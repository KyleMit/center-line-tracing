"""Scoring for the `opencv-tracing` track (Common Setup "Metrics", report §11).

Two families:

* **Reconstruction** — re-stroke the recovered centerlines and compare the result
  with the source fill: IoU, symmetric-difference area, boundary distance
  (median and P95, never max), complexity, width error. Done in the element's own
  raster crop, on the same pixel grid the skeleton came from, so no resampling
  error is introduced between extraction and scoring.

* **Centerline error** — only available on the synthetic corpus, where the source
  path is known. Reported in both directions, because they measure different
  failures:
      recovered -> GT   "is what I found actually on the true centerline"
      GT -> recovered   "did I cover the whole true centerline"
  Thinning's cap pull-back (report §2.3, §6.6) shows up almost entirely in the
  second direction, so collapsing them into one symmetric number would hide the
  single most characteristic defect of this backend.

Failure tags follow Common Setup's taxonomy; `classify` documents the exact
numeric rule for each so Track 3's counts are directly comparable.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

import pipeline


# ---------------------------------------------------------------------------
# re-stroke into a raster mask
# ---------------------------------------------------------------------------

def restroke_mask(graph, constant_width: bool = True) -> np.ndarray:
    """Rasterize `stroke_to_fill(centerline, width)` on the element's own grid.

    Round caps and joins are reproduced by stamping a disc at every densified
    sample, which is exactly what an SVG round-capped stroke is. Each edge is
    stamped inside its own bounding box rather than the full element crop —
    without that, scoring a 38-element drawing costs one full-mask distance
    transform per edge and dominates the whole benchmark.
    """
    h, w = graph.raster.mask.shape
    out = np.zeros((h, w), dtype=bool)

    stamps = []
    for edge in graph.edges:
        if len(edge.points_px) < 2:
            continue
        dense = pipeline.densify(edge.points_px, 0.7)
        if constant_width:
            radii = np.full(len(dense), edge.median_radius_px)
        else:
            # Interpolate the radius profile along ARC LENGTH, not vertex index.
            # After Douglas-Peucker the vertices are wildly unevenly spaced — on
            # the variable-width case, index 0.25 sits at x=236 while arc-length
            # 0.25 sits at x=200 — so index interpolation reports the wrong width
            # over most of the stroke.
            seg = np.linalg.norm(np.diff(edge.points_px, axis=0), axis=1)
            src = np.concatenate([[0.0], np.cumsum(seg)])
            dst = np.linspace(0.0, src[-1], len(dense))
            radii = np.interp(dst, src, edge.radii_px)
        stamps.append((dense, radii))

    if not stamps:
        return out

    # Threshold a distance transform seeded at the samples: exact on the pixel
    # grid, with no rasterization approximation of its own. Restricted to each
    # edge's own bounding box — the unrestricted version costs a full-mask
    # transform per edge and dominated the whole benchmark on the 38-element
    # dinosaur.
    #
    # Stamping with cv2.circle(shift=3) instead is much faster but disagrees
    # with this by up to 0.002 IoU (see NOTES.md); since the bounded transform
    # is fast enough, correctness wins.
    for dense, radii in stamps:
        pad = int(np.ceil(radii.max())) + 2
        x0 = max(0, int(np.floor(dense[:, 0].min())) - pad)
        x1 = min(w, int(np.ceil(dense[:, 0].max())) + pad + 1)
        y0 = max(0, int(np.floor(dense[:, 1].min())) - pad)
        y1 = min(h, int(np.ceil(dense[:, 1].max())) + pad + 1)
        if x1 <= x0 or y1 <= y0:
            continue

        lw, lh = x1 - x0, y1 - y0
        px = np.clip(np.round(dense[:, 0]).astype(int) - x0, 0, lw - 1)
        py = np.clip(np.round(dense[:, 1]).astype(int) - y0, 0, lh - 1)
        window = out[y0:y1, x0:x1]

        if np.allclose(radii, radii[0]):
            seeds = np.ones((lh, lw), dtype=np.uint8)
            seeds[py, px] = 0
            window |= ndimage.distance_transform_edt(seeds) <= radii[0]
        else:
            # Variable radius: bucket samples by radius and union the buckets.
            order = np.argsort(radii)
            buckets = np.array_split(order, min(12, max(1, len(order) // 8)))
            for bucket in buckets:
                if len(bucket) == 0:
                    continue
                seeds = np.ones((lh, lw), dtype=np.uint8)
                seeds[py[bucket], px[bucket]] = 0
                window |= (ndimage.distance_transform_edt(seeds)
                           <= float(np.max(radii[bucket])))
    return out


# ---------------------------------------------------------------------------
# reconstruction metrics
# ---------------------------------------------------------------------------

def reconstruction(graph, constant_width: bool = True) -> dict:
    original = graph.raster.mask
    recon = restroke_mask(graph, constant_width)
    scale = graph.raster.scale

    inter = int(np.count_nonzero(original & recon))
    union = int(np.count_nonzero(original | recon))
    sym = int(np.count_nonzero(original ^ recon))
    px_area = 1.0 / (scale * scale)

    result = {
        "iou": (inter / union) if union else 1.0,
        "symDiffArea": sym * px_area,
        "symDiffFraction": (sym / int(np.count_nonzero(original))) if original.any() else 0.0,
        "originalArea": int(np.count_nonzero(original)) * px_area,
        "reconArea": int(np.count_nonzero(recon)) * px_area,
    }
    result.update(boundary_distance(original, recon, scale))
    return result


def boundary_distance(a: np.ndarray, b: np.ndarray, scale: float) -> dict:
    """Symmetric nearest-boundary distance, in SVG user units."""
    def edges(mask):
        return mask & ~ndimage.binary_erosion(mask, np.ones((3, 3), bool))

    ea, eb = edges(a), edges(b)
    if not ea.any() or not eb.any():
        return {"boundaryMedian": float("nan"), "boundaryP95": float("nan")}

    da = ndimage.distance_transform_edt(~ea)
    db = ndimage.distance_transform_edt(~eb)
    both = np.concatenate([db[ea], da[eb]]) / scale
    return {"boundaryMedian": float(np.median(both)),
            "boundaryP95": float(np.percentile(both, 95))}


def complexity(graphs: list) -> dict:
    edges = [e for g in graphs for e in g.edges]
    nodes = {nid for g in graphs for nid in g.nodes}
    degree: dict = {}
    for g in graphs:
        for e in g.edges:
            degree[e.from_id] = degree.get(e.from_id, 0) + 1
            degree[e.to_id] = degree.get(e.to_id, 0) + 1

    lengths = [float(e.length_px / e_scale) for g in graphs
               for e, e_scale in [(e, g.raster.scale) for e in g.edges]]
    radii = [float(e.median_radius_px / g.raster.scale) for g in graphs for e in g.edges]
    cvs = [float(e.radius_std_px / e.median_radius_px)
           for g in graphs for e in g.edges if e.median_radius_px > 1e-6]

    return {
        "edgeCount": len(edges),
        "nodeCount": len(nodes),
        "vertexCount": int(sum(len(e.points_px) for e in edges)),
        "terminalNodes": sum(1 for d in degree.values() if d == 1),
        "junctionNodes": sum(1 for d in degree.values() if d >= 3),
        "degree4PlusNodes": sum(1 for d in degree.values() if d >= 4),
        "totalLength": float(sum(lengths)),
        "medianRadius": float(np.median(radii)) if radii else 0.0,
        "widthErrorCv": float(np.mean(cvs)) if cvs else 0.0,
    }


# ---------------------------------------------------------------------------
# centerline error vs known ground truth (synthetic corpus only)
# ---------------------------------------------------------------------------

def _to_svg_points(graphs):
    out = []
    for g in graphs:
        r = g.raster
        for e in g.edges:
            dense = pipeline.densify(e.points_px, 0.5)
            xs, ys = r.to_svg(dense[:, 0], dense[:, 1])
            out.append(np.column_stack([xs, ys]))
    return out


def _directed(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Nearest-point distance from every point of `src` to the point set `dst`."""
    from scipy.spatial import cKDTree
    return cKDTree(dst).query(src)[0]


