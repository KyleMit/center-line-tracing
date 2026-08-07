"""Metrics for the polygon-Voronoi track (Common Setup Sec 11).

All geometry metrics are computed in VECTOR space with Shapely; the raster
pixel-diff from ``src/compare.js`` is kept separately for continuity with the
incumbent's numbers.

Boundary distance is reported as median and P95, never max -- one pathological
point dominates a max and hides real differences.
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry


def iou(a: BaseGeometry, b: BaseGeometry) -> float:
    if a.is_empty or b.is_empty:
        return 0.0
    try:
        inter = a.intersection(b).area
        union = a.union(b).area
    except Exception:
        a, b = a.buffer(0), b.buffer(0)
        inter, union = a.intersection(b).area, a.union(b).area
    return inter / union if union > 0 else 0.0


def symmetric_difference_area(a: BaseGeometry, b: BaseGeometry) -> float:
    if a.is_empty and b.is_empty:
        return 0.0
    try:
        return a.symmetric_difference(b).area
    except Exception:
        return a.buffer(0).symmetric_difference(b.buffer(0)).area


def _sample_boundary(geom: BaseGeometry, n: int) -> np.ndarray:
    if geom.is_empty:
        return np.zeros((0, 2))
    b = geom.boundary
    total = b.length
    if total <= 0:
        return np.zeros((0, 2))
    ts = np.linspace(0, total, n, endpoint=False)
    pts = [b.interpolate(t) for t in ts]
    return np.array([[p.x, p.y] for p in pts])


def boundary_distance(a: BaseGeometry, b: BaseGeometry, n: int = 800) -> dict:
    """Symmetric nearest-distance error between two region boundaries."""
    if a.is_empty or b.is_empty:
        return {"median": float("inf"), "p95": float("inf"), "mean": float("inf")}
    pa, pb = _sample_boundary(a, n), _sample_boundary(b, n)
    ba, bb = a.boundary, b.boundary
    da = np.array([bb.distance(Point(*p)) for p in pa]) if len(pa) else np.array([])
    db = np.array([ba.distance(Point(*p)) for p in pb]) if len(pb) else np.array([])
    d = np.concatenate([da, db]) if len(da) and len(db) else (da if len(da) else db)
    if not len(d):
        return {"median": float("inf"), "p95": float("inf"), "mean": float("inf")}
    return {
        "median": float(np.median(d)),
        "p95": float(np.percentile(d, 95)),
        "mean": float(np.mean(d)),
    }


def centerline_error(pred: MultiLineString, truth_lines: list[list[list[float]]],
                     n: int = 800) -> dict:
    """Directed + symmetric distance between a predicted centerline and ground truth.

    Synthetic corpus only.  ``pred_to_truth`` says "is what we drew on the real
    centerline"; ``truth_to_pred`` says "did we cover the whole centerline".
    Reported as median / P95, per Common Setup.
    """
    if pred.is_empty or not truth_lines:
        return {k: float("inf") for k in
                ("pred_to_truth_median", "pred_to_truth_p95",
                 "truth_to_pred_median", "truth_to_pred_p95", "hausdorff_p95")}
    truth = MultiLineString([LineString(t) for t in truth_lines if len(t) >= 2])

    def dists(src: MultiLineString, dst: BaseGeometry) -> np.ndarray:
        total = src.length
        if total <= 0:
            return np.array([])
        out = []
        for ls in src.geoms:
            k = max(2, int(round(n * ls.length / total)))
            for t in np.linspace(0, 1, k):
                p = ls.interpolate(t, normalized=True)
                out.append(dst.distance(p))
        return np.array(out)

    d1 = dists(pred, truth)
    d2 = dists(truth, pred)
    both = np.concatenate([d1, d2])
    return {
        "pred_to_truth_median": float(np.median(d1)),
        "pred_to_truth_p95": float(np.percentile(d1, 95)),
        "truth_to_pred_median": float(np.median(d2)),
        "truth_to_pred_p95": float(np.percentile(d2, 95)),
        "hausdorff_p95": float(np.percentile(both, 95)),
        "hausdorff_max": float(both.max()),
    }


def width_error(graph, truth_width: float | None) -> dict:
    radii = [r for e in graph.edges for r in e.radii if r == r]
    if not radii:
        return {"radius_cv": None, "width_bias": None, "median_width": None}
    radii = np.array(radii)
    med_w = float(2 * np.median(radii))
    cv = float(np.std(radii) / np.mean(radii)) if np.mean(radii) else None
    bias = None if truth_width in (None, 0) else float((med_w - truth_width) / truth_width)
    return {"radius_cv": cv, "width_bias": bias, "median_width": med_w}


def complexity(graph) -> dict:
    return {
        "edges": len(graph.edges),
        "nodes": len(graph.nodes),
        "terminals": graph.branch_count(),
        "junctions": graph.junction_count(),
        "vertices": int(sum(len(e.geometry) for e in graph.edges)),
        "total_length": float(graph.total_length),
    }
