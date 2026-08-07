"""Common centerline graph model (Common Setup §"Emit the common graph model").

    CenterlineNode { id, x, y, radius? }
    CenterlineEdge { id, from, to, geometry: Point[], length, medianRadius?, sourceElementId? }

Also holds the generic graph operations every engine in this track needs:
contract degree-2 chains, prune tips, and re-stroke to SVG.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict


@dataclass
class Node:
    id: str
    x: float
    y: float
    radius: float = 0.0


@dataclass
class Edge:
    id: str
    frm: str
    to: str
    geometry: list  # list[(x, y)]
    length: float
    medianRadius: float = 0.0
    radii: list = field(default_factory=list)
    sourceElementId: str = ""


class CenterlineGraph:
    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self._n = 0
        self._e = 0

    # -- construction --------------------------------------------------------
    def add_node(self, x, y, radius=0.0, nid=None):
        if nid is None:
            nid = f"n{self._n}"
            self._n += 1
        self.nodes[nid] = Node(nid, x, y, radius)
        return nid

    def add_edge(self, frm, to, geometry, radii=None, source=""):
        eid = f"e{self._e}"
        self._e += 1
        length = polyline_length(geometry)
        radii = radii or []
        self.edges[eid] = Edge(
            eid, frm, to, geometry, length, median(radii), radii, source
        )
        return eid

    # -- topology ------------------------------------------------------------
    def incident(self):
        inc = {nid: [] for nid in self.nodes}
        for e in self.edges.values():
            inc[e.frm].append(e.id)
            if e.to != e.frm:
                inc[e.to].append(e.id)
        return inc

    def degree(self):
        return {k: len(v) for k, v in self.incident().items()}

    def contract_chains(self):
        """Merge runs of degree-2 nodes into single edges."""
        inc = self.incident()
        deg = {k: len(v) for k, v in inc.items()}
        visited = set()
        new = CenterlineGraph()
        idmap = {}

        def keep(nid):
            if nid not in idmap:
                n = self.nodes[nid]
                idmap[nid] = new.add_node(n.x, n.y, n.radius, nid=nid)
            return idmap[nid]

        anchors = [n for n in self.nodes if deg.get(n, 0) != 2]
        # Anchors first, then every remaining node: a component that is a pure
        # cycle (a closed stroke — the cloud in house-wide, case 06) has no
        # anchor of its own and would otherwise be dropped whenever some *other*
        # component in the same graph supplied anchors.
        anchor_set = set(anchors)
        seeds = anchors + [n for n in self.nodes if n not in anchor_set]

        for start in seeds:
            for e0 in inc[start]:
                if e0 in visited:
                    continue
                pts, radii, src = [], [], ""
                cur_node, cur_edge = start, e0
                while True:
                    visited.add(cur_edge)
                    e = self.edges[cur_edge]
                    geom = e.geometry if e.frm == cur_node else e.geometry[::-1]
                    rr = e.radii if e.frm == cur_node else e.radii[::-1]
                    if pts:
                        geom = geom[1:]
                        rr = rr[1:] if rr else rr
                    pts.extend(geom)
                    radii.extend(rr)
                    src = src or e.sourceElementId
                    nxt = e.to if e.frm == cur_node else e.frm
                    if deg.get(nxt, 0) != 2 or nxt == start:
                        cur_node = nxt
                        break
                    nn = [x for x in inc[nxt] if x != cur_edge]
                    if not nn or nn[0] in visited:
                        cur_node = nxt
                        break
                    cur_node, cur_edge = nxt, nn[0]
                new.add_edge(keep(start), keep(cur_node), pts, radii, src)
        # carry over any untouched nodes
        for nid in self.nodes:
            if nid in idmap:
                continue
            if deg.get(nid, 0) != 2:
                keep(nid)
        return new

    def prune_tips(self, k=1.0, max_rounds=12):
        """Minimal boundary-noise pruning: drop leaf chains shorter than k times
        the clearance radius at their attachment node.

        Deliberately the simplest defensible rule (Common Setup: "do not
        implement sophisticated pruning early" — Track 8 owns real pruning).
        """
        g = self
        for _ in range(max_rounds):
            inc = g.incident()
            deg = {n: len(v) for n, v in inc.items()}
            drop = set()
            for e in g.edges.values():
                leaf = None
                anchor = None
                if deg.get(e.frm, 0) == 1 and deg.get(e.to, 0) > 1:
                    leaf, anchor = e.frm, e.to
                elif deg.get(e.to, 0) == 1 and deg.get(e.frm, 0) > 1:
                    leaf, anchor = e.to, e.frm
                if leaf is None:
                    continue
                r = g.nodes[anchor].radius
                if e.length < k * max(r, 1e-9):
                    drop.add(e.id)
            if not drop:
                break
            ng = CenterlineGraph()
            keep_ids = {}

            def keep(nid, gg=g, ng=ng, keep_ids=keep_ids):
                if nid not in keep_ids:
                    n = gg.nodes[nid]
                    keep_ids[nid] = ng.add_node(n.x, n.y, n.radius, nid=nid)
                return keep_ids[nid]

            for e in g.edges.values():
                if e.id in drop:
                    continue
                ng.add_edge(keep(e.frm), keep(e.to), e.geometry, e.radii, e.sourceElementId)
            g = ng.contract_chains()
        return g

    def drop_short_components(self, min_length=0.0):
        """Remove connected components whose total length is below min_length."""
        if min_length <= 0:
            return self
        inc = self.incident()
        seen = set()
        keep_edges = set()
        for start in self.nodes:
            if start in seen:
                continue
            stack, comp_nodes, comp_edges = [start], set(), set()
            seen.add(start)
            while stack:
                n = stack.pop()
                comp_nodes.add(n)
                for eid in inc[n]:
                    comp_edges.add(eid)
                    e = self.edges[eid]
                    for m in (e.frm, e.to):
                        if m not in seen:
                            seen.add(m)
                            stack.append(m)
            total = sum(self.edges[eid].length for eid in comp_edges)
            if total >= min_length:
                keep_edges |= comp_edges
        ng = CenterlineGraph()
        idm = {}

        def keep(nid):
            if nid not in idm:
                n = self.nodes[nid]
                idm[nid] = ng.add_node(n.x, n.y, n.radius, nid=nid)
            return idm[nid]

        for eid in keep_edges:
            e = self.edges[eid]
            ng.add_edge(keep(e.frm), keep(e.to), e.geometry, e.radii, e.sourceElementId)
        return ng

    def set_width_stat(self, stat="median"):
        """Choose the per-edge stroke radius statistic.

        `median` is the default. A lower percentile is more robust where an edge
        passes through a junction, whose inscribed circle is larger than the
        stroke half-width and inflates the whole edge.
        """
        for e in self.edges.values():
            if not e.radii:
                continue
            if stat == "median":
                e.medianRadius = median(e.radii)
            elif stat.startswith("p"):
                q = float(stat[1:]) / 100.0
                s = sorted(e.radii)
                e.medianRadius = s[min(len(s) - 1, int(q * len(s)))]
            elif stat == "min":
                e.medianRadius = min(e.radii)
        return self

    def extend_tips(self, geom, max_factor=4.0, steps=24):
        """Width-aware cap extension (report §9.6).

        Pruning and the clearance-zero filter both stop a branch short of the
        real stroke end, and a round-capped re-stroke then leaves the tip blunt.
        Push each leaf forward along its tangent as far as the tip's own
        inscribed disc still fits inside the shape.
        """
        if geom is None:
            return self
        from shapely.geometry import Point

        inc = self.incident()
        deg = {n: len(v) for n, v in inc.items()}
        for e in self.edges.values():
            for end in ("frm", "to"):
                nid = getattr(e, end)
                if deg.get(nid, 0) != 1 or len(e.geometry) < 2:
                    continue
                pts = e.geometry if end == "to" else e.geometry[::-1]
                (x0, y0), (x1, y1) = pts[-2], pts[-1]
                dx, dy = x1 - x0, y1 - y0
                n = math.hypot(dx, dy)
                if n < 1e-9:
                    continue
                dx, dy = dx / n, dy / n
                r = self.nodes[nid].radius
                lo, hi = 0.0, max_factor * max(r, 1e-6)
                best = 0.0
                for _ in range(steps):
                    mid = 0.5 * (lo + hi)
                    p = Point(x1 + dx * mid, y1 + dy * mid)
                    if geom.contains(p) and p.distance(geom.boundary) >= r * 0.995:
                        best, lo = mid, mid
                    else:
                        hi = mid
                if best <= 1e-6:
                    continue
                nx, ny = x1 + dx * best, y1 + dy * best
                if end == "to":
                    e.geometry = e.geometry + [(nx, ny)]
                    e.radii = e.radii + [r]
                else:
                    e.geometry = [(nx, ny)] + e.geometry
                    e.radii = [r] + e.radii
                e.length = polyline_length(e.geometry)
                self.nodes[nid].x, self.nodes[nid].y = nx, ny
        return self

    # -- serialization -------------------------------------------------------
    def to_dict(self, meta=None):
        return {
            "meta": meta or {},
            "nodes": [asdict(n) for n in self.nodes.values()],
            "edges": [
                {
                    "id": e.id,
                    "from": e.frm,
                    "to": e.to,
                    "geometry": [[round(x, 4), round(y, 4)] for x, y in e.geometry],
                    "length": round(e.length, 4),
                    "medianRadius": round(e.medianRadius, 4),
                    "sourceElementId": e.sourceElementId,
                }
                for e in self.edges.values()
            ],
        }

    def write_json(self, path, meta=None):
        with open(path, "w") as f:
            json.dump(self.to_dict(meta), f)

    def stats(self):
        deg = self.degree()
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "branch_nodes": sum(1 for d in deg.values() if d >= 3),
            "leaf_nodes": sum(1 for d in deg.values() if d == 1),
            "points": sum(len(e.geometry) for e in self.edges.values()),
            "total_length": round(sum(e.length for e in self.edges.values()), 3),
        }


def median(vals):
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def polyline_length(pts):
    return sum(
        math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        for i in range(len(pts) - 1)
    )


def simplify_polyline(pts, tol):
    """Ramer-Douglas-Peucker, used only to trim redundant discretization points."""
    if tol <= 0 or len(pts) < 3:
        return pts
    from shapely.geometry import LineString

    return list(LineString(pts).simplify(tol).coords)


def restroke_svg(graph, width, height, stroke="#000", simplify_tol=0.0, background=None):
    """Re-stroke the graph: one <path> per edge, width = 2 * medianRadius."""
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
    ]
    if background:
        parts.append(f'<rect width="{width}" height="{height}" fill="{background}"/>')
    for e in graph.edges.values():
        pts = simplify_polyline(e.geometry, simplify_tol) if simplify_tol else e.geometry
        if len(pts) < 2:
            continue
        d = "M " + " L ".join(f"{x:.3f} {y:.3f}" for x, y in pts)
        w = max(2.0 * e.medianRadius, 0.1)
        parts.append(
            f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{w:.3f}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def restroke_geometry_variable(graph, max_discs=40000):
    """Reconstruction using the FULL medial-axis transform: the union of the
    inscribed discs along each edge, with the per-point clearance radius.

    This is not a deliverable (an SVG stroke has one width), but comparing it
    with `restroke_geometry` separates axis error from the error introduced by
    collapsing each edge to a single stroke width.
    """
    from shapely.geometry import Point, LineString
    from shapely.ops import unary_union

    discs = []
    for e in graph.edges.values():
        pts, radii = e.geometry, e.radii or [e.medianRadius] * len(e.geometry)
        for i, (p, r) in enumerate(zip(pts, radii)):
            if r <= 0:
                continue
            discs.append(Point(p).buffer(r, resolution=8))
            if i + 1 < len(pts):
                # bridge the gap between consecutive samples
                seg = LineString([pts[i], pts[i + 1]])
                if seg.length > 0:
                    discs.append(seg.buffer(min(r, radii[i + 1]), cap_style=1, resolution=8))
        if len(discs) > max_discs:
            break
    return unary_union(discs) if discs else None


def restroke_geometry(graph, simplify_tol=0.0):
    """Shapely reconstruction of the filled shape from the graph (round caps)."""
    from shapely.geometry import LineString
    from shapely.ops import unary_union

    buffers = []
    for e in graph.edges.values():
        pts = simplify_polyline(e.geometry, simplify_tol) if simplify_tol else e.geometry
        if len(pts) < 2 or e.medianRadius <= 0:
            continue
        buffers.append(
            LineString(pts).buffer(e.medianRadius, cap_style=1, join_style=1, resolution=8)
        )
    if not buffers:
        return None
    return unary_union(buffers)
