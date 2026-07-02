#!/usr/bin/env python3
"""Vector chordal-axis reconstruction v3: contract each fold cluster to its
sharp outline corner, giving a clean snake of teeth joined at sharp vertices.
Renders a stroked SVG for the scribble; the ring is added separately."""
from __future__ import annotations

import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from shapely.geometry import Polygon, Point

sys.path.insert(0, str(Path(__file__).parent))
from chordal import flatten_path, resample_ring
import chordal2 as C


def cluster_nodes(node_keys, pts, edges, short_len):
    """Merge graph nodes joined by a short edge (fork/bridge) into one fold
    cluster. Teeth are the long edges left spanning between clusters."""
    keys = list(node_keys)
    parent = {k: k for k in keys}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for e in edges:
        a, b = e[0], e[-1]
        if a in parent and b in parent and C.polyline_len(e, pts) < short_len:
            union(a, b)
    groups = defaultdict(list)
    for k in keys:
        groups[find(k)].append(k)
    return groups


def reconstruct(src, curve_steps=24):
    txt = Path(src).read_text()
    vb = list(map(float, re.split(r"[\s,]+", re.search(r'viewBox="([^"]+)"', txt).group(1).strip())))
    paths = re.findall(r'<path\b[^>]*\bd="([^"]*)"', txt, re.S)
    fills = re.findall(r'<path\b[^>]*\bfill="(#[0-9A-Fa-f]{6})"', txt, re.S)
    color = fills[1] if len(fills) > 1 else "#ffcd19"

    subs = flatten_path(paths[1], curve_steps)
    poly = C.largest_poly(Polygon(subs[0]).buffer(0))
    ext = poly.exterior
    ring = resample_ring(subs[0], step=2.0)

    segs = C.chordal_segments(ring, poly)
    dists = [C.dist_to_edge(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), ext) for a, b, _ in segs]
    width = 2 * float(np.median(dists))
    radius = width / 2

    adj, pts, nodes, edges = C.build_graph(segs)
    edges = C.prune_spurs(edges, pts, nodes, max_len=radius * 1.6)

    # All edge endpoints are candidate nodes (a degree-2 node between two long
    # teeth becomes its own singleton cluster and is walked through later).
    node_keys = set()
    for e in edges:
        node_keys.add(e[0])
        node_keys.add(e[-1])

    # Contract fold clusters: nodes joined by short fork/bridge edges.
    groups = cluster_nodes(node_keys, pts, edges, short_len=width * 0.95)
    root_of = {}
    for root, members in groups.items():
        for m in members:
            root_of[m] = root

    # supernode representative = cluster member farthest from cluster centroid
    # (the outermost sharp corner of the fold), plus inward direction.
    super_pts = {}
    for root, members in groups.items():
        P = np.array([pts[m] for m in members])
        c = P.mean(axis=0)
        far = members[int(np.argmax(((P - c) ** 2).sum(axis=1)))]
        super_pts[root] = pts[far]

    # tooth edges = graph edges whose endpoints are in different clusters and
    # that are long enough to be a real stroke (not an internal bridge).
    teeth = []
    for e in edges:
        a, b = e[0], e[-1]
        if a not in root_of or b not in root_of:
            continue
        ra, rb = root_of[a], root_of[b]
        if ra == rb:
            continue
        if C.polyline_len(e, pts) < width * 0.95:
            continue
        teeth.append((ra, rb, e))

    # Build supernode graph and trace snake path(s).
    g = defaultdict(list)
    for ti, (ra, rb, e) in enumerate(teeth):
        g[ra].append((rb, ti))
        g[rb].append((ra, ti))

    # inward direction at each supernode = mean of directions toward its teeth
    def tooth_dir_from(root, e):
        p0 = pts[e[0]]
        pts_e = [pts[k] for k in e]
        if root_of[e[0]] == root:
            a, b = pts_e[0], pts_e[min(len(pts_e) - 1, 6)]
        else:
            a, b = pts_e[-1], pts_e[max(0, len(pts_e) - 7)]
        v = (b[0] - a[0], b[1] - a[1])
        n = math.hypot(*v) or 1
        return (v[0] / n, v[1] / n)

    inward = {}
    for root in super_pts:
        dirs = [tooth_dir_from(root, teeth[ti][2]) for (_, ti) in g[root]]
        if not dirs:
            inward[root] = (0.0, 0.0)
            continue
        mx = sum(d[0] for d in dirs) / len(dirs)
        my = sum(d[1] for d in dirs) / len(dirs)
        n = math.hypot(mx, my) or 1
        inward[root] = (mx / n, my / n)

    # vertex position: corner backed off by radius toward the teeth (inward)
    vtx = {}
    for root, cp in super_pts.items():
        iw = inward[root]
        vtx[root] = (cp[0] + iw[0] * radius, cp[1] + iw[1] * radius)

    # trace paths through supernodes of degree<=2 (the snake)
    used = set()
    strokes = []
    order = sorted(g, key=lambda r: len(g[r]))  # start at ends (deg 1)
    for start in order:
        for (nb, ti) in g[start]:
            if ti in used:
                continue
            chain = [start]
            cur, tid = start, ti
            while True:
                nxt = None
                for (nb2, ti2) in g[cur]:
                    if ti2 == tid:
                        nxt = nb2
                        break
                used.add(tid)
                chain.append(nxt)
                cur = nxt
                # continue only through degree-2 supernodes
                nexts = [(nb2, ti2) for (nb2, ti2) in g[cur] if ti2 not in used]
                if len(g[cur]) == 2 and len(nexts) == 1:
                    nb2, ti2 = nexts[0]
                    tid = ti2
                else:
                    break
            strokes.append([vtx[r] for r in chain])

    # any teeth not consumed (isolated) -> straight tip-to-tip
    for ti, (ra, rb, e) in enumerate(teeth):
        if ti not in used:
            strokes.append([vtx[ra], vtx[rb]])

    return vb, color, width, strokes, subs[0]


