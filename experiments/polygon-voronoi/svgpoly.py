"""SVG -> Shapely polygon conversion for the polygon-Voronoi track.

Stage 1 of Track 4.  Parses SVG with ``svgelements`` (which resolves transforms,
converts primitive shapes to paths and applies the presentation attributes for
us), flattens every curve segment to a polyline at a *configurable tolerance*,
resolves subpath nesting into exteriors/holes, and returns validated Shapely
geometry.

The flattening tolerance is the first-class swept parameter for this track: too
coarse loses the shape, too fine turns the Voronoi diagram into a hairball
(report Sec 4.2 / 6.3).  It is expressed in user units and is the maximum
allowed deviation between the true curve and the emitted chord.

Validity matters a great deal here.  An invalid polygon makes both Voronoi
backends emit garbage *silently*, so every polygon leaves this module having
passed ``.is_valid`` or having been repaired, and the repair is recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from svgelements import (
    SVG,
    Arc,
    Close,
    CubicBezier,
    Line,
    Move,
    Path,
    QuadraticBezier,
    Shape,
)

# Segment classes whose geometry is exactly a straight chord.
_STRAIGHT = (Line, Close)
_CURVED = (CubicBezier, QuadraticBezier, Arc)


@dataclass
class Element:
    """One filled SVG element, flattened to Shapely geometry."""

    element_id: str
    index: int
    fill: str | None
    geometry: MultiPolygon
    n_boundary_points: int
    repaired: bool = False
    tag: str = ""

    @property
    def area(self) -> float:
        return self.geometry.area


@dataclass
class Document:
    path: str
    width: float
    height: float
    viewbox: tuple[float, float, float, float]
    elements: list[Element] = field(default_factory=list)

    @property
    def geometry(self) -> BaseGeometry:
        return unary_union([e.geometry for e in self.elements])


# --------------------------------------------------------------------------
# flattening
# --------------------------------------------------------------------------


def _flatten_segment(seg, tolerance: float, max_depth: int = 18) -> list[tuple[float, float]]:
    """Adaptively flatten one svgelements segment, excluding its start point.

    Recursive midpoint-deviation subdivision in ``t`` space.  Works for every
    curved segment type uniformly because svgelements exposes ``point(t)``.
    """
    if isinstance(seg, _STRAIGHT) or not isinstance(seg, _CURVED):
        end = seg.end
        return [(float(end.x), float(end.y))]

    p0 = seg.point(0.0)
    p1 = seg.point(1.0)
    out: list[tuple[float, float]] = []

    def rec(t0: float, t1: float, a, b, depth: int) -> None:
        tm = 0.5 * (t0 + t1)
        m = seg.point(tm)
        ax, ay = float(a.x), float(a.y)
        bx, by = float(b.x), float(b.y)
        mx, my = float(m.x), float(m.y)
        dx, dy = bx - ax, by - ay
        chord = np.hypot(dx, dy)
        if chord < 1e-12:
            dev = np.hypot(mx - ax, my - ay)
        else:
            dev = abs(dx * (ay - my) - (ax - mx) * dy) / chord
        if depth >= max_depth or (dev <= tolerance and chord <= 1e6):
            out.append((bx, by))
            return
        rec(t0, tm, a, m, depth + 1)
        rec(tm, t1, m, b, depth + 1)

    rec(0.0, 1.0, p0, p1, 0)
    return out


def flatten_path(path: Path, tolerance: float) -> list[list[tuple[float, float]]]:
    """Flatten an svgelements Path into a list of closed rings."""
    rings: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for seg in path:
        if isinstance(seg, Move):
            if len(current) >= 3:
                rings.append(current)
            start = seg.end
            current = [(float(start.x), float(start.y))]
            continue
        if not current:
            start = getattr(seg, "start", None)
            if start is None:
                continue
            current = [(float(start.x), float(start.y))]
        current.extend(_flatten_segment(seg, tolerance))
    if len(current) >= 3:
        rings.append(current)
    return rings


# --------------------------------------------------------------------------
# ring nesting -> polygons
# --------------------------------------------------------------------------


def _dedupe(ring: list[tuple[float, float]], eps: float = 1e-9) -> list[tuple[float, float]]:
    out = [ring[0]]
    for p in ring[1:]:
        if abs(p[0] - out[-1][0]) > eps or abs(p[1] - out[-1][1]) > eps:
            out.append(p)
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) < eps and abs(out[0][1] - out[-1][1]) < eps:
        out.pop()
    return out


def rings_to_polygons(rings: Iterable[list[tuple[float, float]]]) -> tuple[MultiPolygon, bool]:
    """Resolve rings into exteriors + holes by containment nesting depth.

    Artwork fills are effectively non-self-intersecting nested rings, so parity
    of nesting depth gives the same answer for both ``nonzero`` and ``evenodd``
    in practice, and is robust to authoring winding mistakes.  Returns the
    geometry and whether a validity repair was needed.
    """
    polys: list[Polygon] = []
    for r in rings:
        r = _dedupe(list(r))
        if len(r) < 3:
            continue
        p = Polygon(r)
        if p.area <= 0:
            continue
        polys.append(p)
    if not polys:
        return MultiPolygon(), False

    order = sorted(range(len(polys)), key=lambda i: polys[i].area, reverse=True)
    depth = [0] * len(polys)
    reps = [p.representative_point() for p in polys]
    for pos, i in enumerate(order):
        for j in order[:pos]:
            if polys[j].contains(reps[i]):
                depth[i] += 1

    shells = [i for i in range(len(polys)) if depth[i] % 2 == 0]
    holes = [i for i in range(len(polys)) if depth[i] % 2 == 1]

    built: list[Polygon] = []
    for i in shells:
        my_holes = []
        for h in holes:
            if depth[h] == depth[i] + 1 and polys[i].contains(reps[h]):
                my_holes.append(list(polys[h].exterior.coords))
        built.append(Polygon(list(polys[i].exterior.coords), my_holes))

    geom = MultiPolygon(built) if len(built) > 1 else built[0]
    repaired = False
    if not geom.is_valid:
        repaired = True
        geom = geom.buffer(0)
        if not geom.is_valid or geom.is_empty:
            from shapely.validation import make_valid

            geom = make_valid(geom)
    if geom.geom_type == "Polygon":
        geom = MultiPolygon([geom])
    elif geom.geom_type != "MultiPolygon":
        parts = [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon"]
        geom = MultiPolygon(parts)
    return geom, repaired


def _count_points(geom: MultiPolygon) -> int:
    n = 0
    for p in geom.geoms:
        n += len(p.exterior.coords)
        for r in p.interiors:
            n += len(r.coords)
    return n


# --------------------------------------------------------------------------
# document level
# --------------------------------------------------------------------------


def load_svg(path: str, tolerance: float = 0.5, min_area: float = 1e-6) -> Document:
    """Parse an SVG into per-element validated Shapely polygons."""
    svg = SVG.parse(path)
    vb = getattr(svg, "viewbox", None)
    if vb is not None:
        viewbox = (float(vb.x), float(vb.y), float(vb.width), float(vb.height))
    else:
        viewbox = (0.0, 0.0, float(svg.width or 0), float(svg.height or 0))

    doc = Document(
        path=path,
        width=float(svg.width or viewbox[2]),
        height=float(svg.height or viewbox[3]),
        viewbox=viewbox,
    )

    idx = 0
    for e in svg.elements():
        if not isinstance(e, Shape):
            continue
        fill = e.values.get("fill")
        if fill in ("none", None) and getattr(e, "fill", None) is None:
            continue
        try:
            p = Path(e)
        except Exception:
            continue
        rings = flatten_path(p, tolerance)
        if not rings:
            continue
        geom, repaired = rings_to_polygons(rings)
        if geom.is_empty or geom.area <= min_area:
            continue
        eid = e.values.get("id") or f"el{idx}"
        doc.elements.append(
            Element(
                element_id=str(eid),
                index=idx,
                fill=str(getattr(e, "fill", fill) or fill),
                geometry=geom,
                n_boundary_points=_count_points(geom),
                repaired=repaired,
            )
        )
        idx += 1
    return doc


def polygon_width_stats(geom: BaseGeometry) -> dict:
    """Cheap width proxies used to make library parameters width-relative."""
    if geom.is_empty:
        return {"area": 0.0, "perimeter": 0.0, "avg_width": 0.0}
    perim = geom.length
    area = geom.area
    # For a long thin ribbon, area ~= width * length and perimeter ~= 2*length.
    avg_width = 4.0 * area / perim if perim > 0 else 0.0
    return {"area": area, "perimeter": perim, "avg_width": avg_width}
