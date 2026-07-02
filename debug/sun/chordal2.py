#!/usr/bin/env python3
"""Vector chordal-axis stroke reconstruction, v2: graph assembly with spur
pruning, hairpin-aware pairing through folds, and tip pull-back, then render
a stroked SVG. Compares directly against the filled input."""
from __future__ import annotations

import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.spatial import Delaunay
from shapely.geometry import Polygon, Point

sys.path.insert(0, str(Path(__file__).parent))
from chordal import flatten_path, resample_ring  # reuse flattener


def largest_poly(poly):
    if poly.geom_type == "Polygon":
        return poly
    return max(poly.geoms, key=lambda g: g.area)


def chordal_segments(ring: np.ndarray, poly: Polygon):
    """Return axis segments plus, for terminal triangles, the tip corner."""
    n = len(ring)
    tri = Delaunay(ring)

    def inside(t):
        return poly.contains(Point(ring[t].mean(axis=0)))

    def is_boundary(i, j):
        return abs(i - j) == 1 or abs(i - j) == n - 1

    def mid(i, j):
        return ((ring[i][0] + ring[j][0]) / 2, (ring[i][1] + ring[j][1]) / 2)

    segs = []
    for t in tri.simplices:
        if not inside(t):
            continue
        e = [(t[0], t[1]), (t[1], t[2]), (t[2], t[0])]
        bflag = [is_boundary(i, j) for i, j in e]
        nb = sum(bflag)
        if nb == 3:
            continue
        if nb == 2:
            internal = e[bflag.index(False)]
            apex = list({t[0], t[1], t[2]} - set(internal))[0]
            segs.append((mid(*internal), (ring[apex][0], ring[apex][1]), "tip"))
        elif nb == 1:
            ints = [e[k] for k in range(3) if not bflag[k]]
            segs.append((mid(*ints[0]), mid(*ints[1]), "sleeve"))
        else:
            cen = (float(ring[t][:, 0].mean()), float(ring[t][:, 1].mean()))
            for i, j in e:
                segs.append((cen, mid(i, j), "junc"))
    return segs


def dist_to_edge(pt, ext):
    return ext.distance(Point(pt))


def build_graph(segs):
    """Return nodes (deg!=2 pts), and edges as polylines between nodes."""
    K = lambda p: (round(p[0], 2), round(p[1], 2))
    adj = defaultdict(set)
    pts = {}
    for a, b, _ in segs:
        ka, kb = K(a), K(b)
        if ka == kb:
            continue
        pts[ka], pts[kb] = a, b
        adj[ka].add(kb)
        adj[kb].add(ka)

    used = set()
    ek = lambda a, b: (a, b) if a <= b else (b, a)
    nodes = {k for k in adj if len(adj[k]) != 2}
    edges = []  # dict: pts list, endpoints (key),
    starts = nodes or set(list(adj)[:1])
    for s in starts:
        for nb in list(adj[s]):
            if ek(s, nb) in used:
                continue
            chain = [s, nb]
            used.add(ek(s, nb))
            prev, cur = s, nb
            while cur not in nodes:
                nxts = [q for q in adj[cur] if ek(cur, q) not in used]
                if not nxts:
                    break
                nq = nxts[0]
                used.add(ek(cur, nq))
                chain.append(nq)
                prev, cur = cur, nq
            edges.append(chain)
    # leftover loops
    for a, b, _ in segs:
        ka, kb = K(a), K(b)
        if ka != kb and ek(ka, kb) not in used:
            used.add(ek(ka, kb))
            edges.append([ka, kb])
    return adj, pts, nodes, edges


def polyline_len(chain, pts):
    return sum(math.dist(pts[chain[i]], pts[chain[i - 1]]) for i in range(1, len(chain)))


def prune_spurs(edges, pts, nodes, max_len):
    """Iteratively drop terminal edges shorter than max_len (tip forks)."""
    changed = True
    edges = [list(e) for e in edges]
    while changed:
        changed = False
        deg = defaultdict(int)
        for e in edges:
            deg[e[0]] += 1
            deg[e[-1]] += 1
        keep = []
        for e in edges:
            terminal = deg[e[0]] == 1 or deg[e[-1]] == 1
            if terminal and deg[e[0]] != deg[e[-1]] and polyline_len(e, pts) < max_len:
                # drop only if the other end is a junction (deg>=3)
                other = e[-1] if deg[e[0]] == 1 else e[0]
                if deg[other] >= 3:
                    changed = True
                    continue
            keep.append(e)
        edges = keep
    return edges


def tangent(chain, pts, at_start, span=6):
    if at_start:
        a = pts[chain[0]]
        b = pts[chain[min(len(chain) - 1, span)]]
    else:
        a = pts[chain[-1]]
        b = pts[chain[max(0, len(chain) - 1 - span)]]
    v = (b[0] - a[0], b[1] - a[1])
    n = math.hypot(*v) or 1
    return (v[0] / n, v[1] / n)  # points inward from the endpoint


