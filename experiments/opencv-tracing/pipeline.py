"""The `opencv-tracing` centerline pipeline.

    SVG -> resvg mask (per filled element)
        -> cv2.ximgproc.thinning   (Zhang-Suen | Guo-Hall)
        -> skeleton-tracing        (C | Python | JS) or the incumbent's tracer
        -> radius recovered by sampling a distance transform  [DERIVED, not native]
        -> common graph model (report §13)
        -> re-stroked SVG

Radius is the load-bearing caveat of this whole track (report §4.4, §6.6):
morphological thinning returns a 1-pixel skeleton and nothing else, so unlike
Track 3's `medial_axis(return_distance=True)` there is no distance field falling
out of the skeletonizer. Everything radius-shaped here is sampled back out of a
separately computed `cv2.distanceTransform`, and the emitted graph JSON says so
explicitly in its `radius.native: false` field.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

import tracers
from svgraster import Raster

THINNERS = {
    "zhangsuen": cv2.ximgproc.THINNING_ZHANGSUEN,
    "guohall": cv2.ximgproc.THINNING_GUOHALL,
}


# ---------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------

def thin(mask: np.ndarray, method: str = "zhangsuen") -> np.ndarray:
    """1-pixel skeleton via OpenCV's ximgproc thinning."""
    src = (mask.astype(np.uint8)) * 255
    out = cv2.ximgproc.thinning(src, thinningType=THINNERS[method])
    return out > 0


def distance_field(mask: np.ndarray) -> np.ndarray:
    """Exact Euclidean distance to the outside, in pixels.

    This is the stage Track 3 gets for free from `medial_axis(return_distance=True)`
    and this track has to pay for separately.
    """
    return cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)


def sample_bilinear(field: np.ndarray, xs, ys) -> np.ndarray:
    """Bilinear sample of `field` at pixel-centre coordinates (x, y)."""
    h, w = field.shape
    xs = np.clip(np.asarray(xs, float), 0, w - 1.001)
    ys = np.clip(np.asarray(ys, float), 0, h - 1.001)
    x0 = np.floor(xs).astype(int)
    y0 = np.floor(ys).astype(int)
    fx = xs - x0
    fy = ys - y0
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    return (field[y0, x0] * (1 - fx) * (1 - fy) + field[y0, x1] * fx * (1 - fy)
            + field[y1, x0] * (1 - fx) * fy + field[y1, x1] * fx * fy)


def densify(points: np.ndarray, step: float = 1.0) -> np.ndarray:
    """Resample a polyline at ~`step` pixel spacing, for radius statistics."""
    if len(points) < 2:
        return points
    seg = np.linalg.norm(np.diff(points, axis=0), axis=1)
    total = float(seg.sum())
    if total <= 0:
        return points
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(2, int(np.ceil(total / step)) + 1)
    t = np.linspace(0.0, total, n)
    return np.column_stack([np.interp(t, cum, points[:, 0]),
                            np.interp(t, cum, points[:, 1])])


def simplify_rdp(points: np.ndarray, tolerance_px: float) -> np.ndarray:
    """Douglas-Peucker at a sub-pixel tolerance.

    skeleton-tracing emits a vertex pair at every chunk seam, so a run that is
    geometrically one straight segment comes back as dozens of collinear points
    (see NOTES.md). At tolerance < 1 pixel this cannot move the polyline further
    than the raster can resolve, but it removes that redundancy.
    """
    if tolerance_px <= 0 or len(points) < 3:
        return points
    from shapely.geometry import LineString
    line = LineString(points).simplify(tolerance_px, preserve_topology=False)
    out = np.asarray(line.coords, dtype=float)
    return out if len(out) >= 2 else points


def polyline_length(points: np.ndarray) -> float:
    if len(points) < 2:
        return 0.0
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


# ---------------------------------------------------------------------------
# graph assembly
# ---------------------------------------------------------------------------

@dataclass
class Edge:
    id: str
    from_id: str
    to_id: str
    points_px: np.ndarray            # (n, 2) pixel coords
    radii_px: np.ndarray             # (n,) per-vertex radius, pixels
    median_radius_px: float
    radius_std_px: float
    length_px: float
    source_element_id: str
    closed: bool = False


@dataclass
class ElementGraph:
    element_id: str
    fill: str
    nodes: dict                      # id -> {x, y, radius} in pixels
    edges: list
    raster: Raster
    skeleton: np.ndarray
    dist: np.ndarray
    timings: dict = field(default_factory=dict)


def _node_key(pt, snap: float = 1.5):
    return (int(round(pt[0] / snap)), int(round(pt[1] / snap)))


