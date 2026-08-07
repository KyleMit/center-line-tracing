"""SVG -> flattened shapely polygons.

Shared front-end for every engine in Track 7 (Boost.Polygon Voronoi, CGAL
straight skeleton, PostGIS). Keeping this identical across engines is what makes
the comparison clean: they all see exactly the same flattened polygon.

Flattening is adaptive (recursive midpoint subdivision against a flatness
tolerance in user units), so the segment count scales with curvature rather than
with arc length.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from svgelements import SVG, Path, Shape, Close, Line, Move

DEFAULT_FLATNESS = 0.05  # user units; max chord deviation when flattening curves


@dataclass
class FilledElement:
    """One filled SVG element, flattened to polygons."""

    element_id: str
    fill: str
    polygons: list  # list[Polygon]
    rings: list = field(default_factory=list)  # raw flattened rings, for debugging


def _flatten_segment(seg, flatness):
    """Return interior sample points (exclusive of the start point) for a segment."""
    if isinstance(seg, (Line, Close, Move)):
        return [(seg.end.x, seg.end.y)]

    pts = []

    def rec(t0, p0, t1, p1, depth):
        tm = 0.5 * (t0 + t1)
        pm = seg.point(tm)
        # distance from the curve midpoint to the chord
        cx, cy = 0.5 * (p0[0] + p1[0]), 0.5 * (p0[1] + p1[1])
        d = math.hypot(pm.x - cx, pm.y - cy)
        if d <= flatness or depth >= 16:
            pts.append((p1[0], p1[1]))
            return
        rec(t0, p0, tm, (pm.x, pm.y), depth + 1)
        rec(tm, (pm.x, pm.y), t1, p1, depth + 1)

    start, end = seg.point(0.0), seg.point(1.0)
    rec(0.0, (start.x, start.y), 1.0, (end.x, end.y), 0)
    return pts


def flatten_path(path: Path, flatness=DEFAULT_FLATNESS):
    """Flatten an svgelements Path into a list of closed rings (point lists)."""
    rings = []
    current = []
    for seg in path.segments():
        if isinstance(seg, Move):
            if len(current) >= 3:
                rings.append(current)
            current = [(seg.end.x, seg.end.y)]
            continue
        if not current:
            p = seg.point(0.0)
            current = [(p.x, p.y)]
        current.extend(_flatten_segment(seg, flatness))
    if len(current) >= 3:
        rings.append(current)

    out = []
    for ring in rings:
        # drop consecutive duplicates, then close
        clean = [ring[0]]
        for p in ring[1:]:
            if abs(p[0] - clean[-1][0]) > 1e-12 or abs(p[1] - clean[-1][1]) > 1e-12:
                clean.append(p)
        if len(clean) >= 3:
            if clean[0] != clean[-1]:
                clean.append(clean[0])
            out.append(clean)
    return out


def rings_to_polygons(rings):
    """Combine rings into polygons with holes using the even-odd rule (XOR).

    Even-odd matches how these coloring-book SVGs are authored (outer outline
    plus interior holes) and is exact regardless of ring winding.
    """
    polys = []
    for ring in rings:
        try:
            p = Polygon(ring)
        except Exception:
            continue
        if not p.is_valid:
            p = p.buffer(0)
        if p.is_empty or p.area <= 0:
            continue
        polys.append(p)
    if not polys:
        return []
    acc = polys[0]
    for p in polys[1:]:
        acc = acc.symmetric_difference(p)
    acc = acc.buffer(0)
    if isinstance(acc, Polygon):
        return [acc] if not acc.is_empty else []
    if isinstance(acc, MultiPolygon):
        return [g for g in acc.geoms if g.area > 0]
    return [g for g in getattr(acc, "geoms", []) if isinstance(g, Polygon) and g.area > 0]


def load_filled_elements(svg_path, flatness=DEFAULT_FLATNESS, min_area=1.0):
    """Parse an SVG and return its filled elements as flattened polygons."""
    svg = SVG.parse(svg_path, reify=True, ppi=96.0)
    elements = []
    idx = 0
    for el in svg.elements():
        if not isinstance(el, Shape):
            continue
        fill = getattr(el, "fill", None)
        if fill is None or fill.value is None or str(fill) == "none":
            continue
        try:
            path = Path(el)
        except Exception:
            continue
        rings = flatten_path(path, flatness)
        polys = [p for p in rings_to_polygons(rings) if p.area >= min_area]
        if not polys:
            continue
        eid = el.id or f"el{idx}"
        idx += 1
        elements.append(
            FilledElement(element_id=eid, fill=str(fill), polygons=polys, rings=rings)
        )
    return elements


def svg_viewbox(svg_path):
    svg = SVG.parse(svg_path, reify=True, ppi=96.0)
    return float(svg.width), float(svg.height)


def total_geometry(elements):
    """Union of every filled element — the shape we must reconstruct."""
    geoms = [p for e in elements for p in e.polygons]
    if not geoms:
        return None
    return unary_union(geoms)