def assemble(edges, pts, nodes):
    """Pair edges at each junction by most-parallel outward tangent (hairpin
    turns) and walk into long strokes."""
    ends = []  # (edge_idx, which_end 0/1, node_key, inward_tangent)
    for idx, e in enumerate(edges):
        ends.append((idx, 0, e[0], tangent(e, pts, True)))
        ends.append((idx, 1, e[-1], tangent(e, pts, False)))
    by_node = defaultdict(list)
    for en in ends:
        by_node[en[2]].append(en)

    pair = {}
    for node, group in by_node.items():
        if len(group) < 2:
            continue
        # outward tangent = -inward
        cand = []
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                gi, gj = group[i], group[j]
                oi = (-gi[3][0], -gi[3][1])
                oj = (-gj[3][0], -gj[3][1])
                dot = oi[0] * oj[0] + oi[1] * oj[1]
                cand.append((dot, i, j))
        # hairpin: outward directions nearly parallel (dot near +1) -> pen
        # turns back alongside itself. Pick most-parallel pairs greedily.
        cand.sort(reverse=True)
        used = set()
        for dot, i, j in cand:
            if i in used or j in used:
                continue
            if dot < 0.3:  # too divergent to be one stroke turning
                continue
            a, b = group[i], group[j]
            pair[(a[0], a[1])] = (b[0], b[1])
            pair[(b[0], b[1])] = (a[0], a[1])
            used.add(i)
            used.add(j)

    oriented = lambda idx, end: edges[idx] if end == 0 else edges[idx][::-1]
    used_edges = set()
    strokes = []
    starts = [(i, e) for i in range(len(edges)) for e in (0, 1) if (i, e) not in pair]
    for si, se in starts:
        if si in used_edges:
            continue
        chain_keys = []
        idx, end = si, se
        while idx not in used_edges:
            seg = oriented(idx, end)
            used_edges.add(idx)
            chain_keys += seg if not chain_keys else seg[1:]
            exit_end = 1 - end
            nxt = pair.get((idx, exit_end))
            if nxt is None:
                break
            idx, pend = nxt
            end = pend
        strokes.append([pts[k] for k in chain_keys])
    for i in range(len(edges)):
        if i in used_edges:
            continue
        strokes.append([pts[k] for k in edges[i]])
    return strokes


def rdp(points, eps):
    if len(points) < 3:
        return points
    dmax, idx = 0, 0
    a, b = points[0], points[-1]
    for i in range(1, len(points) - 1):
        d = _perp(points[i], a, b)
        if d > dmax:
            dmax, idx = d, i
    if dmax <= eps:
        return [a, b]
    return rdp(points[: idx + 1], eps)[:-1] + rdp(points[idx:], eps)


def _perp(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 and dy == 0:
        return math.dist(p, a)
    return abs(dy * p[0] - dx * p[1] + b[0] * a[1] - b[1] * a[0]) / math.hypot(dx, dy)


def pull_tip(chain, ext, radius, at_end):
    """Pull a terminal endpoint back to radius inside the outline tip."""
    if len(chain) < 2:
        return chain
    i0, i1 = (-1, -2) if at_end else (0, 1)
    tip = chain[i0]
    inward = (chain[i1][0] - tip[0], chain[i1][1] - tip[1])
    n = math.hypot(*inward) or 1
    d = (inward[0] / n, inward[1] / n)
    new = (tip[0] + d[0] * radius, tip[1] + d[1] * radius)
    chain = list(chain)
    chain[i0] = new
    return chain


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "inputs/sun-5.svg"
    txt = Path(src).read_text()
    vb = list(map(float, re.split(r"[\s,]+", re.search(r'viewBox="([^"]+)"', txt).group(1).strip())))
    paths = re.findall(r'<path\b[^>]*\bd="([^"]*)"', txt, re.S)
    fills = re.findall(r'<path\b[^>]*\bfill="(#[0-9A-Fa-f]{6})"', txt, re.S)
    color = fills[1] if len(fills) > 1 else "#ffcd19"

    subs = flatten_path(paths[1])
    poly = largest_poly(Polygon(subs[0]).buffer(0))
    ext = poly.exterior
    ring = resample_ring(subs[0], step=2.0)

    segs = chordal_segments(ring, poly)
    dists = [dist_to_edge(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), ext) for a, b, _ in segs]
    width = 2 * float(np.median(dists))
    radius = width / 2

    adj, pts, nodes, edges = build_graph(segs)
    edges = prune_spurs(edges, pts, nodes, max_len=radius * 1.6)
    # recompute node set after pruning
    deg = defaultdict(int)
    for e in edges:
        deg[e[0]] += 1
        deg[e[-1]] += 1
    nodes = {k for k in deg if deg[k] != 2}
    strokes = assemble(edges, pts, nodes)

    # pull terminal tips back by radius, simplify
    deg = defaultdict(int)
    for s in strokes:
        pass
    final = []
    for s in strokes:
        if len(s) < 2:
            continue
        s = pull_tip(s, ext, radius, at_end=True)
        s = pull_tip(s, ext, radius, at_end=False)
        s = rdp(s, 0.8)
        if len(s) >= 2:
            final.append(s)
    print(f"{src}: width={width:.1f} strokes={len(final)} (pts {sum(len(s) for s in final)})")

    out = [f'<?xml version="1.0" encoding="UTF-8"?>',
           f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" viewBox="{vb[0]} {vb[1]} {vb[2]} {vb[3]}">',
           f'  <g fill="none" stroke="{color}" stroke-width="{width:.1f}" stroke-linecap="round" stroke-linejoin="round">']
    for s in final:
        d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in s)
        out.append(f'    <path d="{d}"/>')
    out += ["  </g>", "</svg>"]
    Path("debug/sun/chordal2-out.svg").write_text("\n".join(out))
    print("  wrote debug/sun/chordal2-out.svg")


if __name__ == "__main__":
    main()