def build_graph(raster: Raster, polylines, dist: np.ndarray,
                skeleton: np.ndarray, element_index: int,
                timings: dict, simplify_px: float = 0.0) -> ElementGraph:
    """Turn traced polylines + a distance field into the common graph model."""
    nodes: dict = {}
    node_lookup: dict = {}
    edges: list = []

    def node_id_for(pt):
        key = _node_key(pt)
        if key in node_lookup:
            nid = node_lookup[key]
            return nid
        nid = f"e{element_index:03d}n{len(nodes):04d}"
        node_lookup[key] = nid
        nodes[nid] = {"x": float(pt[0]), "y": float(pt[1]),
                      "radius": float(sample_bilinear(dist, [pt[0]], [pt[1]])[0])}
        return nid

    for i, poly in enumerate(polylines):
        pts = np.asarray(poly, dtype=float)
        if len(pts) < 2:
            continue
        closed = bool(np.allclose(pts[0], pts[-1]))
        if simplify_px > 0:
            ends = (pts[0].copy(), pts[-1].copy())
            pts = simplify_rdp(pts, simplify_px)
            pts[0], pts[-1] = ends       # never move a junction/terminal node
        radii = sample_bilinear(dist, pts[:, 0], pts[:, 1])
        dense = densify(pts, 1.0)
        dense_r = sample_bilinear(dist, dense[:, 0], dense[:, 1])
        edges.append(Edge(
            id=f"e{element_index:03d}b{i:04d}",
            from_id=node_id_for(pts[0]),
            to_id=node_id_for(pts[-1]),
            points_px=pts,
            radii_px=radii,
            median_radius_px=float(np.median(dense_r)),
            radius_std_px=float(np.std(dense_r)),
            length_px=polyline_length(pts),
            source_element_id=raster.element.id,
            closed=closed,
        ))

    return ElementGraph(element_id=raster.element.id, fill=raster.element.fill,
                        nodes=nodes, edges=edges, raster=raster,
                        skeleton=skeleton, dist=dist, timings=timings)


# ---------------------------------------------------------------------------
# cap extension (report §2.3)
# ---------------------------------------------------------------------------

def cap_reach(graph: ElementGraph) -> list:
    """Per terminal end: how far short of the shape's tip the skeleton stopped.

    Returns `(edge_id, node_id, exit_distance_px, radius_px)`. For a round cap
    the ideal `exit_distance` is exactly R (the endpoint sits at the cap circle's
    centre); anything larger is thinning pull-back. This is the measurement
    behind both `extend_caps` and the `cap artifact` tag, kept in one place so
    the fix and the metric cannot drift apart.
    """
    degree: dict = {}
    for e in graph.edges:
        degree[e.from_id] = degree.get(e.from_id, 0) + 1
        degree[e.to_id] = degree.get(e.to_id, 0) + 1

    mask = graph.raster.mask
    h, w = mask.shape
    out = []

    for edge in graph.edges:
        if edge.closed or len(edge.points_px) < 2:
            continue
        for end in ("from", "to"):
            nid = edge.from_id if end == "from" else edge.to_id
            if degree.get(nid, 0) != 1:
                continue
            pts = edge.points_px
            if end == "from":
                tip, inner = pts[0], pts[min(len(pts) - 1, 3)]
            else:
                tip, inner = pts[-1], pts[max(0, len(pts) - 4)]
            direction = tip - inner
            norm = float(np.linalg.norm(direction))
            if norm < 1e-9:
                continue
            direction /= norm

            radius = max(edge.median_radius_px, 1.0)
            limit = 3.0 * radius
            exit_at = 0.0
            travelled = 0.25
            while travelled <= limit:
                probe = tip + direction * travelled
                px, py = int(round(probe[0])), int(round(probe[1]))
                if not (0 <= px < w and 0 <= py < h) or not mask[py, px]:
                    break
                exit_at = travelled
                travelled += 0.25
            out.append((edge.id, nid, end, float(exit_at), float(radius),
                        tip.copy(), direction.copy()))
    return out


def extend_caps(graph: ElementGraph, mode: str = "round",
                max_extend_factor: float = 1.5) -> int:
    """Push terminal ends outward along their tangent to where the cap belongs.

    Thinning stops short of a cap, so a re-stroked centerline is systematically
    short at both ends (report §2.3, §6.6). Two modes, because the right target
    depends on the cap style the fill was produced with:

        "round"     stop one radius inside the shape's tip — the cap circle's
                    centre, which is where a round-capped stroke's path ends.
        "boundary"  stop at the shape's tip itself, correct for butt/square caps.

    Marching to the boundary and stopping there overshoots a round cap by exactly
    one radius and makes IoU *worse*, which is why "round" is the default and why
    both are measured rather than assumed — see NOTES.md.

    Returns how many ends moved.
    """
    if mode == "none":
        return 0

    moved = 0
    by_edge = {e.id: e for e in graph.edges}

    for edge_id, nid, end, exit_at, radius, tip, direction in cap_reach(graph):
        edge = by_edge[edge_id]
        target = exit_at - radius if mode == "round" else exit_at
        best = min(target, max_extend_factor * radius)
        if best <= 0.25:
            continue

        new_tip = tip + direction * best
        new_r = float(sample_bilinear(graph.dist, [new_tip[0]], [new_tip[1]])[0])
        if end == "from":
            edge.points_px = np.vstack([new_tip, edge.points_px])
            edge.radii_px = np.concatenate([[new_r], edge.radii_px])
        else:
            edge.points_px = np.vstack([edge.points_px, new_tip])
            edge.radii_px = np.concatenate([edge.radii_px, [new_r]])
        edge.length_px = polyline_length(edge.points_px)
        graph.nodes[nid]["x"] = float(new_tip[0])
        graph.nodes[nid]["y"] = float(new_tip[1])
        graph.nodes[nid]["radius"] = new_r
        moved += 1

    return moved