def ring_centerline(src, samples=240):
    """Reconstruct the ring's wavy centerline loop + width from path 0's two
    edge loops (outer + inner), so it follows the hand-drawn waviness."""
    txt = Path(src).read_text()
    paths = re.findall(r'<path\b[^>]*\bd="([^"]*)"', txt, re.S)
    subs = flatten_path(paths[0])
    P = np.vstack([np.array(s) for s in subs])
    cx, cy = P[:, 0].mean(), P[:, 1].mean()
    loops = sorted(
        (np.array(s) for s in subs),
        key=lambda a: np.hypot(a[:, 0] - cx, a[:, 1] - cy).mean(),
    )
    inner, outer = loops[0], loops[-1]

    def radial(loop):
        ang = np.arctan2(loop[:, 1] - cy, loop[:, 0] - cx)
        rad = np.hypot(loop[:, 0] - cx, loop[:, 1] - cy)
        o = np.argsort(ang)
        return ang[o], rad[o]

    ai, ri = radial(inner)
    ao, ro = radial(outer)
    grid = np.linspace(-np.pi, np.pi, samples, endpoint=False)
    ri_g = np.interp(grid, ai, ri, period=2 * np.pi)
    ro_g = np.interp(grid, ao, ro, period=2 * np.pi)
    rmid = (ri_g + ro_g) / 2
    width = float(np.median(ro_g - ri_g))
    pts = [(cx + rmid[k] * math.cos(grid[k]), cy + rmid[k] * math.sin(grid[k])) for k in range(samples)]
    pts.append(pts[0])
    return pts, width


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "inputs/sun-5.svg"
    vb, color, width, strokes, outline = reconstruct(src)
    width *= 1.08
    ring_pts, band = ring_centerline(src)
    print(f"{src}: scribble width={width:.1f} strokes={len(strokes)}; ring band={band:.1f}")
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" viewBox="{vb[0]} {vb[1]} {vb[2]} {vb[3]}">',
           '  <g fill="none" stroke-linecap="round" stroke-linejoin="round">']
    rd = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in ring_pts)
    out.append(f'    <path d="{rd}" stroke="{color}" stroke-width="{band:.1f}"/>')
    for s in strokes:
        d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in s)
        out.append(f'    <path d="{d}" stroke="{color}" stroke-width="{width:.1f}"/>')
    out += ["  </g>", "</svg>"]
    Path("debug/sun/chordal3-out.svg").write_text("\n".join(out))
    print("  wrote debug/sun/chordal3-out.svg")


if __name__ == "__main__":
    main()
