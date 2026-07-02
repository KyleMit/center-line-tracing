#!/usr/bin/env python3
"""Vector (non-raster) reconstruction of a filled scribble-sun SVG into
stroked lines, with *sharp* zigzag tips.

Unlike the raster skeleton pipeline (convert_filled_svg_to_stroked_lines.py),
this reads the filled outline's path data directly and recovers the pen
centerline from a triangulation-based (chordal-axis) medial axis. Terminal
triangles point straight into the outline's sharp corners, so the zigzag
folds stay sharp instead of being blunted/rounded by skeletonization.

Input assumption (matches inputs/sun-*.svg): two <path> elements — path 0 is
the outer ring band (two edge loops), path 1 is the scribble fill (one closed
outline of a single continuous pen stroke). Handles L/Q/C/A/Z path data, so
every sun-* variant works; the pure-polyline variant (sun-5) is the cleanest
input because there is no curve-flattening approximation.

Usage:
    DYLD_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python sun_vectorize.py \
        inputs/sun-5.svg --output outputs/sun-5.svg

Dependencies: numpy, scipy, shapely.
"""
from __future__ import annotations

import argparse
import math
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.spatial import Delaunay
from shapely.geometry import Polygon, Point


# ---------------------------------------------------------------- flattener

def _tokenize(d: str):
    for m in re.finditer(r"[MmLlHhVvCcSsQqTtAaZz]|-?\d*\.?\d+(?:e-?\d+)?", d):
        yield m.group(0)


def flatten_path(d: str, curve_steps: int = 24) -> list[list[tuple[float, float]]]:
    """Return one list of (x, y) points per subpath (curves sampled)."""
    toks = list(_tokenize(d))
    i = 0
    cx = cy = sx = sy = 0.0
    subpaths: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    cmd = None
    prev_ctrl = None

    def num():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    while i < len(toks):
        if re.match(r"[A-Za-z]", toks[i]):
            cmd = toks[i]
            i += 1
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = (cx, cy) if rel else (0.0, 0.0)

        if c == "M":
            x, y = num() + ox, num() + oy
            if cur:
                subpaths.append(cur)
            cur = [(x, y)]
            cx, cy, sx, sy = x, y, x, y
            cmd = "l" if rel else "L"
            prev_ctrl = None
        elif c == "L":
            x, y = num() + ox, num() + oy
            cur.append((x, y))
            cx, cy = x, y
            prev_ctrl = None
        elif c == "H":
            x = num() + ox
            cur.append((x, cy))
            cx = x
            prev_ctrl = None
        elif c == "V":
            y = num() + oy
            cur.append((cx, y))
            cy = y
            prev_ctrl = None
        elif c in ("Q", "T"):
            if c == "Q":
                x1, y1 = num() + ox, num() + oy
            else:
                x1, y1 = (2 * cx - prev_ctrl[0], 2 * cy - prev_ctrl[1]) if prev_ctrl else (cx, cy)
            x, y = num() + ox, num() + oy
            for s in range(1, curve_steps + 1):
                u = s / curve_steps
                mt = 1 - u
                cur.append((mt * mt * cx + 2 * mt * u * x1 + u * u * x,
                            mt * mt * cy + 2 * mt * u * y1 + u * u * y))
            prev_ctrl = (x1, y1)
            cx, cy = x, y
        elif c in ("C", "S"):
            if c == "C":
                x1, y1 = num() + ox, num() + oy
            else:
                x1, y1 = (2 * cx - prev_ctrl[0], 2 * cy - prev_ctrl[1]) if prev_ctrl else (cx, cy)
            x2, y2 = num() + ox, num() + oy
            x, y = num() + ox, num() + oy
            for s in range(1, curve_steps + 1):
                u = s / curve_steps
                mt = 1 - u
                cur.append((mt**3 * cx + 3 * mt**2 * u * x1 + 3 * mt * u**2 * x2 + u**3 * x,
                            mt**3 * cy + 3 * mt**2 * u * y1 + 3 * mt * u**2 * y2 + u**3 * y))
            prev_ctrl = (x2, y2)
            cx, cy = x, y
        elif c == "A":
            rx, ry = num(), num()
            phi = math.radians(num())
            large, sweep = num(), num()
            x, y = num() + ox, num() + oy
            cur.extend(_arc(cx, cy, rx, ry, phi, large, sweep, x, y, curve_steps))
            cx, cy = x, y
            prev_ctrl = None
        elif c == "Z":
            if cur:
                cur.append((sx, sy))
                subpaths.append(cur)
                cur = []
            cx, cy = sx, sy
            prev_ctrl = None
        else:
            i += 1

    if cur:
        subpaths.append(cur)
    return subpaths


