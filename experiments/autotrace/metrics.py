"""Reconstruction scoring (Common Setup / report §11).

Everything is measured on a common raster of the ORIGINAL and the RECONSTRUCTED
SVG at one controlled scale, using resvg for both so the comparison is not
measuring two different renderers.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage


def masks(renderer, box, scale, svg_a: str, svg_b: str):
    a, fa = renderer.mask(svg_a, box, scale)
    b, fb = renderer.mask(svg_b, box, scale)
    h = min(a.shape[0], b.shape[0])
    w = min(a.shape[1], b.shape[1])
    return a[:h, :w], b[:h, :w], fa


def score(a: np.ndarray, b: np.ndarray, scale: float):
    inter = np.count_nonzero(a & b)
    union = np.count_nonzero(a | b)
    xor = np.count_nonzero(a ^ b)
    total = a.size
    out = {
        "iou": inter / union if union else 1.0,
        "sym_diff_px": int(xor),
        "sym_diff_pct_of_canvas": 100.0 * xor / total,
        "sym_diff_pct_of_orig": 100.0 * xor / max(1, np.count_nonzero(a)),
        "orig_px": int(np.count_nonzero(a)),
        "recon_px": int(np.count_nonzero(b)),
        "coverage": np.count_nonzero(a & b) / max(1, np.count_nonzero(a)),
        "spill": np.count_nonzero(b & ~a) / max(1, np.count_nonzero(a)),
    }
    out.update(boundary_distance(a, b, scale))
    return out


def boundary_distance(a: np.ndarray, b: np.ndarray, scale: float):
    """Symmetric nearest-boundary distance, reported as median and P95 (never max)."""

    def bnd(m):
        er = ndimage.binary_erosion(m, np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool))
        return m & ~er

    ba, bb = bnd(a), bnd(b)
    if not ba.any() or not bb.any():
        return {"boundary_median_px": float("nan"), "boundary_p95_px": float("nan"),
                "boundary_median_user": float("nan"), "boundary_p95_user": float("nan")}
    da = ndimage.distance_transform_edt(~ba)
    db = ndimage.distance_transform_edt(~bb)
    d = np.concatenate([db[ba], da[bb]])
    med, p95 = float(np.median(d)), float(np.percentile(d, 95))
    return {
        "boundary_median_px": med, "boundary_p95_px": p95,
        "boundary_median_user": med / scale, "boundary_p95_user": p95 / scale,
    }


def complexity(result):
    """Centerline complexity: prefer the simpler graph at equal geometry error."""
    g = result.get("graph", {"edges": []})
    edges = g.get("edges", [])
    return {
        "n_strokes": len(edges),
        "n_closed": sum(1 for e in edges if e.get("closed")),
        "n_outline_like": sum(1 for e in edges if e.get("outlineLike")),
        "total_length": round(sum(e.get("length", 0) for e in edges), 2),
    }


def width_error(result):
    """Within-path radius variation -- how constant the recovered width is."""
    cvs = []
    for g in result.get("groups", []):
        r = g.get("radius_px")
        if not r or not r.get("median"):
            continue
        if r["median"] > 0:
            cvs.append((r["max"] - r["min"]) / r["median"])
    if not cvs:
        return {"width_spread_median": None}
    return {"width_spread_median": round(float(np.median(cvs)), 4)}
