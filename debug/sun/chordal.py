#!/usr/bin/env python3
"""Prototype: recover a stroke centerline from a filled outline in *vector*
space using a triangulation (chordal-axis) medial axis, so sharp zigzag tips
stay sharp.

Focus: the sun scribble (a single outlined pen stroke). Reads the SVG path
data directly rather than rasterizing, so the crisp corners survive.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import Delaunay
from shapely.geometry import Polygon, Point, LineString
from shapely import STRtree


# ----- minimal SVG path flattener (M L H V Q C A Z, absolute + relative) -----

def _tokenize(d: str):
    for m in re.finditer(r"[MmLlHhVvCcSsQqTtAaZz]|-?\d*\.?\d+(?:e-?\d+)?", d):
        yield m.group(0)


def flatten_path(d: str, curve_steps: int = 24) -> list[list[tuple[float, float]]]:
    """Return one list of (x, y) points per subpath."""
    toks = list(_tokenize(d))
    i = 0
    cx = cy = 0.0
    sx = sy = 0.0
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
        t = toks[i]
        if re.match(r"[A-Za-z]", t):
            cmd = t
            i += 1
        rel = cmd.islower()
        c = cmd.upper()

        if c == "M":
            x = num() + (cx if rel else 0)
            y = num() + (cy if rel else 0)
            if cur:
                subpaths.append(cur)
            cur = [(x, y)]
            cx, cy, sx, sy = x, y, x, y
            cmd = "l" if rel else "L"
            prev_ctrl = None
        elif c == "L":
            x = num() + (cx if rel else 0)
            y = num() + (cy if rel else 0)
            cur.append((x, y))
            cx, cy = x, y
            prev_ctrl = None
        elif c == "H":
            x = num() + (cx if rel else 0)
            cur.append((x, cy))
            cx = x
            prev_ctrl = None
        elif c == "V":
            y = num() + (cy if rel else 0)
            cur.append((cx, y))
            cy = y
            prev_ctrl = None
        elif c in ("Q", "T"):
            if c == "Q":
                x1 = num() + (cx if rel else 0)
                y1 = num() + (cy if rel else 0)
            else:
                if prev_ctrl:
                    x1 = 2 * cx - prev_ctrl[0]
                    y1 = 2 * cy - prev_ctrl[1]
                else:
                    x1, y1 = cx, cy
            x = num() + (cx if rel else 0)
            y = num() + (cy if rel else 0)
            for s in range(1, curve_steps + 1):
                u = s / curve_steps
                mt = 1 - u
                bx = mt * mt * cx + 2 * mt * u * x1 + u * u * x
                by = mt * mt * cy + 2 * mt * u * y1 + u * u * y
                cur.append((bx, by))
            prev_ctrl = (x1, y1)
            cx, cy = x, y
        elif c in ("C", "S"):
            if c == "C":
                x1 = num() + (cx if rel else 0)
                y1 = num() + (cy if rel else 0)
            else:
                if prev_ctrl:
                    x1 = 2 * cx - prev_ctrl[0]
                    y1 = 2 * cy - prev_ctrl[1]
                else:
                    x1, y1 = cx, cy
            x2 = num() + (cx if rel else 0)
            y2 = num() + (cy if rel else 0)
            x = num() + (cx if rel else 0)
            y = num() + (cy if rel else 0)
            for s in range(1, curve_steps + 1):
                u = s / curve_steps
                mt = 1 - u
                bx = mt**3 * cx + 3 * mt**2 * u * x1 + 3 * mt * u**2 * x2 + u**3 * x
                by = mt**3 * cy + 3 * mt**2 * u * y1 + 3 * mt * u**2 * y2 + u**3 * y
                cur.append((bx, by))
            prev_ctrl = (x2, y2)
            cx, cy = x, y
        elif c == "A":
            rx = num()
            ry = num()
            phi = math.radians(num())
            large = num()
            sweep = num()
            x = num() + (cx if rel else 0)
            y = num() + (cy if rel else 0)
            for px, py in _arc(cx, cy, rx, ry, phi, large, sweep, x, y, curve_steps):
                cur.append((px, py))
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
    dx = (x0 - x) / 2
    dy = (y0 - y) / 2
    x1p = cosp * dx + sinp * dy
    y1p = -sinp * dx + cosp * dy
    rx, ry = abs(rx), abs(ry)
    lam = (x1p / rx) ** 2 + (y1p / ry) ** 2
    if lam > 1:
        s = math.sqrt(lam)
        rx *= s
        ry *= s
    num_ = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
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
        if ux * vy - uy * vx < 0:
            a = -a
        return a

    th1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dth = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dth > 0:
        dth -= 2 * math.pi
    elif sweep and dth < 0:
        dth += 2 * math.pi
    pts = []
    for s in range(1, steps + 1):
        th = th1 + dth * s / steps
        ex = cosp * rx * math.cos(th) - sinp * ry * math.sin(th) + cxc
        ey = sinp * rx * math.cos(th) + cosp * ry * math.sin(th) + cyc
        pts.append((ex, ey))
    return pts


# ----------------------------- chordal axis -----------------------------

def resample_ring(pts: list[tuple[float, float]], step: float) -> np.ndarray:
    p = np.array(pts, dtype=float)
    if np.allclose(p[0], p[-1]):
        p = p[:-1]
    seg = np.diff(np.vstack([p, p[:1]]), axis=0)
    seglen = np.hypot(seg[:, 0], seg[:, 1])
    out = []
    for k in range(len(p)):
        a = p[k]
        b = p[(k + 1) % len(p)]
        L = seglen[k]
        n = max(1, int(round(L / step)))
        for j in range(n):
            out.append(a + (b - a) * (j / n))
    return np.array(out)


def chordal_axis(ring: np.ndarray, poly: Polygon):
    """Return (axis_nodes dict pt->id, edges list, width_at, tips list)."""
    n = len(ring)
    tri = Delaunay(ring)
    # keep triangles inside the polygon
    keep = []
    for t in tri.simplices:
        c = ring[t].mean(axis=0)
        if poly.contains(Point(c)):
            keep.append(t)

    def is_boundary(i, j):
        return abs(i - j) == 1 or abs(i - j) == n - 1

    def mid(i, j):
        return tuple((ring[i] + ring[j]) / 2)

    seg = []  # list of (ptA, ptB)
    tips = []  # list of (tip_pt, inward_dir)
    for t in keep:
        e = [(t[0], t[1]), (t[1], t[2]), (t[2], t[0])]
        bflag = [is_boundary(i, j) for i, j in e]
        nb = sum(bflag)
        if nb == 3:
            continue  # degenerate sliver, skip
        if nb == 2:
            # terminal: shared vertex of the two boundary edges = tip corner
            internal = e[bflag.index(False)]
            apex = list({t[0], t[1], t[2]} - set(internal))[0]
            m = mid(*internal)
            tip = tuple(ring[apex])
            seg.append((m, tip))
            d = np.array(m) - np.array(tip)
            d = d / (np.hypot(*d) or 1)
            tips.append((tip, tuple(d)))
        elif nb == 1:
            internals = [e[k] for k in range(3) if not bflag[k]]
            seg.append((mid(*internals[0]), mid(*internals[1])))
        else:
            cen = tuple(ring[t].mean(axis=0))
            for i, j in e:
                seg.append((cen, mid(i, j)))
    return seg, tips


def build_polylines(seg):
    from collections import defaultdict
    key = lambda p: (round(p[0], 3), round(p[1], 3))
    adj = defaultdict(list)
    pts = {}
    for a, b in seg:
        ka, kb = key(a), key(b)
        pts[ka] = a
        pts[kb] = b
        adj[ka].append(kb)
        adj[kb].append(ka)
    used = set()

    def ekey(a, b):
        return (a, b) if a <= b else (b, a)

    lines = []
    # start from degree-1 nodes
    starts = [k for k in adj if len(adj[k]) == 1] or list(adj.keys())
    for s in starts:
        for nb in adj[s]:
            if ekey(s, nb) in used:
                continue
            line = [pts[s]]
            prev, cur = s, nb
            used.add(ekey(prev, cur))
            line.append(pts[cur])
            while True:
                nxts = [q for q in adj[cur] if ekey(cur, q) not in used]
                if len(nxts) != 1:
                    break
                nq = nxts[0]
                used.add(ekey(cur, nq))
                line.append(pts[nq])
                prev, cur = cur, nq
                if len(adj[cur]) != 2:
                    break
            lines.append(line)
    # any leftover edges (loops)
    for a, b in seg:
        ka, kb = key(a), key(b)
        if ekey(ka, kb) not in used:
            used.add(ekey(ka, kb))
            lines.append([pts[ka], pts[kb]])
    return lines


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "inputs/sun-5.svg"
    txt = Path(src).read_text()
    vb = list(map(float, re.split(r"[\s,]+", re.search(r'viewBox="([^"]+)"', txt).group(1).strip())))
    paths = re.findall(r'<path\b[^>]*\bd="([^"]*)"', txt, re.S)
    fills = re.findall(r'<path\b[^>]*\bfill="(#[0-9A-Fa-f]{6})"', txt, re.S)
    # scribble = the path with a single subpath (the ring has two)
    scribble_idx = 1
    subs = flatten_path(paths[scribble_idx])
    poly = Polygon(subs[0]).buffer(0)
    ring = resample_ring(subs[0], step=2.0)

    seg, tips = chordal_axis(ring, poly if poly.geom_type == "Polygon" else max(poly.geoms, key=lambda g: g.area))
    lines = build_polylines(seg)
    print(f"{src}: outline pts={len(ring)}, axis segs={len(seg)}, tips={len(tips)}, polylines={len(lines)}")

    # stroke width estimate: 2 * median distance from axis midpoints to boundary
    ext = poly.exterior if poly.geom_type == "Polygon" else max(poly.geoms, key=lambda g: g.area).exterior
    dists = []
    for a, b in seg:
        m = Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        dists.append(ext.distance(m))
    width = 2 * float(np.median(dists))
    print(f"  estimated width = {width:.1f}")

    # emit an overlay SVG: outline (gray) + centerline (red) + tips (blue dots)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb[0]} {vb[1]} {vb[2]} {vb[3]}">']
    dstr = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in subs[0]) + " Z"
    out.append(f'<path d="{dstr}" fill="#eee" stroke="#bbb" stroke-width="0.5"/>')
    for line in lines:
        d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in line)
        out.append(f'<path d="{d}" fill="none" stroke="red" stroke-width="0.8"/>')
    for (tx, ty), _ in tips:
        out.append(f'<circle cx="{tx:.1f}" cy="{ty:.1f}" r="1.6" fill="blue"/>')
    out.append("</svg>")
    Path("debug/sun/chordal-overlay.svg").write_text("\n".join(out))
    print("  wrote debug/sun/chordal-overlay.svg")


if __name__ == "__main__":
    main()