def _arc(x0, y0, rx, ry, phi, large, sweep, x, y, steps):
    if rx == 0 or ry == 0:
        return [(x, y)]
    cosp, sinp = math.cos(phi), math.sin(phi)
    dx, dy = (x0 - x) / 2, (y0 - y) / 2
    x1p = cosp * dx + sinp * dy
    y1p = -sinp * dx + cosp * dy
    rx, ry = abs(rx), abs(ry)
    lam = (x1p / rx) ** 2 + (y1p / ry) ** 2
    if lam > 1:
        s = math.sqrt(lam)
        rx *= s
        ry *= s
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    num_ = rx * rx * ry * ry - den
    co = math.sqrt(max(0.0, num_ / den)) if den else 0.0
    if large == sweep:
        co = -co
    cxp = co * rx * y1p / ry
    cyp = -co * ry * x1p / rx
    cxc = cosp * cxp - sinp * cyp + (x0 + x) / 2
    cyc = sinp * cxp + cosp * cyp + (y0 + y) / 2

    def ang(ux, uy, vx, vy):
        d = (ux * vx + uy * vy) / (math.hypot(ux, uy) * math.hypot(vx, vy))
        a = math.acos(max(-1, min(1, d)))
        return -a if ux * vy - uy * vx < 0 else a

    th1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dth = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dth > 0:
        dth -= 2 * math.pi
    elif sweep and dth < 0:
        dth += 2 * math.pi
    out = []
    for s in range(1, steps + 1):
        th = th1 + dth * s / steps
        out.append((cosp * rx * math.cos(th) - sinp * ry * math.sin(th) + cxc,
                    sinp * rx * math.cos(th) + cosp * ry * math.sin(th) + cyc))
    return out


# ---------------------------------------------------------- chordal axis

def resample_ring(pts, step: float) -> np.ndarray:
    p = np.array(pts, dtype=float)
    if np.allclose(p[0], p[-1]):
        p = p[:-1]
    out = []
    for k in range(len(p)):
        a, b = p[k], p[(k + 1) % len(p)]
        n = max(1, int(round(math.hypot(*(b - a)) / step)))
        for j in range(n):
            out.append(a + (b - a) * (j / n))
    return np.array(out)


def largest_poly(poly):
    return poly if poly.geom_type == "Polygon" else max(poly.geoms, key=lambda g: g.area)


def chordal_segments(ring: np.ndarray, poly: Polygon):
    n = len(ring)
    tri = Delaunay(ring)
    is_boundary = lambda a, b: abs(a - b) == 1 or abs(a - b) == n - 1
    mid = lambda a, b: ((ring[a][0] + ring[b][0]) / 2, (ring[a][1] + ring[b][1]) / 2)
    segs = []
    for t in tri.simplices:
        if not poly.contains(Point(ring[t].mean(axis=0))):
            continue
        e = [(t[0], t[1]), (t[1], t[2]), (t[2], t[0])]
        bflag = [is_boundary(a, b) for a, b in e]
        nb = sum(bflag)
        if nb == 3:
            continue
        if nb == 2:
            internal = e[bflag.index(False)]
            apex = list({t[0], t[1], t[2]} - set(internal))[0]
            segs.append((mid(*internal), (ring[apex][0], ring[apex][1])))
        elif nb == 1:
            ints = [e[k] for k in range(3) if not bflag[k]]
            segs.append((mid(*ints[0]), mid(*ints[1])))
        else:
            cen = (float(ring[t][:, 0].mean()), float(ring[t][:, 1].mean()))
            for a, b in e:
                segs.append((cen, mid(a, b)))
    return segs


