"""Reconstruction metrics — report §11.

Vector-space scoring is the primary measure; the raster pixel-diff from
src/compare.js is kept as a cross-check for continuity with the incumbent's
numbers. Where the two disagree, that disagreement is itself a finding (see
NOTES.md), so both are always reported side by side rather than one being derived
from the other.
"""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from shapely.geometry import MultiLineString, MultiPolygon, Polygon

from . import geom, restroke, svgio

REPO = Path(__file__).resolve().parents[3]

# Boundary sampling step, in units of the drawing's dominant stroke radius. 0.25
# gives a few thousand samples on a typical drawing: dense enough that the median
# is stable, cheap enough to run inside a pruning sweep.
BOUNDARY_STEP_FRAC = 0.25


@dataclass
class ReconMetrics:
    # fidelity
    iou: float = 0.0
    sym_diff_area: float = 0.0
    sym_diff_ratio: float = 0.0        # symmetric difference / original area
    missing_ratio: float = 0.0         # original \ reconstructed, over original area
    extra_ratio: float = 0.0           # reconstructed \ original, over original area
    boundary_median: float = 0.0
    boundary_p95: float = 0.0
    boundary_median_norm: float = 0.0  # in units of the dominant stroke radius
    boundary_p95_norm: float = 0.0
    # width
    width_error_median: float = 0.0    # |assigned r - true distance to boundary|
    width_error_norm: float = 0.0
    width_cv: float = 0.0              # length-weighted std(R)/mean(R)
    # complexity
    strokes: int = 0
    edges: int = 0
    nodes: int = 0
    terminals: int = 0
    junctions: int = 0
    control_points: int = 0
    bezier_segments: int = 0
    total_length: float = 0.0
    global_radius: float = 0.0
    # provenance
    source_area: float = 0.0
    recon_area: float = 0.0
    width_mode: str = "median"
    seconds: float = 0.0
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, float):
                d[k] = round(v, 6)
        return d


def _boundary_points(geom_obj, step: float) -> np.ndarray:
    """Dense samples along a geometry's boundary."""
    if geom_obj is None or geom_obj.is_empty:
        return np.empty((0, 2))
    boundary = geom_obj.boundary
    if boundary.is_empty:
        return np.empty((0, 2))
    dense = shapely.segmentize(boundary, max_segment_length=max(step, 1e-6))
    lines = dense.geoms if isinstance(dense, MultiLineString) else [dense]
    chunks = [np.asarray(ln.coords) for ln in lines if len(ln.coords) > 0]
    if not chunks:
        return np.empty((0, 2))
    return np.vstack(chunks)


def boundary_distances(a, b, step: float) -> tuple[float, float]:
    """Symmetric nearest-distance error between two region boundaries.

    Median and P95 over the union of both directions. Never max: report §11 is
    explicit that one pathological point dominates a maximum.
    """
    pa = _boundary_points(a, step)
    pb = _boundary_points(b, step)
    if len(pa) == 0 or len(pb) == 0:
        return (float("inf"), float("inf"))
    da = shapely.distance(shapely.points(pa), b.boundary)
    db = shapely.distance(shapely.points(pb), a.boundary)
    allv = np.concatenate([da, db])
    return (float(np.median(allv)), float(np.percentile(allv, 95)))


def width_error(graph, source_poly, *, sample_step: float) -> tuple[float, float]:
    """How well the assigned radius matches the source's true local half-width.

    For every centerline vertex inside the source region, the true half-width is
    the distance from that point to the source boundary. Compared against the
    radius the backend assigned there. Returns (median abs error, length-weighted CV).
    """
    pts: list[tuple[float, float]] = []
    assigned: list[float] = []
    for e in graph.edges.values():
        radii = e.radii()
        if not radii:
            continue
        acc = 0.0
        cum = geom.cumulative_lengths(e.points)
        for i, p in enumerate(e.points):
            if i > 0 and cum[i] - acc < sample_step:
                continue
            acc = cum[i]
            pts.append(p)
            assigned.append(radii[min(i, len(radii) - 1)])
    if not pts:
        return (0.0, 0.0)
    arr = np.asarray(pts)
    sp = shapely.points(arr)
    inside = shapely.contains(source_poly, sp)
    dist = shapely.distance(sp, source_poly.boundary)
    a = np.asarray(assigned)
    if inside.any():
        err = np.abs(a[inside] - dist[inside])
        med = float(np.median(err))
    else:
        med = float("inf")

    # length-weighted coefficient of variation of radius across the graph
    tot = sum(e.length for e in graph.edges.values()) or 1.0
    mean_r = sum((e.median_radius or 0.0) * e.length for e in graph.edges.values()) / tot
    if mean_r <= 0:
        return (med, 0.0)
    var = sum(
        ((e.median_radius or 0.0) - mean_r) ** 2 * e.length for e in graph.edges.values()
    ) / tot
    return (med, float(math.sqrt(var) / mean_r))


