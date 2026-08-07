"""Synthetic ground-truth corpus (Common Setup Sec 12.1) for the polygon-Voronoi track.

Every case is generated *from a known centerline*, so true centerline error is
measurable rather than only reconstruction error.

Design decision that matters for this track specifically: wherever the stroke
outline is analytically expressible with real SVG curve commands, it is emitted
that way (lines + ``A`` arcs + cubics), NOT as a pre-flattened polygon.  That is
what makes the flattening-tolerance sweep meaningful -- a corpus of dense
polygons would make tolerance a no-op.  The cases that are genuinely boolean
unions (crossings, junctions, self-overlap) and the deliberately-noisy case are
emitted as polygons, because that is what such artwork really is; those cases
are marked ``curve_native: false`` in the manifest.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import unary_union

# --------------------------------------------------------------------------
# centerline primitives
# --------------------------------------------------------------------------


@dataclass
class Lin:
    p0: tuple[float, float]
    p1: tuple[float, float]

    def start(self):
        return self.p0

    def end(self):
        return self.p1

    def tangent0(self):
        return _unit(self.p1[0] - self.p0[0], self.p1[1] - self.p0[1])

    def tangent1(self):
        return self.tangent0()

    def sample(self, n):
        t = np.linspace(0, 1, n)
        return np.stack([self.p0[0] + t * (self.p1[0] - self.p0[0]),
                         self.p0[1] + t * (self.p1[1] - self.p0[1])], axis=1)

    def length(self):
        return math.hypot(self.p1[0] - self.p0[0], self.p1[1] - self.p0[1])


@dataclass
class Arc:
    """Circular arc; angles in radians, screen coords (y down)."""

    c: tuple[float, float]
    r: float
    a0: float
    a1: float

    def _pt(self, a):
        return (self.c[0] + self.r * math.cos(a), self.c[1] + self.r * math.sin(a))

    def start(self):
        return self._pt(self.a0)

    def end(self):
        return self._pt(self.a1)

    def _tan(self, a):
        s = 1.0 if self.a1 > self.a0 else -1.0
        return _unit(-math.sin(a) * s, math.cos(a) * s)

    def tangent0(self):
        return self._tan(self.a0)

    def tangent1(self):
        return self._tan(self.a1)

    def sample(self, n):
        a = np.linspace(self.a0, self.a1, n)
        return np.stack([self.c[0] + self.r * np.cos(a), self.c[1] + self.r * np.sin(a)], axis=1)

    def length(self):
        return abs(self.a1 - self.a0) * self.r


def _unit(x, y):
    n = math.hypot(x, y)
    return (x / n, y / n) if n else (0.0, 0.0)


def _left(d):
    return (-d[1], d[0])


# --------------------------------------------------------------------------
# exact stroke outline in SVG path syntax
# --------------------------------------------------------------------------


def _fmt(p):
    return f"{p[0]:.6f} {p[1]:.6f}"


def _arc_cmd(r, target, sweep, large=0):
    return f"A {r:.6f} {r:.6f} 0 {large} {sweep} {_fmt(target)}"


def _offset_side(seg, h, s):
    """Return (start_point, end_point, svg_command_generator) for one offset side."""
    if isinstance(seg, Lin):
        n = _left(seg.tangent0())
        a = (seg.p0[0] + s * n[0] * h, seg.p0[1] + s * n[1] * h)
        b = (seg.p1[0] + s * n[0] * h, seg.p1[1] + s * n[1] * h)
        return a, b, lambda tgt: f"L {_fmt(tgt)}"
    # Arc: left normal points inward when sweeping with increasing angle.
    inc = seg.a1 > seg.a0
    ro = seg.r + (-s * h if inc else s * h)
    sub = Arc(seg.c, ro, seg.a0, seg.a1)
    sweep = 1 if inc else 0
    large = 1 if abs(seg.a1 - seg.a0) > math.pi else 0
    return sub.start(), sub.end(), (lambda tgt, ro=ro, sw=sweep, lg=large: _arc_cmd(ro, tgt, sw, lg))


def _reverse_side(seg, h, s):
    """Same offset side but traversed backwards."""
    if isinstance(seg, Lin):
        n = _left(seg.tangent0())
        a = (seg.p1[0] + s * n[0] * h, seg.p1[1] + s * n[1] * h)
        b = (seg.p0[0] + s * n[0] * h, seg.p0[1] + s * n[1] * h)
        return a, b, lambda tgt: f"L {_fmt(tgt)}"
    inc = seg.a1 > seg.a0
    ro = seg.r + (-s * h if inc else s * h)
    sub = Arc(seg.c, ro, seg.a1, seg.a0)
    sweep = 1 if sub.a1 > sub.a0 else 0
    large = 1 if abs(seg.a1 - seg.a0) > math.pi else 0
    return sub.start(), sub.end(), (lambda tgt, ro=ro, sw=sweep, lg=large: _arc_cmd(ro, tgt, sw, lg))


def _line_intersect(p, d, q, e):
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-12:
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return (p[0] + t * d[0], p[1] + t * d[1])


def stroke_outline_path(segs, width, cap="round", join="round") -> str:
    """Exact stroke outline of a centerline chain as an SVG path 'd' string."""
    h = width / 2.0
    closed = _close_enough(segs[0].start(), segs[-1].end())
    cmds: list[str] = []

    def walk(side_segs, s, reverse):
        """Emit one offset side as [('M', pt)] + [('C', cmd)]...

        Inner joins TRIM the previous segment: the intersection of the two offset
        lines replaces the previous segment's endpoint.  Appending it instead
        would leave a zero-area backtrack spike and an invalid ring.
        """
        ops: list = []
        segops: list[dict] = []
        prev_end = None
        for i, seg in enumerate(side_segs):
            a, b, gen = (_reverse_side(seg, h, s) if reverse else _offset_side(seg, h, s))
            if prev_end is None:
                ops.append(["M", a])
            else:
                extra, trim = _join_cmds(side_segs, i, s, h, prev_end, a, join, reverse)
                if trim is not None and segops:
                    segops[-1]["end"] = trim
                ops.extend(["C", c] for c in extra)
            op = {"gen": gen, "end": b}
            segops.append(op)
            ops.append(op)
            prev_end = b
        flat = []
        for o in ops:
            if isinstance(o, dict):
                flat.append(["C", o["gen"](o["end"])])
            else:
                flat.append(o)
        return flat

    left_ops = walk(segs, +1, False)
    right_ops = walk(list(reversed(segs)), -1, True)

    cmds.append(f"M {_fmt(left_ops[0][1])}")
    for kind, val in left_ops[1:]:
        cmds.append(val)

    if closed:
        cmds.append("Z")
        cmds.append(f"M {_fmt(right_ops[0][1])}")
        for kind, val in right_ops[1:]:
            cmds.append(val)
        cmds.append("Z")
        return " ".join(cmds)

    # end cap: from left-side end to right-side start
    end_pt = segs[-1].end()
    d_end = segs[-1].tangent1()
    cmds.extend(_cap_cmds(end_pt, d_end, h, cap))
    for kind, val in right_ops[1:]:
        cmds.append(val)
    # start cap
    start_pt = segs[0].start()
    d_start = segs[0].tangent0()
    cmds.extend(_cap_cmds(start_pt, (-d_start[0], -d_start[1]), h, cap))
    cmds.append("Z")
    return " ".join(cmds)


def _cap_cmds(p, d, h, cap):
    n = _left(d)
    a = (p[0] + n[0] * h, p[1] + n[1] * h)
    b = (p[0] - n[0] * h, p[1] - n[1] * h)
    if cap == "round":
        return [_arc_cmd(h, b, 0, 0)]
    if cap == "square":
        a2 = (a[0] + d[0] * h, a[1] + d[1] * h)
        b2 = (b[0] + d[0] * h, b[1] + d[1] * h)
        return [f"L {_fmt(a2)}", f"L {_fmt(b2)}", f"L {_fmt(b)}"]
    return [f"L {_fmt(b)}"]  # butt


def _join_cmds(segs, i, s, h, prev_end, next_start, join, reverse):
    """Geometry connecting two consecutive offset segments at an interior vertex.

    ``_left()`` returns ``(-dy, dx)``; in SVG's y-down screen space that is the
    *right* hand of travel, so with a positive cross product (a clockwise turn on
    screen) the outer side is ``s = -1``.  Hence ``outer <=> s * cross < 0``.
    """
    prev_seg, cur_seg = segs[i - 1], segs[i]
    # Directions of travel along this walk (used for the offset-line intersection).
    t_prev = prev_seg.tangent1() if not reverse else _neg(prev_seg.tangent0())
    t_cur = cur_seg.tangent0() if not reverse else _neg(cur_seg.tangent1())
    # Forward-ordered pair, so inner/outer does not depend on walk direction.
    fa, fb = (cur_seg, prev_seg) if reverse else (prev_seg, cur_seg)
    d1, d2 = fa.tangent1(), fb.tangent0()
    cross = d1[0] * d2[1] - d1[1] * d2[0]
    if _close_enough(prev_end, next_start) or abs(cross) < 1e-9:
        return [], None  # tangent-continuous: offsets already meet

    if s * cross < 0:  # outer side -> apply the join style
        if join == "round":
            sweep = int((cross > 0) != bool(reverse))
            return [_arc_cmd(h, next_start, sweep, 0)], None
        if join == "miter":
            m = _line_intersect(prev_end, t_prev, next_start, t_cur)
            if m is not None:
                return [f"L {_fmt(m)}", f"L {_fmt(next_start)}"], None
        return [f"L {_fmt(next_start)}"], None  # bevel
    # Inner side: the two offsets cross, so the intersection point IS the shared
    # vertex -- trim the previous segment to it rather than appending.
    m = _line_intersect(prev_end, t_prev, next_start, t_cur)
    if m is None:
        return [f"L {_fmt(next_start)}"], None
    return [], m


def _neg(d):
    return (-d[0], -d[1])


def _close_enough(a, b, eps=1e-7):
    return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps


# --------------------------------------------------------------------------
# case definitions
# --------------------------------------------------------------------------


@dataclass
class Case:
    num: int
    name: str
    width: float
    strokes: list = field(default_factory=list)   # list[list[seg]]
    caps: str = "round"
    join: str = "round"
    curve_native: bool = True
    union: bool = False           # emit as one boolean-unioned polygon
    separate: bool = False        # emit one SVG element per stroke
    note: str = ""
    builder: object = None        # optional custom polygon builder


W = 24.0
CANVAS = (600, 600)


def _capsule(p0, p1):
    return [Lin(p0, p1)]


def _cases() -> list[Case]:
    cs: list[Case] = []
    cs.append(Case(1, "line", W, [_capsule((100, 300), (500, 300))]))
    cs.append(Case(2, "diagonal", W, [_capsule((110, 110), (480, 460))]))
    cs.append(Case(3, "arc", W, [[Arc((300, 380), 200, math.radians(200), math.radians(340))]]))

    # S curve: two tangent circular arcs of opposite curvature
    r = 120.0
    s1 = Arc((180, 300), r, math.radians(180), math.radians(0))     # decreasing: bulges down
    s2 = Arc((420, 300), r, math.radians(180), math.radians(360))   # increasing: bulges up
    cs.append(Case(4, "s-curve", W, [[s1, s2]]))

    # Tight U: small radius half-turn with straight legs
    ur = 45.0
    cs.append(Case(5, "u-tight", W, [[
        Lin((240, 120), (240, 360)),
        Arc((285, 360), ur, math.radians(180), math.radians(0)),
        Lin((330, 360), (330, 120)),
    ]]))

    cs.append(Case(6, "loop", W, [[Arc((300, 300), 170, 0.0, math.pi),
                                   Arc((300, 300), 170, math.pi, 2 * math.pi)]]))

    cs.append(Case(7, "cap-round", 40.0, [_capsule((140, 300), (460, 300))], caps="round"))
    cs.append(Case(8, "cap-butt", 40.0, [_capsule((140, 300), (460, 300))], caps="butt"))
    cs.append(Case(9, "cap-square", 40.0, [_capsule((140, 300), (460, 300))], caps="square"))

    elbow = [Lin((150, 150), (450, 150)), Lin((450, 150), (450, 450))]
    cs.append(Case(10, "join-round", 40.0, [elbow], join="round"))
    cs.append(Case(11, "join-bevel", 40.0, [elbow], join="bevel"))
    cs.append(Case(12, "join-miter", 40.0, [elbow], join="miter"))

    x1 = _capsule((130, 130), (470, 470))
    x2 = _capsule((470, 130), (130, 470))
    cs.append(Case(13, "x-separate", W, [x1, x2], separate=True,
                   note="two overlapping elements kept separate"))
    cs.append(Case(14, "x-union", W, [x1, x2], union=True, curve_native=False,
                   note="boolean union; boundary is polygonal by construction"))

    t1 = _capsule((120, 200), (480, 200))
    t2 = _capsule((300, 200), (300, 480))
    cs.append(Case(15, "t-junction", W, [t1, t2], union=True, curve_native=False))

    y1 = _capsule((300, 480), (300, 300))
    y2 = _capsule((300, 300), (160, 140))
    y3 = _capsule((300, 300), (440, 140))
    cs.append(Case(16, "y-junction", W, [y1, y2, y3], union=True, curve_native=False))

    gap = 2.0
    off = W / 2 + gap / 2
    cs.append(Case(17, "parallel-near", W,
                   [_capsule((120, 300 - off), (480, 300 - off)),
                    _capsule((120, 300 + off), (480, 300 + off))],
                   separate=False, union=True, curve_native=False,
                   note=f"two parallel strokes separated by a {gap}px gap"))

    cs.append(Case(18, "self-overlap", W, [[
        Lin((180, 420), (180, 200)),
        Arc((250, 200), 70, math.radians(180), math.radians(360)),
        Lin((320, 200), (320, 300)),
        Lin((320, 300), (150, 300)),
    ]], union=True, curve_native=False, note="hook that crosses its own earlier leg"))

    cs.append(Case(19, "variable-width", 0.0, [], curve_native=True,
                   builder="variable", note="width tapers 40 -> 12"))
    cs.append(Case(20, "noisy-boundary", W, [_capsule((110, 300), (490, 300))],
                   curve_native=False, builder="noisy",
                   note="capsule boundary perturbed to mimic vectorization noise"))
    return cs


# --------------------------------------------------------------------------
# emission
# --------------------------------------------------------------------------


def _polygon_from_stroke(segs, width, cap="round", join="round", quad=64):
    pts = _sample_chain(segs, per_unit=1.5)
    ls = LineString(pts)
    cs = {"round": 1, "butt": 2, "square": 3}[cap]
    js = {"round": 1, "miter": 2, "bevel": 3}[join]
    return ls.buffer(width / 2.0, cap_style=cs, join_style=js, quad_segs=quad)


def _sample_chain(segs, per_unit=1.0):
    pts: list[tuple[float, float]] = []
    for seg in segs:
        n = max(2, int(seg.length() * per_unit) + 2)
        s = seg.sample(n)
        if pts and _close_enough(tuple(s[0]), pts[-1], 1e-6):
            s = s[1:]
        pts.extend([tuple(p) for p in s])
    return pts


def _variable_width_case():
    """Tapered stroke built from cubic side curves; ground truth is the axis."""
    p0, p1 = (120.0, 300.0), (480.0, 300.0)
    w0, w1 = 40.0, 12.0
    n = 400
    t = np.linspace(0, 1, n)
    x = p0[0] + t * (p1[0] - p0[0])
    y = np.full_like(x, p0[1])
    w = w0 + t * (w1 - w0)
    top = np.stack([x, y - w / 2], axis=1)
    bot = np.stack([x, y + w / 2], axis=1)
    ring = list(map(tuple, top)) + list(map(tuple, bot[::-1]))
    poly = Polygon(ring).buffer(0)
    axis = np.stack([x, y], axis=1)
    return poly, axis, w


def _noisy_case(segs, width, rng):
    poly = _polygon_from_stroke(segs, width, quad=32)
    ring = np.array(poly.exterior.coords)
    c = np.array(poly.centroid.coords[0])
    v = ring - c
    nrm = np.linalg.norm(v, axis=1, keepdims=True)
    nrm[nrm == 0] = 1
    noise = rng.normal(0.0, 0.45, size=(len(ring), 1))
    noise[-1] = noise[0]
    out = ring + (v / nrm) * noise
    p = Polygon(out)
    if not p.is_valid:
        p = p.buffer(0)
    return p


def _svg(paths: list[tuple[str, str]], size=CANVAS) -> str:
    body = "\n".join(
        f'  <path fill="{fill}" fill-rule="evenodd" d="{d}"/>' for d, fill in paths
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'viewBox="0 0 {size[0]} {size[1]}" width="{size[0]}" height="{size[1]}">\n'
        f'{body}\n</svg>\n'
    )


def _poly_to_d(geom) -> str:
    polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    parts = []
    for p in polys:
        for ring in [p.exterior, *p.interiors]:
            cs = list(ring.coords)
            parts.append("M " + " L ".join(f"{x:.4f} {y:.4f}" for x, y in cs) + " Z")
    return " ".join(parts)


FILL = "#222222"


def generate(outdir: str, seed: int = 7) -> list[dict]:
    os.makedirs(outdir, exist_ok=True)
    rng = np.random.default_rng(seed)
    manifest = []
    for case in _cases():
        name = f"{case.num:02d}-{case.name}"
        gt_lines: list[list[list[float]]] = []
        widths: list[float] = []

        if case.builder == "variable":
            poly, axis, wprof = _variable_width_case()
            d = _poly_to_d(poly)
            paths = [(d, FILL)]
            gt_lines.append(axis.tolist())
            widths.append(float(np.mean(wprof)))
            geom = poly
        elif case.builder == "noisy":
            poly = _noisy_case(case.strokes[0], case.width, rng)
            paths = [(_poly_to_d(poly), FILL)]
            gt_lines.append([list(map(float, p)) for p in _sample_chain(case.strokes[0], 1.0)])
            widths.append(case.width)
            geom = poly
        elif case.union:
            polys = [_polygon_from_stroke(s, case.width, case.caps, case.join) for s in case.strokes]
            geom = unary_union(polys)
            paths = [(_poly_to_d(geom), FILL)]
            for s in case.strokes:
                gt_lines.append([list(map(float, p)) for p in _sample_chain(s, 1.0)])
                widths.append(case.width)
        else:
            paths = []
            geoms = []
            for s in case.strokes:
                d = stroke_outline_path(s, case.width, case.caps, case.join)
                paths.append((d, FILL))
                geoms.append(_polygon_from_stroke(s, case.width, case.caps, case.join))
                gt_lines.append([list(map(float, p)) for p in _sample_chain(s, 1.0)])
                widths.append(case.width)
            geom = unary_union(geoms) if len(geoms) > 1 else geoms[0]
            if not case.separate:
                pass

        svg_path = os.path.join(outdir, f"{name}.svg")
        with open(svg_path, "w") as f:
            f.write(_svg(paths))

        entry = {
            "num": case.num,
            "name": case.name,
            "slug": name,
            "svg": os.path.relpath(svg_path),
            "width": case.width if case.width else float(np.mean(widths)),
            "curve_native": case.curve_native,
            "n_strokes": len(gt_lines),
            "elements": len(paths),
            "note": case.note,
            "centerlines": gt_lines,
            "reference_area": float(geom.area),
        }
        manifest.append(entry)

    with open(os.path.join(outdir, "manifest.json"), "w") as f:
        json.dump(manifest, f)
    return manifest


if __name__ == "__main__":
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "debug/polygon-voronoi/synthetic"
    m = generate(out)
    for e in m:
        print(f"{e['num']:2d} {e['name']:16s} strokes={e['n_strokes']} "
              f"curve_native={e['curve_native']} area={e['reference_area']:.1f}")