def centerline_error(graphs, ground_truth: list) -> dict:
    """Both directed distances between recovered centerlines and the source paths."""
    recovered = _to_svg_points(graphs)
    if not recovered:
        return {"centerlineToGtMedian": float("nan"), "centerlineToGtP95": float("nan"),
                "gtToCenterlineMedian": float("nan"), "gtToCenterlineP95": float("nan"),
                "gtCoverageFraction": 0.0}

    rec = np.vstack(recovered)
    gts = []
    for entry in ground_truth:
        pts = np.asarray(entry["points"], dtype=float)
        gts.append(pipeline.densify(pts, 0.25))
    gt = np.vstack(gts)

    r2g = _directed(rec, gt)
    g2r = _directed(gt, rec)
    tol = 1.0   # user units; ~1 raster pixel at scale 4 is 0.25

    return {
        "centerlineToGtMedian": float(np.median(r2g)),
        "centerlineToGtP95": float(np.percentile(r2g, 95)),
        "gtToCenterlineMedian": float(np.median(g2r)),
        "gtToCenterlineP95": float(np.percentile(g2r, 95)),
        "gtCoverageFraction": float(np.mean(g2r <= tol)),
    }


# ---------------------------------------------------------------------------
# failure tagging (Common Setup "Tag every failure", report §13 Experiment 2)
# ---------------------------------------------------------------------------

