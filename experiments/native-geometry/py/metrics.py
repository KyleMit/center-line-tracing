"""Re-stroke reconstruction scoring (Common Setup §Metrics, report §11).

All geometry metrics are computed on exact shapely geometry rather than pixels,
so they are deterministic and resolution-independent (report §15). The raster
pixel-diff from `src/compare.js` is kept separately for continuity with the
incumbent's numbers.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString, MultiLineString, Point


def _sample(geom, step):
    """Sample points along a (Multi)LineString every `step` units."""
    lines = geom.geoms if hasattr(geom, "geoms") else [geom]
    pts = []
    for ln in lines:
        if ln.length == 0:
            continue
        n = max(2, int(math.ceil(ln.length / step)))
        for i in range(n + 1):
            p = ln.interpolate(i / n, normalized=True)
            pts.append((p.x, p.y))
    return pts


def _dists(points, target):
    return [target.distance(Point(p)) for p in points]


def _stats(vals):
    if not vals:
        return {"median": None, "p95": None, "max": None, "mean": None}
    s = sorted(vals)
    n = len(s)
    return {
        "median": round(s[n // 2], 4),
        "p95": round(s[min(n - 1, int(0.95 * n))], 4),
        "max": round(s[-1], 4),
        "mean": round(sum(s) / n, 4),
    }


def area_metrics(orig, recon):
    if orig is None or recon is None:
        return {"iou": 0.0, "symdiff_area": None, "symdiff_frac": None}
    inter = orig.intersection(recon).area
    union = orig.union(recon).area
    sym = orig.symmetric_difference(recon).area
    return {
        "iou": round(inter / union, 5) if union else 0.0,
        "symdiff_area": round(sym, 3),
        "symdiff_frac": round(sym / orig.area, 5) if orig.area else None,
        "orig_area": round(orig.area, 3),
        "recon_area": round(recon.area, 3),
    }


def boundary_metrics(orig, recon, step=1.0):
    """Nearest-distance error between the two boundaries, both directions."""
    if orig is None or recon is None:
        return {}
    ob, rb = orig.boundary, recon.boundary
    d1 = _dists(_sample(rb, step), ob)
    d2 = _dists(_sample(ob, step), rb)
    return {"boundary_recon_to_orig": _stats(d1), "boundary_orig_to_recon": _stats(d2)}


def centerline_metrics(graph, ground_truth_paths, step=1.0):
    """Recovered centerline vs the known source path (synthetic corpus only).

    Reports both directions: recovered->truth catches spurious branches,
    truth->recovered catches missed structure.
    """
    if not ground_truth_paths:
        return {}
    gt = MultiLineString([LineString(p) for p in ground_truth_paths if len(p) >= 2])
    rec_lines = [
        LineString(e.geometry) for e in graph.edges.values() if len(e.geometry) >= 2
    ]
    if not rec_lines:
        return {"centerline_recovered_to_truth": _stats([]), "centerline_truth_to_recovered": _stats([])}
    rec = MultiLineString(rec_lines)
    d1 = _dists(_sample(rec, step), gt)
    d2 = _dists(_sample(gt, step), rec)
    return {
        "centerline_recovered_to_truth": _stats(d1),
        "centerline_truth_to_recovered": _stats(d2),
        "length_recovered": round(rec.length, 3),
        "length_truth": round(gt.length, 3),
        "length_ratio": round(rec.length / gt.length, 4) if gt.length else None,
    }


def width_metrics(graph, true_radius=None):
    radii = [r for e in graph.edges.values() for r in e.radii]
    if not radii:
        return {}
    s = sorted(radii)
    n = len(s)
    med = s[n // 2]
    out = {
        "radius_median": round(med, 4),
        "radius_p05": round(s[int(0.05 * n)], 4),
        "radius_p95": round(s[min(n - 1, int(0.95 * n))], 4),
        "radius_spread": round((s[min(n - 1, int(0.95 * n))] - s[int(0.05 * n)]) / med, 4)
        if med
        else None,
    }
    if true_radius:
        errs = [abs(r - true_radius) for r in radii]
        out["radius_abs_err"] = _stats(errs)
        out["radius_rel_err_median"] = round(_stats(errs)["median"] / true_radius, 4)
    return out


def clearance_metrics(graph, geom, max_nodes=4000):
    """How medial is this axis, really?

    For a true Euclidean medial axis the radius carried at each node IS the
    distance from that node to the shape boundary. For a straight skeleton the
    stored value is the offset time — the distance to the SUPPORTING LINES of
    the polygon edges — which the report (§4.5, §6.12) says is not the same
    thing in a non-convex polygon. This measures the discrepancy directly, and
    is the cleanest engine-level discriminator we have.
    """
    if geom is None or not graph.nodes:
        return {}
    b = geom.boundary
    nodes = list(graph.nodes.values())
    stride = max(1, len(nodes) // max_nodes)
    errs, rel = [], []
    for n in nodes[::stride]:
        p = Point(n.x, n.y)
        if not geom.contains(p):
            continue
        d = b.distance(p)
        errs.append(abs(d - n.radius))
        if d > 1e-9:
            rel.append(abs(d - n.radius) / d)
    if not errs:
        return {}
    return {"clearance_err": _stats(errs), "clearance_rel_err": _stats(rel)}


def complexity_metrics(graph):
    st = graph.stats()
    return {
        "strokes": st["edges"],
        "branch_nodes": st["branch_nodes"],
        "leaf_nodes": st["leaf_nodes"],
        "points": st["points"],
        "total_length": st["total_length"],
        "components": _components(graph),
    }


def _components(graph):
    inc = graph.incident()
    seen, comps = set(), 0
    for start in graph.nodes:
        if start in seen:
            continue
        comps += 1
        stack = [start]
        seen.add(start)
        while stack:
            n = stack.pop()
            for eid in inc[n]:
                e = graph.edges[eid]
                for m in (e.frm, e.to):
                    if m not in seen:
                        seen.add(m)
                        stack.append(m)
    return comps