def build_graph(segs):
    K = lambda p: (round(p[0], 2), round(p[1], 2))
    adj = defaultdict(set)
    pts = {}
    for a, b in segs:
        ka, kb = K(a), K(b)
        if ka == kb:
            continue
        pts[ka], pts[kb] = a, b
        adj[ka].add(kb)
        adj[kb].add(ka)
    ek = lambda a, b: (a, b) if a <= b else (b, a)
    nodes = {k for k in adj if len(adj[k]) != 2}
    used = set()
    edges = []
    for s in (nodes or set(list(adj)[:1])):
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
    for a, b in segs:
        ka, kb = K(a), K(b)
        if ka != kb and ek(ka, kb) not in used:
            used.add(ek(ka, kb))
            edges.append([ka, kb])
    return pts, edges


def polyline_len(chain, pts):
    return sum(math.dist(pts[chain[i]], pts[chain[i - 1]]) for i in range(1, len(chain)))


def prune_spurs(edges, pts, max_len):
    edges = [list(e) for e in edges]
    changed = True
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
                other = e[-1] if deg[e[0]] == 1 else e[0]
                if deg[other] >= 3:
                    changed = True
                    continue
            keep.append(e)
        edges = keep
    return edges


def cluster_short_edges(node_keys, pts, edges, short_len):
    parent = {k: k for k in node_keys}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for e in edges:
        a, b = e[0], e[-1]
        if a in parent and b in parent and polyline_len(e, pts) < short_len:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    groups = defaultdict(list)
    for k in node_keys:
        groups[find(k)].append(k)
    return groups


# ------------------------------------------------------- reconstruction

def reconstruct_scribble(d: str, curve_steps: int):
    subs = flatten_path(d, curve_steps)
    poly = largest_poly(Polygon(subs[0]).buffer(0))
    ext = poly.exterior
    ring = resample_ring(subs[0], step=2.0)

    segs = chordal_segments(ring, poly)
    dists = [ext.distance(Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)) for a, b in segs]
    width = 2 * float(np.median(dists))
    radius = width / 2

    pts, edges = build_graph(segs)
    edges = prune_spurs(edges, pts, max_len=radius * 1.6)

    node_keys = set()
    for e in edges:
        node_keys.add(e[0])
        node_keys.add(e[-1])
    groups = cluster_short_edges(node_keys, pts, edges, short_len=width * 0.95)
    root_of = {m: root for root, members in groups.items() for m in members}

    super_pt = {}
    for root, members in groups.items():
        P = np.array([pts[m] for m in members])
        c = P.mean(axis=0)
        super_pt[root] = pts[members[int(np.argmax(((P - c) ** 2).sum(axis=1)))]]

    teeth = []
    for e in edges:
        a, b = e[0], e[-1]
        if a not in root_of or b not in root_of:
            continue
        ra, rb = root_of[a], root_of[b]
        if ra != rb and polyline_len(e, pts) >= width * 0.95:
            teeth.append((ra, rb, e))

    g = defaultdict(list)
    for ti, (ra, rb, _e) in enumerate(teeth):
        g[ra].append((rb, ti))
        g[rb].append((ra, ti))

    def tooth_dir(root, e):
        pe = [pts[k] for k in e]
        if root_of[e[0]] == root:
            a, b = pe[0], pe[min(len(pe) - 1, 6)]
        else:
            a, b = pe[-1], pe[max(0, len(pe) - 7)]
        v = (b[0] - a[0], b[1] - a[1])
        n = math.hypot(*v) or 1
        return (v[0] / n, v[1] / n)

    vtx = {}
    for root, cp in super_pt.items():
        dirs = [tooth_dir(root, teeth[ti][2]) for (_, ti) in g[root]]
        if dirs:
            mx = sum(dd[0] for dd in dirs) / len(dirs)
            my = sum(dd[1] for dd in dirs) / len(dirs)
            n = math.hypot(mx, my) or 1
            vtx[root] = (cp[0] + mx / n * radius, cp[1] + my / n * radius)
        else:
            vtx[root] = cp

    used = set()
    strokes = []
    for start in sorted(g, key=lambda r: len(g[r])):
        for (nb, ti) in g[start]:
            if ti in used:
                continue
            chain = [start]
            cur, tid = start, ti
            while True:
                nxt = next(nb2 for (nb2, ti2) in g[cur] if ti2 == tid)
                used.add(tid)
                chain.append(nxt)
                cur = nxt
                nexts = [(nb2, ti2) for (nb2, ti2) in g[cur] if ti2 not in used]
                if len(g[cur]) == 2 and len(nexts) == 1:
                    tid = nexts[0][1]
                else:
                    break
            strokes.append([vtx[r] for r in chain])
    for ti, (ra, rb, _e) in enumerate(teeth):
        if ti not in used:
            strokes.append([vtx[ra], vtx[rb]])
    return width, strokes