# ---------------------------------------------------------------------------
# per-element driver
# ---------------------------------------------------------------------------

def process_element(raster: Raster, element_index: int, thinning: str = "zhangsuen",
                    tracer: str = "st-c", cap_extend: str = "round",
                    csize: int = tracers.CSIZE_DEFAULT,
                    simplify_px: float = 0.0) -> ElementGraph:
    timings = {}

    t0 = time.perf_counter()
    skeleton = thin(raster.mask, thinning)
    timings["thin_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    fn = tracers.TRACERS[tracer]
    polylines = fn(skeleton) if tracer == "bespoke" else fn(skeleton, csize=csize)
    timings["trace_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    dist = distance_field(raster.mask)
    timings["distance_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    graph = build_graph(raster, polylines, dist, skeleton, element_index, timings,
                        simplify_px=simplify_px)
    timings["graph_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    timings["caps_extended"] = extend_caps(graph, mode=cap_extend)
    timings["cap_extend_s"] = time.perf_counter() - t0

    return graph


# ---------------------------------------------------------------------------
# serialization
# ---------------------------------------------------------------------------

def graph_to_json(graphs: list, image: str, raster_meta: dict, config: dict) -> dict:
    """Serialize to the Common Setup graph model (report §13)."""
    nodes = []
    edges = []
    for g in graphs:
        r = g.raster
        for nid, n in g.nodes.items():
            x, y = r.to_svg(n["x"], n["y"])
            nodes.append({"id": nid, "x": round(float(x), 4), "y": round(float(y), 4),
                          "radius": round(float(r.to_svg_len(n["radius"])), 4)})
        for e in g.edges:
            xs, ys = r.to_svg(e.points_px[:, 0], e.points_px[:, 1])
            edges.append({
                "id": e.id, "from": e.from_id, "to": e.to_id,
                "geometry": [[round(float(a), 4), round(float(b), 4)]
                             for a, b in zip(xs, ys)],
                "geometryType": "polyline",
                "length": round(float(r.to_svg_len(e.length_px)), 4),
                "medianRadius": round(float(r.to_svg_len(e.median_radius_px)), 4),
                "radiusStd": round(float(r.to_svg_len(e.radius_std_px)), 4),
                "radii": [round(float(v), 4) for v in r.to_svg_len(e.radii_px)],
                "closed": e.closed,
                "sourceElementId": e.source_element_id,
                "sourceElementFill": g.fill,
            })

    return {
        "schemaVersion": "centerline-graph/1",
        "slug": "opencv-tracing",
        "image": image,
        "units": "svg user units",
        "backend": {
            "skeletonizer": f"cv2.ximgproc.thinning({config['thinning']})",
            "opencv": cv2.__version__,
            "tracer": config["tracer"],
            "tracerSource": "LingDong-/skeleton-tracing @ f5dd65e (MIT), vendored"
                            if config["tracer"].startswith("st-")
                            else "port of src/convert_filled_svg_to_stroked_lines.py",
            "capExtension": config["cap_extend"],
        },
        "radius": {
            "native": False,
            "derivedFrom": "cv2.distanceTransform(DIST_L2, DIST_MASK_PRECISE) on the "
                           "source mask, sampled bilinearly along the traced polylines",
            "note": "Morphological thinning carries no distance field (report §4.4, "
                    "§6.6). Unlike Track 3's medial_axis(return_distance=True), every "
                    "radius here is DERIVED, not native to the skeletonizer.",
        },
        "raster": raster_meta,
        "nodes": nodes,
        "edges": edges,
    }


def graph_to_svg(graphs: list, viewbox, hairline: bool = False) -> str:
    """Re-stroke the graph into the output shape Common Setup asks for.

    `hairline` instead draws the bare centerlines at a fixed thin width, which is
    what the contact sheets' overlay column needs — a full-width re-stroke over
    the source fill just hides the thing being inspected.
    """
    vx, vy, vw, vh = viewbox
    parts = [f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
             f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
             f'viewBox="{vx} {vy} {vw} {vh}">']
    for g in graphs:
        r = g.raster
        for e in g.edges:
            if len(e.points_px) < 2:
                continue
            xs, ys = r.to_svg(e.points_px[:, 0], e.points_px[:, 1])
            d = "M " + " L ".join(f"{x:.3f} {y:.3f}" for x, y in zip(xs, ys))
            if e.closed:
                d += " Z"
            if hairline:
                width = max(vw, vh) / 400.0
                colour = "#e01414"
            else:
                width = 2.0 * float(r.to_svg_len(e.median_radius_px))
                colour = g.fill
            parts.append(f'<path d="{d}" fill="none" stroke="{colour}" '
                         f'stroke-width="{width:.3f}" stroke-linecap="round" '
                         f'stroke-linejoin="round"/>')
    parts.append("</svg>")
    return "\n".join(parts)
