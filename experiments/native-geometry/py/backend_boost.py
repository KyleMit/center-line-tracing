"""Boost.Polygon segment-site Voronoi backend (report §6.10).

Pipeline: shapely Polygon -> integer segment sites -> `voronoi_medial` (C++)
-> keep finite primary Voronoi edges lying strictly inside the polygon
-> CenterlineGraph.

Numerical control, recorded so results are reproducible (report §15):

* Boost 1.83.0, `boost/polygon/voronoi.hpp`, `voronoi_diagram<double>`.
* Input coordinates are multiplied by SCALE and rounded to int32; SCALE=100
  means the sites are exact on a 0.01 user-unit lattice, and the Voronoi
  construction is then exact (Boost's predicates are exact for integer input).
* Parabolic Voronoi edges (point-site vs segment-site) are discretized with a
  chord tolerance of PARABOLA_TOL user units.
* Boundary flattening tolerance is svgpoly.DEFAULT_FLATNESS user units.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

from shapely import set_precision
from shapely.geometry import LineString, Polygon
from shapely.prepared import prep

from graph import CenterlineGraph

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "..", "cpp", "voronoi_medial")

SCALE = 100.0
PARABOLA_TOL = 0.1  # user units


def _ring_segments(coords, scale, seen):
    segs = []
    pts = [(int(round(x * scale)), int(round(y * scale))) for x, y in coords]
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        if a == b:
            continue
        key = (a, b) if a < b else (b, a)
        if key in seen:
            continue
        seen.add(key)
        segs.append((a[0], a[1], b[0], b[1]))
    if pts[0] != pts[-1]:
        a, b = pts[-1], pts[0]
        if a != b:
            key = (a, b) if a < b else (b, a)
            if key not in seen:
                seen.add(key)
                segs.append((a[0], a[1], b[0], b[1]))
    return segs


def polygon_segments(poly: Polygon, scale=SCALE):
    seen = set()
    segs = _ring_segments(list(poly.exterior.coords), scale, seen)
    for ring in poly.interiors:
        segs.extend(_ring_segments(list(ring.coords), scale, seen))
    return segs


def run_voronoi(segments, parabola_tol=PARABOLA_TOL, scale=SCALE, binary=BIN):
    """Invoke the C++ kernel. Returns the raw diagram dict (scaled units)."""
    payload = [str(len(segments))]
    payload.extend(" ".join(str(v) for v in s) for s in segments)
    proc = subprocess.run(
        [binary, str(parabola_tol * scale)],
        input="\n".join(payload) + "\n",
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"voronoi_medial failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def medial_axis_graph(
    polygons,
    source_ids=None,
    scale=SCALE,
    parabola_tol=PARABOLA_TOL,
    binary=BIN,
    r_eps=0.25,
):
    """Build a CenterlineGraph from a list of shapely Polygons."""
    g = CenterlineGraph()
    source_ids = source_ids or [f"p{i}" for i in range(len(polygons))]
    timing = {"voronoi_ms": 0.0, "filter_ms": 0.0, "segments": 0, "raw_edges": 0}

    snapped = []
    for pi, poly in enumerate(polygons):
        # Snap to the same integer lattice the kernel will see, and re-validate.
        # Boost's Voronoi builder requires non-crossing segment sites; rounding a
        # near-degenerate boundary can create crossings, which produce NaN
        # vertices. Snapping first (and letting shapely repair the result) makes
        # the polygon we filter against *identical* to the sites we feed in.
        sp = set_precision(poly, 1.0 / scale)
        if sp.is_empty:
            continue
        if not sp.is_valid:
            sp = sp.buffer(0)
        for part in getattr(sp, "geoms", [sp]):
            if isinstance(part, Polygon) and part.area > 0:
                snapped.append((source_ids[pi], part))

    for pi, (src, poly) in enumerate(snapped):
        segs = polygon_segments(poly, scale)
        if len(segs) < 3:
            continue
        timing["segments"] += len(segs)

        t0 = time.perf_counter()
        diagram = run_voronoi(segs, parabola_tol, scale, binary)
        timing["voronoi_ms"] += (time.perf_counter() - t0) * 1000.0
        timing["raw_edges"] += len(diagram["edges"])

        t0 = time.perf_counter()
        verts = diagram["vertices"]
        # Interior test: an edge is medial only if it lies strictly inside.
        # Voronoi edges radiating to convex corners end ON the boundary and are
        # rejected by `contains`, which is exactly the filtering we want.
        pg = prep(poly)
        vmap = {}
        for e in diagram["edges"]:
            pts = [(x / scale, y / scale) for x, y in e["pts"]]
            if len(pts) < 2:
                continue
            line = LineString(pts)
            if line.length <= 0:
                continue
            if not pg.contains(line):
                continue
            ra = verts[e["a"]]["r"] / scale
            rb = verts[e["b"]]["r"] / scale
            # Every convex vertex of the flattened polygon spawns a Voronoi
            # "spoke" whose far endpoint sits ON the boundary with clearance 0.
            # Those spokes are an artifact of the polygonization, not medial
            # structure, and the integer lattice lets a few of them slip past
            # the containment test. Dropping edges that reach clearance ~0 is
            # the one geometric filter this backend needs.
            if min(ra, rb) < r_eps:
                continue
            radii = _interp_radii(pts, ra, rb)
            ka, kb = (pi, e["a"]), (pi, e["b"])
            if ka not in vmap:
                vmap[ka] = g.add_node(pts[0][0], pts[0][1], ra)
            if kb not in vmap:
                vmap[kb] = g.add_node(pts[-1][0], pts[-1][1], rb)
            g.add_edge(vmap[ka], vmap[kb], pts, radii, source=src)
        timing["filter_ms"] += (time.perf_counter() - t0) * 1000.0

    return g, timing


def _interp_radii(pts, ra, rb):
    """Clearance radius along an edge.

    Exact at the two Voronoi vertices (distance to the nearest site, computed in
    the kernel); linearly interpolated by arc length at the intermediate points
    produced by parabola discretization.
    """
    if len(pts) == 2:
        return [ra, rb]
    import math

    d = [0.0]
    for i in range(1, len(pts)):
        d.append(d[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    total = d[-1] or 1.0
    return [ra + (rb - ra) * (t / total) for t in d]
