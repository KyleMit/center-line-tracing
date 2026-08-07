"""Width recovery from the source mask's Euclidean distance transform.

This is the piece the earlier autotrace evaluation never had.  It previously
swept ONE global stroke width for a whole drawing; here every traced subpath
gets its own width, measured from the source geometry:

    EDT(mask)[p] == radius of the largest circle centred at p inscribed in the
                    filled region

so sampling the EDT along a traced centerline reads the local stroke radius
directly.  A robust statistic over those samples is the path's width.

The same signal doubles as the detector for the "mixed centerline/outline"
failure the handoff warns about: a traced *outline* hugs the boundary, where
EDT ~ 0, while a traced *centerline* sits near the ridge, where EDT ~ r.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage


def edt(mask: np.ndarray) -> np.ndarray:
    """Euclidean distance to the nearest background pixel, in pixels."""
    return ndimage.distance_transform_edt(mask)


def shape_radius(mask: np.ndarray) -> float:
    """Cheap scale-correct radius estimate for a stroke-like region.

    For a long stroke of width w and length L, area ~= wL and perimeter ~= 2L,
    so area/perimeter ~= w/2 = r.  Used as the reference scale for the
    outline-vs-centerline test, because it needs no skeleton and no traced path.
    """
    area = float(mask.sum())
    if area <= 0:
        return 0.0
    # 4-neighbour boundary pixel count is a stable perimeter proxy at our scales
    er = ndimage.binary_erosion(mask, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool))
    perim = float((mask & ~er).sum())
    if perim <= 0:
        return float(np.sqrt(area / np.pi))
    return area / perim


def sample_bilinear(field: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Bilinear sample of `field` at (x, y) pixel-centre coordinates."""
    h, w = field.shape
    x = np.clip(pts[:, 0] - 0.5, 0, w - 1.001)
    y = np.clip(pts[:, 1] - 0.5, 0, h - 1.001)
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    fx = x - x0
    fy = y - y0
    return (
        field[y0, x0] * (1 - fx) * (1 - fy)
        + field[y0, x1] * fx * (1 - fy)
        + field[y1, x0] * (1 - fx) * fy
        + field[y1, x1] * fx * fy
    )


def resample_uniform(pts: np.ndarray, step: float = 1.0) -> np.ndarray:
    """Arc-length resample so width statistics are not biased by vertex density."""
    if len(pts) < 2:
        return pts
    seg = np.hypot(*np.diff(pts, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total <= 0:
        return pts[:1]
    n = max(2, int(np.ceil(total / step)) + 1)
    t = np.linspace(0, total, n)
    return np.column_stack([np.interp(t, cum, pts[:, 0]), np.interp(t, cum, pts[:, 1])])


# ---- per-path statistics ------------------------------------------------------

STATS = ("median", "mean", "p60", "p70", "p75", "p80", "trimmed")


def robust(values: np.ndarray, how: str = "median") -> float:
    if len(values) == 0:
        return 0.0
    if how == "median":
        return float(np.median(values))
    if how == "mean":
        return float(np.mean(values))
    if how == "trimmed":  # drop the low and high deciles, then mean
        lo, hi = np.percentile(values, [10, 90])
        sel = values[(values >= lo) & (values <= hi)]
        return float(np.mean(sel)) if len(sel) else float(np.median(values))
    if how.startswith("p"):
        return float(np.percentile(values, float(how[1:])))
    raise ValueError(how)


def profile(dist: np.ndarray, pts_px: np.ndarray, endpoint_trim: float = 0.0):
    """Radius samples (px) along a path, optionally trimming near the two ends.

    Trimming exists because a traced centerline can overshoot slightly into a
    cap or a junction fillet, where EDT stops describing the stroke.
    """
    P = resample_uniform(pts_px, 1.0)
    if endpoint_trim > 0 and len(P) > 4:
        k = int(min(endpoint_trim, (len(P) - 2) // 2))
        if k > 0:
            P = P[k:-k]
    if len(P) == 0:
        return np.zeros(0), np.zeros((0, 2))
    return sample_bilinear(dist, P), P


def measure(subpaths, mask, dist=None, stat="median", endpoint_trim=0.0,
            outline_frac=0.40, min_outline_px=1.6):
    """Annotate each subpath with radius statistics and an outline/centerline verdict.

    Returns the shape radius reference used for the verdict.
    """
    if dist is None:
        dist = edt(mask)
    r_shape = shape_radius(mask)
    for sp in subpaths:
        pts = sp.points()
        vals, used = profile(dist, pts, endpoint_trim)
        if len(vals) == 0:
            sp.stats = {"radius_px": 0.0, "n": 0, "length_px": 0.0}
            sp.outline_like = False
            continue
        seg = np.hypot(*np.diff(pts, axis=0).T) if len(pts) > 1 else np.zeros(1)
        r = robust(vals, stat)
        med = float(np.median(vals))
        sp.stats = {
            "radius_px": r,
            "radius_median_px": med,
            "radius_p10_px": float(np.percentile(vals, 10)),
            "radius_p90_px": float(np.percentile(vals, 90)),
            "radius_min_px": float(vals.min()),
            "radius_max_px": float(vals.max()),
            "radius_cv": float(np.std(vals) / r) if r > 0 else 0.0,
            "n": int(len(vals)),
            "length_px": float(seg.sum()),
            "closed": bool(sp.is_closed()),
            "shape_radius_px": r_shape,
        }
        # Outline test: hugging the boundary means EDT stays near zero relative
        # to how thick the region actually is.
        sp.outline_like = bool(med < max(min_outline_px, outline_frac * r_shape))
    return r_shape


def per_vertex_profile(dist, sp, n=24):
    """Coarse radius profile along a path, for the graph model / variable width."""
    pts = resample_uniform(sp.points(), 1.0)
    if len(pts) < 2:
        return []
    idx = np.linspace(0, len(pts) - 1, min(n, len(pts))).astype(int)
    vals = sample_bilinear(dist, pts[idx])
    return [round(float(v), 4) for v in vals]
