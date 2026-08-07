"""Run `autotrace -centerline` on a binary mask and parse its SVG back.

AutoTrace's SVG writer (src/output-svg.c) emits only M / L / C commands and
already flips y (`height - y`), so its output coordinates are top-down pixel
coordinates in the same frame as the mask we fed it.  It writes each spline
list as a subpath; consecutive lists of the same colour are merged into one
<path> element, so subpaths -- not path elements -- are the unit of geometry.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

AUTOTRACE = shutil.which("autotrace") or "/workspace/autotrace/autotrace/autotrace"


@dataclass
class TraceParams:
    corner_threshold: float = 100.0
    corner_always_threshold: float = 60.0
    corner_surround: int = 4
    error_threshold: float = 2.0
    filter_iterations: int = 4
    despeckle_level: int = 0
    despeckle_tightness: float = 2.0
    line_threshold: float = 1.0
    line_reversion_threshold: float = 0.01
    preserve_width: bool = False

    def argv(self):
        a = [
            "-centerline",
            "-background-color", "FFFFFF",
            "-corner-threshold", f"{self.corner_threshold}",
            "-corner-always-threshold", f"{self.corner_always_threshold}",
            "-corner-surround", f"{self.corner_surround}",
            "-error-threshold", f"{self.error_threshold}",
            "-filter-iterations", f"{self.filter_iterations}",
            "-despeckle-level", f"{self.despeckle_level}",
            "-despeckle-tightness", f"{self.despeckle_tightness}",
            "-line-threshold", f"{self.line_threshold}",
            "-line-reversion-threshold", f"{self.line_reversion_threshold}",
        ]
        if self.preserve_width:
            a.append("-preserve-width")
        return a

    def tag(self):
        return (
            f"ct{self.corner_threshold:g}_et{self.error_threshold:g}"
            f"_fi{self.filter_iterations}_ds{self.despeckle_level}"
        )


@dataclass
class SubPath:
    """One traced subpath, in *mask pixel* coordinates."""

    segments: list  # list of ('L', p1) or ('C', c1, c2, p1); start held separately
    start: tuple
    stroke: str = "#000000"
    outline_like: bool = False  # filled by width.py
    stats: dict = field(default_factory=dict)

    def points(self, flatness: float = 0.4) -> np.ndarray:
        """Adaptive-ish flattening to a polyline, ~`flatness` px chord error."""
        pts = [np.array(self.start, dtype=float)]
        cur = pts[0]
        for seg in self.segments:
            if seg[0] == "L":
                p = np.array(seg[1], dtype=float)
                n = max(1, int(np.hypot(*(p - cur)) / 2.0))
                for i in range(1, n + 1):
                    pts.append(cur + (p - cur) * (i / n))
                cur = p
            else:
                c1 = np.array(seg[1], dtype=float)
                c2 = np.array(seg[2], dtype=float)
                p = np.array(seg[3], dtype=float)
                # step count from the control polygon length
                poly = np.hypot(*(c1 - cur)) + np.hypot(*(c2 - c1)) + np.hypot(*(p - c2))
                n = max(2, min(120, int(np.sqrt(poly / max(flatness, 1e-6)) * 1.5)))
                for i in range(1, n + 1):
                    t = i / n
                    mt = 1 - t
                    q = (
                        mt ** 3 * cur
                        + 3 * mt ** 2 * t * c1
                        + 3 * mt * t ** 2 * c2
                        + t ** 3 * p
                    )
                    pts.append(q)
                cur = p
        arr = np.array(pts)
        # drop consecutive duplicates
        keep = np.ones(len(arr), dtype=bool)
        keep[1:] = np.any(np.abs(np.diff(arr, axis=0)) > 1e-9, axis=1)
        return arr[keep]

    @property
    def end(self):
        if not self.segments:
            return self.start
        return self.segments[-1][-1]

    def is_closed(self, tol=1.5):
        return float(np.hypot(*(np.array(self.end) - np.array(self.start)))) <= tol

    def d(self, xform=None):
        """SVG path data; `xform` maps a pixel point -> output-space point."""
        f = xform or (lambda p: p)
        s = f(self.start)
        out = [f"M {s[0]:.3f} {s[1]:.3f}"]
        for seg in self.segments:
            if seg[0] == "L":
                p = f(seg[1])
                out.append(f"L {p[0]:.3f} {p[1]:.3f}")
            else:
                c1, c2, p = f(seg[1]), f(seg[2]), f(seg[3])
                out.append(
                    f"C {c1[0]:.3f} {c1[1]:.3f} {c2[0]:.3f} {c2[1]:.3f} {p[0]:.3f} {p[1]:.3f}"
                )
        return " ".join(out)

    def n_segments(self):
        return len(self.segments)

    def n_beziers(self):
        return sum(1 for s in self.segments if s[0] == "C")


_NUM = r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?"
_TOK = re.compile(rf"([MLC])\s*((?:\s*{_NUM}[,\s]*)+)")


def write_pbm(mask: np.ndarray, path: Path):
    """Binary PBM (P4).  1 == black == shape.  No palette, no antialiasing."""
    h, w = mask.shape
    packed = np.packbits(mask.astype(np.uint8), axis=1)
    with open(path, "wb") as fh:
        fh.write(f"P4\n{w} {h}\n".encode())
        fh.write(packed.tobytes())


def run(mask: np.ndarray, workdir: Path, params: TraceParams, stem="m"):
    """Trace a binary mask.  Returns (subpaths, seconds, raw_svg_text)."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    pbm = workdir / f"{stem}.pbm"
    out = workdir / f"{stem}.svg"
    write_pbm(mask, pbm)
    t0 = time.perf_counter()
    proc = subprocess.run(
        [AUTOTRACE, *params.argv(), "-input-format", "pbm",
         "-output-format", "svg", "-output-file", str(out), str(pbm)],
        capture_output=True, text=True, timeout=900,
    )
    dt = time.perf_counter() - t0
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError(f"autotrace failed rc={proc.returncode}: {proc.stderr[:400]}")
    text = out.read_text()
    return parse_svg(text), dt, text


