"""SVG -> per-element binary masks, via resvg (deterministic, report §7.1/§15).

The element-splitting logic mirrors the incumbent pipeline
(`src/convert_filled_svg_to_stroked_lines.py`), which learned the hard way that
merging same-colour elements before skeletonizing wrecks images with overlapping
strokes. The incumbent is not imported or modified — Common Setup forbids that —
so the parsing is reimplemented here.

The rasterization contract is documented in `rasterize.mjs` and repeated in
`debug/opencv-tracing/NOTES.md`; Track 3 must match it for the head-to-head
medial-axis-vs-thinning comparison to mean anything.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
SVG_NS = "http://www.w3.org/2000/svg"

# The one place the raster contract is defined numerically.
DEFAULT_SCALE = 4.0
DEFAULT_PAD = 4.0      # crop padding in SVG user units
THRESHOLD = 128


@dataclass
class Element:
    """One filled SVG element, ready to be rendered on its own."""
    id: str
    tag: str
    fill: str
    markup: str


@dataclass
class Raster:
    """A rendered element: binary mask plus the pixel<->SVG coordinate mapping.

    The mask covers a tight crop around the element, not the whole canvas, so
    `origin` carries the crop offset in SVG user units.
    """
    element: Element
    mask: np.ndarray          # bool, (h, w)
    scale: float
    origin: tuple[float, float]
    viewbox: tuple[float, float, float, float]

    def to_svg(self, px, py):
        """Pixel centres -> SVG user units."""
        ox, oy = self.origin
        return (ox + (np.asarray(px, float) + 0.5) / self.scale,
                oy + (np.asarray(py, float) + 0.5) / self.scale)

    def to_svg_len(self, n):
        return np.asarray(n, float) / self.scale


def read_viewbox(svg_text: str) -> tuple[float, float, float, float]:
    match = re.search(r'viewBox="([^"]+)"', svg_text)
    if not match:
        raise ValueError("Input SVG must have a viewBox.")
    values = [float(v) for v in re.split(r"[\s,]+", match.group(1).strip())]
    if len(values) != 4:
        raise ValueError(f"Expected four viewBox values, got {match.group(1)!r}")
    return tuple(values)  # type: ignore[return-value]


def _attr(attrs: str, name: str) -> str | None:
    match = re.search(rf'\b{name}\s*=\s*["\']([^"\']+)["\']', attrs, flags=re.I)
    return match.group(1) if match else None


def _explicit_fill(attrs: str) -> str | None:
    direct = _attr(attrs, "fill")
    if direct and re.match(r"^#[0-9a-fA-F]{6}$", direct):
        return direct.upper()
    style = _attr(attrs, "style")
    if style:
        match = re.search(r"(?:^|;)\s*fill\s*:\s*(#[0-9a-fA-F]{6})", style, flags=re.I)
        if match:
            return match.group(1).upper()
    return None


def _sanitize(attrs: str) -> str:
    attrs = re.sub(
        r'\s(?:fill|stroke|stroke-width|stroke-linecap|stroke-linejoin|vector-effect)'
        r'\s*=\s*["\'][^"\']*["\']',
        "", attrs, flags=re.I)
    style = _attr(attrs, "style")
    if style:
        kept = [p for p in style.split(";")
                if p.strip() and not re.match(r"\s*(fill|stroke)", p, flags=re.I)]
        attrs = re.sub(r'\sstyle\s*=\s*["\'][^"\']*["\']',
                       f' style="{";".join(kept)}"' if kept else "", attrs, flags=re.I)
    return attrs.strip()


def parse_filled_elements(svg_text: str) -> list[Element]:
    elements: list[Element] = []
    fill_stack: list[str | None] = [None]
    token_re = re.compile(r"<g\b([^>]*)>|</g>|<(path|rect|circle|ellipse|polygon)\b([^>]*?)/?>",
                          flags=re.I)

    for match in token_re.finditer(svg_text):
        token = match.group(0)
        if token.lower().startswith("</g"):
            if len(fill_stack) > 1:
                fill_stack.pop()
            continue
        if token.lower().startswith("<g"):
            attrs = match.group(1) or ""
            fill_attr = _attr(attrs, "fill")
            fill = None if (fill_attr and fill_attr.lower() == "none") \
                else _explicit_fill(attrs) or fill_stack[-1]
            fill_stack.append(fill)
            continue

        tag = (match.group(2) or "").lower()
        attrs = match.group(3) or ""
        fill_attr = _attr(attrs, "fill")
        fill = None if (fill_attr and fill_attr.lower() == "none") \
            else _explicit_fill(attrs) or fill_stack[-1]
        if not fill:
            continue

        idx = len(elements)
        elements.append(Element(
            id=f"el{idx:03d}", tag=tag, fill=fill,
            markup=f'<{tag} {_sanitize(attrs)} fill="#ffffff"/>'))

    return elements


def rasterize_elements(svg_text: str, out_dir: Path, scale: float = DEFAULT_SCALE,
                       pad: float = DEFAULT_PAD,
                       elements: list[Element] | None = None) -> tuple[list[Raster], dict]:
    """Render each filled element to its own binary mask at `scale`x the viewBox."""
    viewbox = read_viewbox(svg_text)
    vx, vy, vw, vh = viewbox
    if elements is None:
        elements = parse_filled_elements(svg_text)

    jobs = []
    for el in elements:
        jobs.append({"id": el.id, "svg": "\n".join([
            f'<svg xmlns="{SVG_NS}" version="1.1" viewBox="{vx} {vy} {vw} {vh}">',
            "<!--BG-->",
            el.markup,
            "</svg>",
        ])})

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"outDir": str(out_dir), "scale": scale, "pad": pad,
                          "originX": vx, "originY": vy, "jobs": jobs})
    proc = subprocess.run(["node", str(HERE / "rasterize.mjs")],
                          input=payload.encode("utf-8"),
                          capture_output=True, check=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    result = json.loads(proc.stdout)

    rasters = []
    for el, entry in zip(elements, result["written"]):
        if entry.get("empty"):
            continue
        arr = np.array(Image.open(entry["png"]).convert("RGB"))
        rasters.append(Raster(element=el, mask=arr[..., 0] > THRESHOLD,
                              scale=scale, origin=(entry["x0"], entry["y0"]),
                              viewbox=viewbox))

    meta = {"renderer": "resvg-js", "renderer_version": result["resvg"],
            "scale": scale, "crop_pad_user_units": pad,
            "threshold": f"red > {THRESHOLD}", "fit_to": "zoom",
            "crop": "per-element bbox expanded by pad, filled opaque black",
            "pixel_to_svg": "svg = cropOrigin + (pixelIndex + 0.5) / scale"}
    return rasters, meta


def rasterize_whole(svg_text: str, out_png: Path, scale: float = DEFAULT_SCALE) -> np.ndarray:
    """Render the entire drawing's filled area as one canvas-sized binary mask."""
    viewbox = read_viewbox(svg_text)
    vx, vy, vw, vh = viewbox
    body = "\n".join(el.markup for el in parse_filled_elements(svg_text))
    doc = "\n".join([
        f'<svg xmlns="{SVG_NS}" version="1.1" viewBox="{vx} {vy} {vw} {vh}">',
        f'<rect x="{vx}" y="{vy}" width="{vw}" height="{vh}" fill="#000000"/>',
        body, "</svg>"])
    out_png.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"outDir": str(out_png.parent), "scale": scale, "pad": 0,
                          "originX": vx, "originY": vy,
                          "jobs": [{"id": out_png.stem, "svg": doc}]})
    proc = subprocess.run(["node", str(HERE / "rasterize.mjs")],
                          input=payload.encode("utf-8"), capture_output=True, check=True)
    entry = json.loads(proc.stdout)["written"][0]
    arr = np.array(Image.open(entry["png"]).convert("RGB"))
    return arr[..., 0] > THRESHOLD
