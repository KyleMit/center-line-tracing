"""Failure taxonomy counts (Common Setup: 'tag every failure').

Shared vocabulary across tracks:
  cap artifact . join artifact . outline noise branch . crossing ambiguity .
  disconnected skeleton . missing narrow segment . wrong endpoint .
  excessive curve complexity . raster quantization

These are computed automatically from the graph + source polygon so the counts
are reproducible and comparable, rather than eyeballed.  Where a category
cannot occur for this backend it is reported as 0 with a stated reason, not
silently omitted.
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString, MultiPolygon, Point
from shapely.ops import unary_union

# A terminal branch shorter than this many stroke widths is a spur, not a stroke.
SPUR_WIDTHS = 0.75
# Vertices per stroke-width of arc length above which the polyline is over-dense.
DENSE_VERTICES_PER_WIDTH = 6.0
# Missed-area pieces smaller than this * r_global^2 are width-model slivers.
MIN_ARTIFACT_AREA_R2 = 0.25


def _degrees(graph):
    deg: dict[str, int] = {}
    for e in graph.edges:
        deg[e.frm] = deg.get(e.frm, 0) + 1
        deg[e.to] = deg.get(e.to, 0) + 1
    return deg


def _components(graph) -> int:
    parent: dict[str, str] = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for e in graph.edges:
        ra, rb = find(e.frm), find(e.to)
        if ra != rb:
            parent[ra] = rb
    return len({find(n.id) for n in graph.nodes if n.id in parent}) if parent else 0


def classify(graph, source, recon, n_source_polygons: int,
             avg_width: float | None = None) -> dict:
    """Return {tag: count} plus a few supporting numbers."""
    deg = _degrees(graph)
    node_by_id = {n.id: n for n in graph.nodes}
    radii = [e.medianRadius for e in graph.edges if e.medianRadius]
    r_global = float(np.median(radii)) if radii else (avg_width or 0) / 2
    width = 2 * r_global if r_global else (avg_width or 1.0)

    tags = {k: 0 for k in (
        "cap artifact", "join artifact", "outline noise branch",
        "crossing ambiguity", "disconnected skeleton", "missing narrow segment",
        "wrong endpoint", "excessive curve complexity", "raster quantization")}

    # outline noise branch: terminal branch shorter than SPUR_WIDTHS stroke widths
    for e in graph.edges:
        is_terminal = deg.get(e.frm, 0) == 1 or deg.get(e.to, 0) == 1
        r = e.medianRadius or r_global
        if is_terminal and r > 0 and e.length / (2 * r) < SPUR_WIDTHS:
            tags["outline noise branch"] += 1

    # crossing ambiguity: degree >= 4 junctions
    tags["crossing ambiguity"] = sum(1 for v in deg.values() if v >= 4)

    # disconnected skeleton: more graph components than source polygons
    comps = _components(graph)
    if comps > n_source_polygons:
        tags["disconnected skeleton"] = comps - n_source_polygons

    # missing narrow segment: source polygons with no centerline inside them
    missing = 0
    polys = source.geoms if source.geom_type == "MultiPolygon" else [source]
    lines = graph.to_multilinestring()
    for p in polys:
        if lines.is_empty or not p.intersects(lines):
            missing += 1
    tags["missing narrow segment"] = missing

    # cap / join artifact: unreconstructed source area concentrated near
    # terminal / junction nodes.  Only pieces big enough to see count -- a
    # per-edge constant radius always leaves hairline slivers along a stroke
    # whose width varies, and those are a width-model artifact, not a cap one.
    min_piece = MIN_ARTIFACT_AREA_R2 * max(r_global, 1e-6) ** 2
    cap_area = join_area = 0.0
    if not recon.is_empty and not source.is_empty:
        missed = source.difference(recon)
        if not missed.is_empty:
            pieces = (missed.geoms if hasattr(missed, "geoms") else [missed])
            terms = [(node_by_id[n].x, node_by_id[n].y) for n, d in deg.items()
                     if d == 1 and n in node_by_id]
            juncs = [(node_by_id[n].x, node_by_id[n].y) for n, d in deg.items()
                     if d >= 3 and n in node_by_id]
            for piece in pieces:
                if piece.area < min_piece:
                    continue
                c = piece.representative_point()
                dt = min((abs(complex(x - c.x, y - c.y)) for x, y in terms),
                         default=float("inf"))
                dj = min((abs(complex(x - c.x, y - c.y)) for x, y in juncs),
                         default=float("inf"))
                if min(dt, dj) > 1.5 * width:
                    continue
                if dt <= dj:
                    tags["cap artifact"] += 1
                    cap_area += piece.area
                else:
                    tags["join artifact"] += 1
                    join_area += piece.area

    # wrong endpoint: terminal node whose inscribed radius is much larger than the
    # branch's own median radius -- the axis stopped before the stroke did.
    for e in graph.edges:
        for nid in (e.frm, e.to):
            if deg.get(nid, 0) != 1:
                continue
            n = node_by_id.get(nid)
            if n is None or n.radius is None or not e.medianRadius:
                continue
            if n.radius > 1.6 * e.medianRadius:
                tags["wrong endpoint"] += 1

    # excessive curve complexity
    for e in graph.edges:
        r = e.medianRadius or r_global
        if r <= 0 or e.length <= 0:
            continue
        vpw = len(e.geometry) / (e.length / (2 * r))
        if vpw > DENSE_VERTICES_PER_WIDTH:
            tags["excessive curve complexity"] += 1

    # raster quantization cannot occur: this backend never rasterizes.
    return {
        "tags": tags,
        "cap_missed_area": cap_area,
        "join_missed_area": join_area,
        "components": comps,
        "source_polygons": n_source_polygons,
        "r_global": r_global,
        "note_raster": "n/a - polygon-Voronoi is fully vector, no rasterization step",
    }
