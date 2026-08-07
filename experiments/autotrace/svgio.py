"""SVG parsing / sub-SVG construction / deterministic rasterisation.

Responsibilities:
  * enumerate the *filled* elements of an input SVG (with inherited fill and
    accumulated ancestor transforms),
  * build a minimal sub-SVG for any subset of them, rendered black-on-transparent,
  * rasterise it through resvg (report §7.1 / §15) at a controlled scale,
  * hand back a binary mask plus the affine that maps mask pixels back into the
    ORIGINAL SVG user coordinate space.

The pixel->user affine is the whole ball game for this track: get it wrong and
autotrace looks far worse than it is.  It is deliberately a single object
(`Frame`) so there is exactly one place to be wrong.
"""

from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

# Elements that describe a fillable region.  Anything else (notably the
# <g stroke-width=... fill="none"> seam groups in dinosaur-wide) is passed
# through to the output verbatim -- it is already a stroke, there is nothing
# to recover from it.
SHAPE_TAGS = {"path", "rect", "circle", "ellipse", "polygon", "polyline", "line"}


def _local(tag: str) -> str:
    return tag.split("}")[-1]


@dataclass
class Element:
    """One filled source element, with everything needed to re-render it alone."""

    index: int
    tag: str
    attrib: dict
    fill: str
    ancestor_transforms: list  # outermost -> innermost
    xml: str  # serialised, fill forced to #000000

    @property
    def eid(self) -> str:
        return f"e{self.index:03d}"


@dataclass
class Frame:
    """Maps mask pixel coords <-> original SVG user coords.

    A pixel *centre* (px + 0.5, py + 0.5) corresponds to user coordinate
    (ox + (px + 0.5) / scale, oy + (py + 0.5) / scale).
    """

    ox: float
    oy: float
    scale: float
    width: int
    height: int

    def px_to_user(self, pts: np.ndarray) -> np.ndarray:
        """pts: (N,2) in pixel space (already pixel-centre convention)."""
        out = np.asarray(pts, dtype=float) / self.scale
        out[:, 0] += self.ox
        out[:, 1] += self.oy
        return out

    def len_px_to_user(self, v):
        return v / self.scale


class Document:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.tree = ET.parse(self.path)
        self.root = self.tree.getroot()
        vb = self.root.get("viewBox")
        if vb:
            self.vx, self.vy, self.vw, self.vh = [float(t) for t in re.split(r"[,\s]+", vb.strip())]
        else:
            self.vx = self.vy = 0.0
            self.vw = float(self.root.get("width", 1000))
            self.vh = float(self.root.get("height", 1000))
        self.elements: list[Element] = []
        self.passthrough: list[str] = []
        self._walk(self.root, [], None)

    def _walk(self, node, transforms, inherited_fill):
        for child in list(node):
            tag = _local(child.tag)
            fill = child.get("fill", inherited_fill)
            tr = transforms + ([child.get("transform")] if child.get("transform") else [])
            if tag == "g":
                # A group that is itself unfilled and only carries strokes is a
                # passthrough (dinosaur-wide's seam group).  Recurse regardless:
                # a <g fill="#98d529"> in landscape-square holds real fills.
                if fill in (None, "none") and child.get("stroke"):
                    self.passthrough.append(_tostr(child))
                    continue
                self._walk(child, tr, fill)
                continue
            if tag not in SHAPE_TAGS:
                continue
            if fill in (None, "none"):
                self.passthrough.append(_tostr(child))
                continue
            attrib = dict(child.attrib)
            black = ET.Element(f"{{{SVG_NS}}}{tag}", {**attrib, "fill": "#000000"})
            black.attrib.pop("stroke", None)
            self.elements.append(
                Element(
                    index=len(self.elements),
                    tag=tag,
                    attrib=attrib,
                    fill=fill,
                    ancestor_transforms=transforms,
                    xml=_tostr(black),
                )
            )

    # ---- sub-SVG construction -------------------------------------------------

    def sub_svg(self, elements, box) -> str:
        """A minimal SVG containing only `elements`, black, cropped to `box`.

        No width/height: the renderer's fitTo drives the output size, so the
        pixel scale is decided in exactly one place.
        """
        bx, by, bw, bh = box
        parts = [
            f'<svg xmlns="{SVG_NS}" version="1.1" '
            f'viewBox="{bx} {by} {bw} {bh}" width="{bw}" height="{bh}">'
        ]
        for el in elements:
            opens = ""
            closes = ""
            for t in el.ancestor_transforms:
                opens += f'<g transform="{t}">'
                closes += "</g>"
            parts.append(opens + el.xml + closes)
        parts.append("</svg>")
        return "".join(parts)


def _tostr(node) -> str:
    s = ET.tostring(node, encoding="unicode")
    return re.sub(r'\sxmlns(:\w+)?="[^"]*"', "", s)


# ---- rasterisation ------------------------------------------------------------


class Renderer:
    """Long-lived node/resvg subprocess; one startup for a whole drawing."""

    def __init__(self, scratch: Path):
        self.scratch = Path(scratch)
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            ["node", str(HERE / "render.mjs")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._n = 0

    def mask(self, svg: str, box, scale: float, threshold: int = 128):
        """Render `svg` (viewBox == box) at `scale` px per user unit -> (bool mask, Frame).

        Returns a mask whose [row, col] indexing is [y, x].
        """
        bx, by, bw, bh = box
        w = max(1, int(round(bw * scale)))
        h = max(1, int(round(bh * scale)))
        self._n += 1
        raw = self.scratch / f"r{self._n:05d}.raw"
        job = {"svg": svg, "width": w, "height": h, "out": str(raw)}
        self.proc.stdin.write(json.dumps(job) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("renderer died")
        res = json.loads(line)
        rw, rh = res["w"], res["h"]
        buf = np.frombuffer(raw.read_bytes(), dtype=np.uint8).reshape(rh, rw, 4)
        alpha = buf[:, :, 3]
        mask = alpha >= threshold
        raw.unlink(missing_ok=True)
        # resvg fits to width; the derived height can differ by a rounding unit
        # from `h`, so the frame's true scale is measured from what came back.
        eff = rw / bw
        return mask, Frame(ox=bx, oy=by, scale=eff, width=rw, height=rh)

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