def score_graph(
    graph,
    source,
    *,
    width_mode: str = "median",
    recon=None,
) -> ReconMetrics:
    """Full vector-space reconstruction score for one graph against one drawing."""
    import time

    t0 = time.time()
    src_poly = source.polygon if hasattr(source, "polygon") else source
    if recon is None:
        recon = restroke.graph_to_fill(graph, width_mode=width_mode)

    m = ReconMetrics(width_mode=width_mode)
    stats = graph.stats()
    m.strokes = stats["strokes"]
    m.edges = stats["edges"]
    m.nodes = stats["nodes"]
    m.terminals = stats["terminals"]
    m.junctions = stats["junctions"]
    m.control_points = stats["controlPoints"]
    m.bezier_segments = stats["bezierSegments"]
    m.total_length = stats["totalLength"]
    m.global_radius = stats["globalRadius"]

    src_area = restroke.area_of(src_poly)
    rec_area = restroke.area_of(recon)
    m.source_area = src_area
    m.recon_area = rec_area
    if src_area <= 0:
        return m
    if rec_area <= 0:
        m.sym_diff_ratio = 1.0
        m.missing_ratio = 1.0
        m.boundary_median = m.boundary_p95 = float("inf")
        m.seconds = time.time() - t0
        return m

    inter = src_poly.intersection(recon)
    union = src_poly.union(recon)
    m.iou = restroke.area_of(inter) / max(restroke.area_of(union), 1e-12)
    missing = restroke.area_of(src_poly.difference(recon))
    extra = restroke.area_of(recon.difference(src_poly))
    m.sym_diff_area = missing + extra
    m.sym_diff_ratio = m.sym_diff_area / src_area
    m.missing_ratio = missing / src_area
    m.extra_ratio = extra / src_area

    r_glob = m.global_radius or _source_scale(src_poly)
    step = max(r_glob * BOUNDARY_STEP_FRAC, 0.25)
    m.boundary_median, m.boundary_p95 = boundary_distances(src_poly, recon, step)
    if r_glob > 0:
        m.boundary_median_norm = m.boundary_median / r_glob
        m.boundary_p95_norm = m.boundary_p95 / r_glob

    m.width_error_median, m.width_cv = width_error(graph, src_poly, sample_step=step * 2)
    if r_glob > 0 and math.isfinite(m.width_error_median):
        m.width_error_norm = m.width_error_median / r_glob
    m.seconds = time.time() - t0
    return m


def _source_scale(poly) -> float:
    """Fallback dominant-radius estimate when the graph carries no radii at all."""
    if poly.is_empty:
        return 1.0
    return max(poly.area / max(poly.length, 1e-9), 1e-6) * 2.0


# ---------------------------------------------------------------- raster arm


def raster_diff(
    input_svg: str | Path,
    candidate_svg: str | Path,
    *,
    size: int = 1200,
    diff_png: str | Path | None = None,
    side_by_side: str | Path | None = None,
) -> float | None:
    """Percentage of differing pixels, via the project's own src/compare.js.

    Deliberately shells out to the incumbent's comparator rather than
    reimplementing it: the control numbers (0.02% dinosaur, 0.73% landscape) are
    only meaningful if measured by exactly the same code.
    """
    tmp = None
    if diff_png is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        diff_png = tmp.name
    cmd = [
        "node",
        str(REPO / "src" / "compare.js"),
        str(input_svg),
        str(candidate_svg),
        str(size),
        str(diff_png),
    ]
    if side_by_side:
        Path(side_by_side).parent.mkdir(parents=True, exist_ok=True)
        cmd.append(str(side_by_side))
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=300)
    except Exception:  # noqa: BLE001
        return None
    finally:
        if tmp is not None:
            tmp.close()
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        if "differing pixels" in line and "=" in line:
            try:
                return float(line.rsplit("=", 1)[1].strip().rstrip("%"))
            except ValueError:
                return None
    return None


def score_with_raster(
    graph,
    source,
    *,
    width_mode: str = "median",
    size: int = 1200,
    svg_out: str | Path | None = None,
    diff_png: str | Path | None = None,
) -> ReconMetrics:
    """Vector score plus the raster cross-check, both recorded."""
    m = score_graph(graph, source, width_mode=width_mode)
    path = svg_out
    tmp = None
    if path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".svg", delete=False)
        tmp.close()
        path = tmp.name
    svgio.write_graph_svg(graph, path, view_box=source.view_box)
    pct = raster_diff(source.path, path, size=size, diff_png=diff_png)
    if pct is not None:
        m.extras["rasterDiffPct"] = pct
        m.extras["rasterSize"] = size
    m.extras["svg"] = str(path) if svg_out else None
    return m


def load_metrics(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())
