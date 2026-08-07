"""One interface over the two polygon-Voronoi centerline libraries.

Both take a Shapely polygon and return line geometry, so an apples-to-apples
comparison is possible: identical input polygons, identical flattening
tolerance, identical downstream graph/metric code.  Only each library's own
knobs differ.

  pygeoops.centerline  -- densify_distance, min_branch_length, simplifytolerance
                          (negative values are *width-relative*, which is the
                          feature this track exists to evaluate)
  centerline.geometry.Centerline (fitodic) -- interpolation_distance only
"""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)


@dataclass
class BackendResult:
    backend: str
    lines: MultiLineString
    seconds: float
    params: dict = field(default_factory=dict)
    error: str | None = None
    n_input_points: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None and not self.lines.is_empty


def _clean_lines(geom: BaseGeometry | None, min_len: float = 1e-9) -> MultiLineString:
    """Drop degenerate/zero-length pieces and merge collinear runs.

    pygeoops in particular emits several exactly-degenerate 2-point strings at
    branch tips (verified on a capsule), which would otherwise show up as
    spurious graph nodes.
    """
    if geom is None or geom.is_empty:
        return MultiLineString([])
    parts: list[LineString] = []
    stack = [geom]
    while stack:
        g = stack.pop()
        if g.is_empty:
            continue
        if g.geom_type == "LineString":
            if g.length > min_len:
                parts.append(g)
        elif hasattr(g, "geoms"):
            stack.extend(list(g.geoms))
    if not parts:
        return MultiLineString([])
    merged = linemerge(parts)
    if merged.geom_type == "LineString":
        merged = MultiLineString([merged])
    return MultiLineString([g for g in merged.geoms if g.length > min_len])


def _as_polygons(geom: BaseGeometry) -> list[Polygon]:
    if geom.geom_type == "Polygon":
        return [geom]
    return [g for g in geom.geoms if g.geom_type == "Polygon" and not g.is_empty]


# --------------------------------------------------------------------------
# backends
# --------------------------------------------------------------------------


def run_pygeoops(
    geom: BaseGeometry,
    densify_distance: float = -1.0,
    min_branch_length: float = -1.0,
    simplifytolerance: float = -0.25,
    extend: bool = False,
) -> BackendResult:
    import pygeoops

    params = dict(
        densify_distance=densify_distance,
        min_branch_length=min_branch_length,
        simplifytolerance=simplifytolerance,
        extend=extend,
    )
    t0 = time.perf_counter()
    try:
        out = pygeoops.centerline(geom, **params)
        lines = _clean_lines(out)
        err = None
    except Exception as exc:  # noqa: BLE001 - we want the message in the table
        lines, err = MultiLineString([]), f"{type(exc).__name__}: {exc}"
    dt = time.perf_counter() - t0
    return BackendResult("pygeoops", lines, dt, params, err, _npoints(geom))


def run_fitodic(
    geom: BaseGeometry,
    interpolation_distance: float = 0.5,
) -> BackendResult:
    from centerline.geometry import Centerline

    params = dict(interpolation_distance=interpolation_distance)
    t0 = time.perf_counter()
    pieces: list[LineString] = []
    err = None
    try:
        for poly in _as_polygons(geom):
            c = Centerline(poly, interpolation_distance=interpolation_distance)
            g = c.geometry
            if g.geom_type == "LineString":
                pieces.append(g)
            else:
                pieces.extend(list(g.geoms))
        lines = _clean_lines(MultiLineString(pieces) if pieces else None)
    except Exception as exc:  # noqa: BLE001
        lines, err = MultiLineString([]), f"{type(exc).__name__}: {exc}"
    dt = time.perf_counter() - t0
    return BackendResult("fitodic", lines, dt, params, err, _npoints(geom))


def run_fitodic_filtered(
    geom: BaseGeometry,
    interpolation_distance: float = 2.0,
    min_branch_length: float = -1.0,
    simplifytolerance: float = 0.0,
) -> BackendResult:
    """fitodic's Voronoi + pygeoops' branch filter.

    The two libraries differ in two ways at once -- how they build the Voronoi
    graph, and whether they prune it.  fitodic has no pruning at all, so a
    straight head-to-head measures mostly the pruning.  This variant borrows
    pygeoops' own ``_remove_short_branches_notempty`` so the remaining
    difference is the Voronoi construction itself, which is what Track 8 needs
    to know.
    """
    from pygeoops._centerline import _remove_short_branches_notempty

    base = run_fitodic(geom, interpolation_distance=interpolation_distance)
    if base.error or base.lines.is_empty:
        base.backend = "fitodic+filter"
        return base
    t0 = time.perf_counter()
    mbl = min_branch_length
    if mbl < 0:
        mbl = abs(mbl) * average_width(geom)
    lines = _remove_short_branches_notempty(base.lines, mbl)
    if simplifytolerance:
        tol = (abs(simplifytolerance) * average_width(geom)
               if simplifytolerance < 0 else simplifytolerance)
        import shapely

        lines = shapely.simplify(lines, tol)
    out = _clean_lines(lines)
    params = dict(interpolation_distance=interpolation_distance,
                  min_branch_length=min_branch_length,
                  simplifytolerance=simplifytolerance)
    return BackendResult("fitodic+filter", out, base.seconds + (time.perf_counter() - t0),
                         params, None, base.n_input_points)


def _npoints(geom: BaseGeometry) -> int:
    n = 0
    for p in _as_polygons(geom):
        n += len(p.exterior.coords) + sum(len(r.coords) for r in p.interiors)
    return n


BACKENDS = {"pygeoops": run_pygeoops, "fitodic": run_fitodic,
            "fitodic+filter": run_fitodic_filtered}


def run(backend: str, geom: BaseGeometry, **kwargs) -> BackendResult:
    if backend not in BACKENDS:
        raise KeyError(f"unknown backend {backend!r}; have {sorted(BACKENDS)}")
    return BACKENDS[backend](geom, **kwargs)


def average_width(geom: BaseGeometry) -> float:
    """pygeoops' own width proxy, reproduced so our reported width-relative
    numbers match the ones its negative parameters actually resolve to.

    Solves ``w*l = area`` and ``2*(w+l) = perimeter`` for the smaller root, i.e.
    the width of the rectangle with the same area and perimeter.
    """
    import math

    p4 = geom.length / 4.0
    return p4 - math.sqrt(max(p4 * p4 - geom.area, 0.0))
