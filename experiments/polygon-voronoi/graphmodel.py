"""Common graph model (Common Setup Sec 13) for the polygon-Voronoi track.

    CenterlineNode { id, x, y, radius? }
    CenterlineEdge { id, from, to, geometry, length, medianRadius?, sourceElementId? }

IMPORTANT, and stated loudly because it differs from Tracks 1 and 3: radius here
is **derived, not native**.  A true MAT carries the inscribed-circle radius as
part of its output; a polygon-Voronoi centerline does not.  We recover it by
measuring distance-to-boundary from the source Shapely polygon at points sampled
along the centerline.  That is exact for an exact medial axis, but it inherits
whatever positional error the Voronoi approximation has -- an off-axis point
reports a radius smaller than the true inscribed circle.  Every graph JSON we
emit therefore carries ``"radiusSource": "derived-distance-to-boundary"``.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep

SNAP = 1e-6


@dataclass
class Node:
    id: str
    x: float
    y: float
    radius: float | None = None
    degree: int = 0

    def to_json(self):
        d = {"id": self.id, "x": round(self.x, 6), "y": round(self.y, 6)}
        if self.radius is not None:
            d["radius"] = round(self.radius, 6)
        return d


@dataclass
class Edge:
    id: str
    frm: str
    to: str
    geometry: list[tuple[float, float]]
    length: float
    medianRadius: float | None = None
    radii: list[float] = field(default_factory=list)
    sourceElementId: str | None = None
    sourceFill: str | None = None

    def to_json(self):
        d = {
            "id": self.id,
            "from": self.frm,
            "to": self.to,
            # geometry is Point[] (the polyline form of the model's
            # `Bezier[] | Point[]`); this backend produces polylines, not curves.
            "geometry": [{"x": round(x, 6), "y": round(y, 6)} for x, y in self.geometry],
            "length": round(self.length, 6),
        }
        if self.medianRadius is not None:
            d["medianRadius"] = round(self.medianRadius, 6)
        if self.radii:
            # Extension beyond the shared model: the radius profile along the
            # edge, sampled at equal normalised arc length.  A single
            # medianRadius cannot represent a tapered stroke (synthetic case
            # 19 re-strokes at IoU 0.72 from medianRadius alone), so the
            # profile is exported for anyone doing variable-width re-stroking.
            d["radiusProfile"] = [round(r, 6) for r in self.radii]
        if self.sourceElementId is not None:
            d["sourceElementId"] = self.sourceElementId
        if self.sourceFill is not None:
            # Carried so a re-stroke reproduces the original ink colour; the
            # raster pixel-diff is colour-sensitive and black-on-coloured
            # scores ~6-32% differing pixels on artwork that is geometrically
            # near-perfect.
            d["sourceFill"] = self.sourceFill
        return d


@dataclass
class Graph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def total_length(self) -> float:
        return sum(e.length for e in self.edges)

    def branch_count(self) -> int:
        """Terminal (degree-1) endpoints -- the count Track 8's pruning targets."""
        deg: dict[str, int] = {}
        for e in self.edges:
            deg[e.frm] = deg.get(e.frm, 0) + 1
            deg[e.to] = deg.get(e.to, 0) + 1
        return sum(1 for v in deg.values() if v == 1)

    def junction_count(self) -> int:
        deg: dict[str, int] = {}
        for e in self.edges:
            deg[e.frm] = deg.get(e.frm, 0) + 1
            deg[e.to] = deg.get(e.to, 0) + 1
        return sum(1 for v in deg.values() if v >= 3)

    def to_json(self):
        return {
            "nodes": [n.to_json() for n in self.nodes],
            "edges": [e.to_json() for e in self.edges],
            "meta": self.meta,
        }

    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_json(), f)

    def to_multilinestring(self) -> MultiLineString:
        parts = [LineString(e.geometry) for e in self.edges if len(e.geometry) >= 2]
        return MultiLineString(parts) if parts else MultiLineString([])


# --------------------------------------------------------------------------


def _key(p, q=1e6):
    return (round(p[0] * q), round(p[1] * q))