CLASSIFIER_RULES = {
    "outline noise branch":
        "terminal edge with L/(2*R_med) < 0.75 whose far end is NOT within 1.5*R_med "
        "of a junction node (i.e. a spur off a plain stroke wall, not off a junction)",
    "join artifact":
        "terminal edge with L/(2*R_med) < 1.5 whose far end IS within 2.5*R_med of a "
        "junction node — the classic thinning spur thrown off a Y/T/X centre",
    "cap artifact":
        "degree-1 endpoint that stops more than 1.25*R_med short of the shape's "
        "tip, measured by marching outward along the terminal tangent. A correctly "
        "terminated round cap exits at exactly R_med (the cap circle's centre), so "
        "this counts thinning pull-back and nothing else. NOTE: the distance-"
        "transform value at the tip does NOT work as a test — it equals R all "
        "along the stroke axis and so cannot discriminate.",
    "crossing ambiguity":
        "node of degree >= 4",
    "disconnected skeleton":
        "connected components of the traced graph in excess of the mask's own "
        "connected-component count",
    "missing narrow segment":
        "mask connected component of area > 4*R_global^2 that contains no skeleton pixel",
    "excessive curve complexity":
        "edge carrying more than 6 vertices per stroke width, i.e. "
        "vertexCount / (L / (2*R_med)) > 6",
    "raster quantization":
        "edge longer than 4*R_med that, after a 0.5px Douglas-Peucker pass, still "
        "needs a direction change more often than every 7 pixels (vertices/L_px > "
        "0.15) — the staircase signature of a thinned skeleton",
}


def classify(graphs) -> dict:
    counts = {key: 0 for key in CLASSIFIER_RULES}

    for g in graphs:
        scale = g.raster.scale
        degree: dict = {}
        for e in g.edges:
            degree[e.from_id] = degree.get(e.from_id, 0) + 1
            degree[e.to_id] = degree.get(e.to_id, 0) + 1
        junctions = np.array([[g.nodes[n]["x"], g.nodes[n]["y"]]
                              for n, d in degree.items() if d >= 3], dtype=float)

        counts["crossing ambiguity"] += sum(1 for d in degree.values() if d >= 4)

        radii = [e.median_radius_px for e in g.edges if e.median_radius_px > 0]
        r_global = float(np.median(radii)) if radii else 1.0

        for e in g.edges:
            r = max(e.median_radius_px, 1e-6)
            norm_len = e.length_px / (2.0 * r)
            ends = [(e.from_id, e.points_px[0]), (e.to_id, e.points_px[-1])]
            terminal = [(nid, pt) for nid, pt in ends if degree.get(nid, 0) == 1]

            if terminal and not e.closed:
                near_junction = False
                if len(junctions):
                    other = [pt for nid, pt in ends if degree.get(nid, 0) != 1]
                    probe = other[0] if other else e.points_px[len(e.points_px) // 2]
                    near_junction = bool(
                        np.min(np.linalg.norm(junctions - probe, axis=1)) <= 2.5 * r)
                if near_junction and norm_len < 1.5:
                    counts["join artifact"] += 1
                elif not near_junction and norm_len < 0.75:
                    counts["outline noise branch"] += 1

            if norm_len > 0 and len(e.points_px) / norm_len > 6.0:
                counts["excessive curve complexity"] += 1

            if e.length_px > 4.0 * r:
                straightened = pipeline.simplify_rdp(e.points_px, 0.5)
                if len(straightened) / e.length_px > 0.15:
                    counts["raster quantization"] += 1

        for _, _, _, exit_at, radius, _, _ in pipeline.cap_reach(g):
            if exit_at > 1.25 * radius:
                counts["cap artifact"] += 1

        # topology: skeleton components vs mask components
        mask_labels, mask_n = ndimage.label(g.raster.mask, np.ones((3, 3), int))
        skel_labels, skel_n = ndimage.label(g.skeleton, np.ones((3, 3), int))
        counts["disconnected skeleton"] += max(0, skel_n - mask_n)

        for label in range(1, mask_n + 1):
            component = mask_labels == label
            if component.sum() > 4 * r_global * r_global and not (g.skeleton & component).any():
                counts["missing narrow segment"] += 1

    return counts


def wrong_endpoints(graphs, ground_truth: list, tol_factor: float = 2.0) -> int:
    """GT path ends with no recovered degree-1 endpoint nearby (`wrong endpoint`)."""
    ends = []
    for g in graphs:
        r = g.raster
        degree: dict = {}
        for e in g.edges:
            degree[e.from_id] = degree.get(e.from_id, 0) + 1
            degree[e.to_id] = degree.get(e.to_id, 0) + 1
        for nid, d in degree.items():
            if d == 1:
                x, y = r.to_svg(g.nodes[nid]["x"], g.nodes[nid]["y"])
                ends.append([float(x), float(y)])
    if not ends:
        return sum(2 for _ in ground_truth)

    ends_arr = np.asarray(ends)
    missing = 0
    for entry in ground_truth:
        pts = np.asarray(entry["points"], dtype=float)
        if np.allclose(pts[0], pts[-1]):
            continue                                     # closed path: no ends
        width = entry.get("width") or 20.0
        tol = tol_factor * width / 2.0
        for tip in (pts[0], pts[-1]):
            if np.min(np.linalg.norm(ends_arr - tip, axis=1)) > tol:
                missing += 1
    return missing
