"""Bézier fitting + stroked-SVG emission for the skimage-skan track."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

from graphmodel import CenterlineGraph

HERE = Path(__file__).resolve().parent
FIT_JS = HERE / "fit_curve.js"
REPO = HERE.parent.parent


def fit_beziers(graph: CenterlineGraph, error_frac: float = 0.06,
                error_floor: float = 0.25, error_ceiling: float = 3.0) -> int:
    """Fit cubics to every edge in place.  Tolerance scales with local radius.

    A fat stroke tolerates more fitting error than a thin one for the same
    visual result, so the tolerance is a fraction of the median radius rather
    than an absolute number of user units.
    """
    jobs = []
    for edge in graph.edges:
        if len(edge.geometry) < 2:
            continue
        r = edge.medianRadius or 1.0
        err = float(np.clip(error_frac * 2 * r, error_floor, error_ceiling))
        pts = list(edge.fitPoints or edge.geometry)
        corners = list(edge.fitCorners if edge.fitPoints else edge.corners)
        if edge.closed and (pts[0] != pts[-1]):
            pts = pts + [pts[0]]
        jobs.append({"id": edge.id, "points": pts, "corners": corners,
                     "error": err, "closed": edge.closed})
    if not jobs:
        return 0
    proc = subprocess.run(["node", str(FIT_JS)], input=json.dumps({"jobs": jobs}),
                          capture_output=True, text=True, cwd=str(REPO))
    if proc.returncode != 0:
        raise RuntimeError(f"fit-curve failed: {proc.stderr[:2000]}")
    by_id = {r["id"]: r["beziers"] for r in json.loads(proc.stdout)["results"]}
    total = 0
    for edge in graph.edges:
        beziers = by_id.get(edge.id, [])
        edge.beziers = beziers
        total += len(beziers)
    return total


def _fmt(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def bezier_path_d(beziers: list[list[list[float]]], closed: bool) -> str:
    if not beziers:
        return ""
    parts = [f"M{_fmt(beziers[0][0][0])},{_fmt(beziers[0][0][1])}"]
    prev_end = beziers[0][0]
    for b in beziers:
        p0, c1, c2, p3 = b
        if abs(p0[0] - prev_end[0]) > 1e-6 or abs(p0[1] - prev_end[1]) > 1e-6:
            parts.append(f"M{_fmt(p0[0])},{_fmt(p0[1])}")
        parts.append(
            f"C{_fmt(c1[0])},{_fmt(c1[1])} {_fmt(c2[0])},{_fmt(c2[1])} "
            f"{_fmt(p3[0])},{_fmt(p3[1])}"
        )
        prev_end = p3
    if closed:
        parts.append("Z")
    return "".join(parts)


def polyline_path_d(points: list[list[float]], closed: bool) -> str:
    if len(points) < 2:
        return ""
    d = "M" + " L".join(f"{_fmt(x)},{_fmt(y)}" for x, y in points)
    return d + ("Z" if closed else "")


def stroked_svg(graph: CenterlineGraph, fills: dict[str, str],
                use_beziers: bool = True,
                min_width: float = 0.0, max_width: float = 1e9,
                width_scale: float = 1.0) -> str:
    x, y, w, h = graph.viewBox
    out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'viewBox="{_fmt(x)} {_fmt(y)} {_fmt(w)} {_fmt(h)}">',
    ]
    for edge in graph.edges:
        d = (bezier_path_d(edge.beziers, edge.closed) if use_beziers
             else polyline_path_d(edge.geometry, edge.closed))
        if not d:
            continue
        width = float(np.clip(2.0 * (edge.medianRadius or 0.5) * width_scale,
                              min_width, max_width))
        colour = fills.get(edge.sourceElementId or "", "#000000")
        out.append(
            f'<path d="{d}" fill="none" stroke="{colour}" '
            f'stroke-width="{_fmt(width)}" stroke-linecap="round" stroke-linejoin="round"/>'
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def bezier_segment_count(graph: CenterlineGraph) -> int:
    return int(sum(len(e.beziers) for e in graph.edges))


def control_point_count(graph: CenterlineGraph) -> int:
    return int(sum(len(e.beziers) * 3 + 1 for e in graph.edges if e.beziers))