def build_graph(
    lines: MultiLineString,
    polygon: BaseGeometry | None = None,
    source_element_id: str | None = None,
    source_fill: str | None = None,
    radius_samples: int = 24,
    meta: dict | None = None,
) -> Graph:
    """Turn a set of centerline linestrings into the common graph model.

    Vertices shared by more than two linestrings become junction nodes; runs of
    degree-2 vertices are merged into one edge so the graph is topological
    rather than per-segment.
    """
    g = Graph(meta=dict(meta or {}))
    g.meta.setdefault("radiusSource", "derived-distance-to-boundary")
    g.meta.setdefault("geometryFormat", "Point[] (polyline); no Bezier fitting in this track")

    # 1. explode into unit segments keyed on snapped coordinates
    adj: dict[tuple, list[tuple]] = {}
    coord: dict[tuple, tuple[float, float]] = {}
    seg_seen: set = set()
    for ls in lines.geoms:
        cs = list(ls.coords)
        for a, b in zip(cs[:-1], cs[1:]):
            ka, kb = _key(a), _key(b)
            if ka == kb:
                continue
            sk = (ka, kb) if ka < kb else (kb, ka)
            if sk in seg_seen:
                continue
            seg_seen.add(sk)
            coord[ka], coord[kb] = a[:2], b[:2]
            adj.setdefault(ka, []).append(kb)
            adj.setdefault(kb, []).append(ka)

    if not adj:
        return g

    # 2. node ids for every non-degree-2 vertex
    node_of: dict[tuple, str] = {}

    def node_for(k) -> str:
        if k not in node_of:
            nid = f"n{len(node_of)}"
            node_of[k] = nid
            x, y = coord[k]
            g.nodes.append(Node(nid, x, y, degree=len(adj[k])))
        return node_of[k]

    anchors = [k for k, nb in adj.items() if len(nb) != 2]
    visited_seg: set = set()
    edge_paths: list[list[tuple]] = []

    def walk_from(start):
        for nb in adj[start]:
            sk = (start, nb) if start < nb else (nb, start)
            if sk in visited_seg:
                continue
            path = [start, nb]
            visited_seg.add(sk)
            prev, cur = start, nb
            while len(adj[cur]) == 2:
                nxt = adj[cur][0] if adj[cur][0] != prev else adj[cur][1]
                sk2 = (cur, nxt) if cur < nxt else (nxt, cur)
                if sk2 in visited_seg:
                    break
                visited_seg.add(sk2)
                path.append(nxt)
                prev, cur = cur, nxt
                if cur == start:
                    break
            edge_paths.append(path)

    for a in anchors:
        walk_from(a)
    # isolated cycles (every vertex degree 2)
    for k in adj:
        if all(((k, nb) if k < nb else (nb, k)) in visited_seg for nb in adj[k]):
            continue
        walk_from(k)

    # 3. materialize edges
    boundary = polygon.boundary if polygon is not None else None
    prepared = prep(polygon) if polygon is not None else None
    for i, path in enumerate(edge_paths):
        pts = [coord[k] for k in path]
        ls = LineString(pts)
        if ls.length <= 0:
            continue
        a_id, b_id = node_for(path[0]), node_for(path[-1])
        radii = _sample_radii(ls, boundary, prepared, radius_samples)
        e = Edge(
            id=f"e{i}",
            frm=a_id,
            to=b_id,
            geometry=[(float(x), float(y)) for x, y in pts],
            length=float(ls.length),
            medianRadius=float(np.median(radii)) if len(radii) else None,
            radii=[float(r) for r in radii],
            sourceElementId=source_element_id,
            sourceFill=source_fill,
        )
        g.edges.append(e)

    # 4. node radii
    if boundary is not None:
        for n in g.nodes:
            n.radius = float(boundary.distance(Point(n.x, n.y)))
    return g


def _sample_radii(ls: LineString, boundary, prepared, n: int) -> np.ndarray:
    if boundary is None:
        return np.array([])
    n = max(3, min(n, max(3, int(ls.length))))
    ts = np.linspace(0.0, 1.0, n)
    out = []
    for t in ts:
        p = ls.interpolate(t, normalized=True)
        d = boundary.distance(p)
        if prepared is not None and not prepared.contains(p):
            d = -d
        out.append(d)
    return np.array(out)