def parse_svg(text: str):
    """AutoTrace SVG -> list[SubPath] in pixel coordinates."""
    subpaths = []
    for m in re.finditer(r'<path\s+style="([^"]*)"\s+d="([^"]*)"', text):
        style, d = m.group(1), m.group(2)
        cm = re.search(r"stroke:\s*(#[0-9a-fA-F]{6})", style)
        stroke = cm.group(1) if cm else "#000000"
        cur = None
        sp = None
        for tm in _TOK.finditer(d):
            cmd = tm.group(1)
            nums = [float(x) for x in re.findall(_NUM, tm.group(2))]
            if cmd == "M":
                if sp is not None and sp.segments:
                    subpaths.append(sp)
                cur = (nums[0], nums[1])
                sp = SubPath(segments=[], start=cur, stroke=stroke)
            elif cmd == "L":
                for i in range(0, len(nums) - 1, 2):
                    cur = (nums[i], nums[i + 1])
                    sp.segments.append(("L", cur))
            elif cmd == "C":
                for i in range(0, len(nums) - 5, 6):
                    cur = (nums[i + 4], nums[i + 5])
                    sp.segments.append(
                        ("C", (nums[i], nums[i + 1]), (nums[i + 2], nums[i + 3]), cur)
                    )
        if sp is not None and sp.segments:
            subpaths.append(sp)
    return subpaths


def version():
    try:
        r = subprocess.run([AUTOTRACE, "--version"], capture_output=True, text=True, timeout=30)
        return (r.stdout + r.stderr).strip().splitlines()[0]
    except Exception as e:  # pragma: no cover
        return f"unavailable: {e}"