def ring_centerline(d: str, curve_steps: int, samples: int = 240):
    subs = flatten_path(d, curve_steps)
    P = np.vstack([np.array(s) for s in subs])
    cx, cy = P[:, 0].mean(), P[:, 1].mean()
    loops = sorted((np.array(s) for s in subs),
                   key=lambda a: np.hypot(a[:, 0] - cx, a[:, 1] - cy).mean())
    inner, outer = loops[0], loops[-1]

    def radial(loop):
        ang = np.arctan2(loop[:, 1] - cy, loop[:, 0] - cx)
        rad = np.hypot(loop[:, 0] - cx, loop[:, 1] - cy)
        o = np.argsort(ang)
        return ang[o], rad[o]

    ai, ri = radial(inner)
    ao, ro = radial(outer)
    grid = np.linspace(-math.pi, math.pi, samples, endpoint=False)
    ri_g = np.interp(grid, ai, ri, period=2 * math.pi)
    ro_g = np.interp(grid, ao, ro, period=2 * math.pi)
    rmid = (ri_g + ro_g) / 2
    band = float(np.median(ro_g - ri_g))
    pts = [(cx + rmid[k] * math.cos(grid[k]), cy + rmid[k] * math.sin(grid[k])) for k in range(samples)]
    pts.append(pts[0])
    return pts, band


def convert(src: Path, out: Path, curve_steps: int = 24, width_scale: float = 1.08):
    txt = src.read_text()
    vb = re.search(r'viewBox="([^"]+)"', txt).group(1).strip()
    vbnums = list(map(float, re.split(r"[\s,]+", vb)))
    paths = re.findall(r'<path\b[^>]*\bd="([^"]*)"', txt, re.S)
    fills = re.findall(r'<path\b[^>]*\bfill="(#[0-9A-Fa-f]{6})"', txt, re.S)
    color = fills[1] if len(fills) > 1 else (fills[0] if fills else "#000000")

    width, strokes = reconstruct_scribble(paths[1], curve_steps)
    width *= width_scale
    ring_pts, band = ring_centerline(paths[0], curve_steps)

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" viewBox="{vb}">',
             '  <g fill="none" stroke-linecap="round" stroke-linejoin="round">']
    rd = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in ring_pts)
    lines.append(f'    <path d="{rd}" stroke="{color}" stroke-width="{band:.1f}"/>')
    for s in strokes:
        if len(s) < 2:
            continue
        dd = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in s)
        lines.append(f'    <path d="{dd}" stroke="{color}" stroke-width="{width:.1f}"/>')
    lines += ["  </g>", "</svg>"]
    out.write_text("\n".join(lines))
    return width, band, len(strokes)


def main():
    ap = argparse.ArgumentParser(description="Vector sharp-tip reconstruction of a scribble-sun SVG.")
    ap.add_argument("input", type=Path)
    ap.add_argument("--output", "-o", type=Path)
    ap.add_argument("--curve-steps", type=int, default=24)
    ap.add_argument("--width-scale", type=float, default=1.08)
    a = ap.parse_args()
    out = a.output or a.input.with_name(f"{a.input.stem}-lines.svg")
    w, band, n = convert(a.input, out, a.curve_steps, a.width_scale)
    print(f"Wrote {out}  (scribble width={w:.1f}, ring band={band:.1f}, strokes={n})")


if __name__ == "__main__":
    main()