def merge_graphs(graphs: list[Graph], meta: dict | None = None) -> Graph:
    out = Graph(meta=dict(meta or {}))
    out.meta.setdefault("radiusSource", "derived-distance-to-boundary")
    for gi, g in enumerate(graphs):
        remap = {}
        for n in g.nodes:
            nid = f"g{gi}_{n.id}"
            remap[n.id] = nid
            out.nodes.append(Node(nid, n.x, n.y, n.radius, n.degree))
        for e in g.edges:
            out.edges.append(
                Edge(f"g{gi}_{e.id}", remap[e.frm], remap[e.to], e.geometry,
                     e.length, e.medianRadius, e.radii, e.sourceElementId,
                     e.sourceFill)
            )
    return out


# --------------------------------------------------------------------------
# re-stroke
# --------------------------------------------------------------------------


def restroke(graph: Graph, quad_segs: int = 16, min_radius: float = 1e-6):
    """Buffer every edge by its own median radius; union to a reconstruction."""
    from shapely.ops import unary_union

    parts = []
    for e in graph.edges:
        if len(e.geometry) < 2:
            continue
        r = e.medianRadius or 0.0
        if r <= min_radius:
            continue
        parts.append(LineString(e.geometry).buffer(r, cap_style=1, join_style=1,
                                                   quad_segs=quad_segs))
    if not parts:
        from shapely.geometry import Polygon as _P

        return _P()
    return unary_union(parts)


def restroke_variable(graph: Graph, step: float = 0.5, quad_segs: int = 8):
    """Re-stroke using the per-edge radius PROFILE instead of one median radius.

    Diagnostic, not a deliverable: it answers "how much of the reconstruction
    error is the centerline, and how much is the constant-width assumption?".
    On the two hardest inputs it removes most of the error, which means the
    extracted axis is better than a median-radius score implies.
    """
    from shapely.ops import unary_union

    parts = []
    for e in graph.edges:
        if len(e.geometry) < 2 or not e.radii:
            continue
        ls = LineString(e.geometry)
        if ls.length <= 0:
            continue
        rr = np.asarray(e.radii, dtype=float)
        ts = np.linspace(0.0, 1.0, len(rr))
        n = max(4, int(ls.length / max(step * float(np.median(rr)), 0.5)))
        for t in np.linspace(0.0, 1.0, n):
            r = float(np.interp(t, ts, rr))
            if r <= 0:
                continue
            parts.append(ls.interpolate(t, normalized=True).buffer(r, quad_segs=quad_segs))
    if not parts:
        from shapely.geometry import Polygon as _P

        return _P()
    return unary_union(parts)


def to_svg_paths(graph: Graph, stroke: str | None = None,
                 variable: bool = False, chunks: int = 0) -> list[str]:
    """Re-stroked paths, one per edge, in the source element's own fill colour.

    With ``variable=True`` each edge is split into ``chunks`` overlapping runs,
    each carrying its own stroke-width sampled from the radius profile.  The
    output is still ordinary ``<path stroke stroke-width>`` markup, just more
    of it -- the cost of representing a stroke whose width changes.
    """
    out = []
    for e in graph.edges:
        if len(e.geometry) < 2:
            continue
        col = stroke or e.sourceFill or "#000000"
        if not variable or not e.radii:
            d = "M " + " L ".join(f"{x:.3f} {y:.3f}" for x, y in e.geometry)
            w = 2.0 * (e.medianRadius or 0.0)
            out.append(
                f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{w:.3f}" '
                f'stroke-linecap="round" stroke-linejoin="round"/>')
            continue
        ls = LineString(e.geometry)
        rr = np.asarray(e.radii, dtype=float)
        k = chunks or max(1, min(len(rr) - 1, int(ls.length / max(2 * np.median(rr), 1))))
        ts = np.linspace(0.0, 1.0, k + 1)
        for i in range(k):
            a, b = ts[i], ts[i + 1]
            pts = [ls.interpolate(t, normalized=True)
                   for t in np.linspace(a, b, max(2, int((b - a) * len(e.geometry)) + 2))]
            d = "M " + " L ".join(f"{p.x:.3f} {p.y:.3f}" for p in pts)
            r = float(np.interp((a + b) / 2, np.linspace(0, 1, len(rr)), rr))
            out.append(
                f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{2*r:.3f}" '
                f'stroke-linecap="round" stroke-linejoin="round"/>')
    return out
