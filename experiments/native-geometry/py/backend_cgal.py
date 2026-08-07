"""CGAL Straight_skeleton_2 backend (report §6.12) — bounded negative experiment.

Same front-end, same graph model, same metrics as the Boost backend, so the two
are directly comparable on the synthetic corpus. The report predicts this
produces the WRONG geometry for pen strokes (§3, §4.5): straight-skeleton
bisectors are equidistant from the supporting LINES of the polygon edges, so the
skeleton is piecewise straight and cannot follow a curved stroke, and it treats
caps by angular bisection rather than by inscribed circles.

Numerical control: CGAL 5.6, `Exact_predicates_inexact_constructions_kernel`,
`create_interior_straight_skeleton_2`. The polygon is passed as doubles with no
lattice snapping (CGAL's kernel has exact predicates on doubles).
"""

from __future__ import annotations

import json
import os
import subprocess
import time

from shapely.geometry import LineString, Polygon
from shapely.prepared import prep

from graph import CenterlineGraph

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "..", "cpp", "straight_skeleton")


def run_skeleton(poly: Polygon, binary=BIN):
    rings = [list(poly.exterior.coords)] + [list(r.coords) for r in poly.interiors]
    lines = [str(len(rings))]
    for ring in rings:
        pts = ring[:-1] if ring[0] == ring[-1] else ring
        lines.append(str(len(pts)) + " " + " ".join(f"{x:.6f} {y:.6f}" for x, y in pts))
    proc = subprocess.run(
        [binary], input="\n".join(lines) + "\n", capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise RuntimeError(f"straight_skeleton failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def straight_skeleton_graph(polygons, source_ids=None, binary=BIN, r_eps=0.25):
    g = CenterlineGraph()
    source_ids = source_ids or [f"p{i}" for i in range(len(polygons))]
    timing = {"engine_ms": 0.0, "filter_ms": 0.0, "segments": 0, "raw_edges": 0}

    for pi, poly in enumerate(polygons):
        src = source_ids[pi]
        timing["segments"] += len(poly.exterior.coords) + sum(
            len(r.coords) for r in poly.interiors
        )
        t0 = time.perf_counter()
        try:
            sk = run_skeleton(poly, binary)
        except RuntimeError:
            continue
        timing["engine_ms"] += (time.perf_counter() - t0) * 1000.0
        timing["raw_edges"] += len(sk["edges"])

        t0 = time.perf_counter()
        pg = prep(poly)
        verts = sk["vertices"]
        vmap = {}
        for e in sk["edges"]:
            a, b = verts[e["a"]], verts[e["b"]]
            pts = [(a["x"], a["y"]), (b["x"], b["y"])]
            line = LineString(pts)
            if line.length <= 0 or not pg.contains(line):
                continue
            ra, rb = a["r"], b["r"]
            if min(ra, rb) < r_eps:
                continue
            for key, p, r in ((e["a"], pts[0], ra), (e["b"], pts[1], rb)):
                if (pi, key) not in vmap:
                    vmap[(pi, key)] = g.add_node(p[0], p[1], r)
            g.add_edge(vmap[(pi, e["a"])], vmap[(pi, e["b"])], pts, [ra, rb], source=src)
        timing["filter_ms"] += (time.perf_counter() - t0) * 1000.0

    return g, timing
