"""Synthetic ground-truth corpus (Common Setup §12.1) — the 20 cases.

Every case is built by *stroking a known centerline*: the centerline is sampled
as a dense polyline, buffered in Shapely with the requested cap/join style, and
the resulting polygon is written out as a filled SVG path. The source centerline
is kept alongside it, so these are the only inputs in the project where true
centerline error (not just reconstruction error) can be measured.

Written to `debug/opencv-tracing/corpus/`:
    case-NN-<name>.svg          the filled shape, one <path> per element
    manifest.json               ground-truth centerlines, widths, cap/join styles

Report §6.1 flags cases 7-9 and 13-16 as the highest-risk area for any backend;
this track's first target is 1-6 plus 13-16.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import unary_union

CANVAS = 300.0
BUFFER_RESOLUTION = 32          # quadrant segments; high, so the fill is smooth

CAP_STYLES = {"round": 1, "flat": 2, "square": 3}
JOIN_STYLES = {"round": 1, "mitre": 2, "bevel": 3}


def _sample(fn, t0, t1, n=200):
    ts = np.linspace(t0, t1, n)
    return np.array([fn(t) for t in ts])


def _line(p0, p1, n=2):
    return np.column_stack([np.linspace(p0[0], p1[0], n),
                            np.linspace(p0[1], p1[1], n)])


def _arc(cx, cy, r, a0_deg, a1_deg, n=200):
    a = np.radians(np.linspace(a0_deg, a1_deg, n))
    return np.column_stack([cx + r * np.cos(a), cy + r * np.sin(a)])


def _bezier(p0, p1, p2, p3, n=200):
    t = np.linspace(0, 1, n)[:, None]
    p0, p1, p2, p3 = map(np.asarray, (p0, p1, p2, p3))
    return ((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1
            + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3)


def _stroke(points, width, cap="round", join="round"):
    return LineString(points).buffer(width / 2.0, resolution=BUFFER_RESOLUTION,
                                     cap_style=CAP_STYLES[cap],
                                     join_style=JOIN_STYLES[join])


def _poly_to_d(geom) -> str:
    polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    parts = []
    for poly in polys:
        for ring in [poly.exterior, *poly.interiors]:
            coords = list(ring.coords)
            parts.append("M " + " L ".join(f"{x:.4f} {y:.4f}" for x, y in coords) + " Z")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# case definitions
# ---------------------------------------------------------------------------

def _cases():
    """Each case -> (name, [element, ...], note).

    An element is (centerline_points, width, cap, join) or, for shapes assembled
    by boolean union, ([(pts, w, cap, join), ...],) marked `union=True`.
    """
    W = 20.0
    cases = []

    # 1-6: pure geometry. A correct centerline here IS the source path.
    cases.append(("horizontal-line", [(_line((50, 150), (250, 150)), W, "round", "round")]))
    cases.append(("diagonal-line", [(_line((55, 60), (245, 240)), W, "round", "round")]))
    cases.append(("circular-arc", [(_arc(150, 170, 100, 200, 340), W, "round", "round")]))
    cases.append(("s-curve", [(_bezier((50, 240), (110, 60), (190, 240), (250, 60)),
                               W, "round", "round")]))
    cases.append(("tight-u-curve", [(np.vstack([
        _line((100, 60), (100, 170), 60),
        _arc(150, 170, 50, 180, 360)[1:],
        _line((200, 170), (200, 60), 60)[1:]]), W, "round", "round")]))
    loop = _arc(150, 150, 85, 0, 360)
    loop[-1] = loop[0]
    cases.append(("closed-loop", [(loop, W, "round", "round")]))

    # 7-9: caps.
    cases.append(("round-cap", [(_line((80, 150), (220, 150)), 34.0, "round", "round")]))
    cases.append(("butt-cap", [(_line((80, 150), (220, 150)), 34.0, "flat", "round")]))
    cases.append(("square-cap", [(_line((80, 150), (220, 150)), 34.0, "square", "round")]))

    # 10-12: joins, all a 90-degree corner so only the join style differs.
    corner = np.vstack([_line((70, 70), (70, 220), 60), _line((70, 220), (230, 220), 60)[1:]])
    cases.append(("round-join", [(corner, 30.0, "flat", "round")]))
    cases.append(("bevel-join", [(corner, 30.0, "flat", "bevel")]))
    cases.append(("miter-join", [(corner, 30.0, "flat", "mitre")]))

    # 13-16: junctions — this track's primary target.
    xa = _line((60, 60), (240, 240))
    xb = _line((240, 60), (60, 240))
    cases.append(("x-crossing-separate", [(xa, W, "round", "round"),
                                          (xb, W, "round", "round")]))
    cases.append(("x-crossing-union", [[(xa, W, "round", "round"),
                                        (xb, W, "round", "round")]]))
    ta = _line((50, 110), (250, 110))
    tb = _line((150, 110), (150, 250))
    cases.append(("t-junction", [[(ta, W, "round", "round"), (tb, W, "round", "round")]]))
    ya = _line((150, 250), (150, 160))
    yb = _line((150, 160), (70, 60))
    yc = _line((150, 160), (230, 60))
    cases.append(("y-junction", [[(ya, W, "round", "round"), (yb, W, "round", "round"),
                                  (yc, W, "round", "round")]]))

    # 17-20: the awkward ones.
    cases.append(("near-parallel", [(_line((50, 140), (250, 140)), W, "round", "round"),
                                    (_line((50, 163), (250, 163)), W, "round", "round")]))
    overlap = np.vstack([_line((70, 200), (150, 90), 60),
                         _arc(150, 130, 42, -90, 200)[1:],
                         _line(_arc(150, 130, 42, -90, 200)[-1], (110, 240), 40)[1:]])
    cases.append(("self-overlap", [[(overlap, W, "round", "round")]]))
    cases.append(("variable-width", [("variable", None, None, None)]))
    cases.append(("noisy-boundary", [("noisy", None, None, None)]))

    return cases


def _variable_width_shape():
    """Case 19: width ramps 8 -> 34 along a straight centerline."""
    pts = _line((60, 150), (240, 150), 400)
    radii = np.linspace(4.0, 17.0, len(pts))
    discs = [LineString([p, p]).buffer(r, resolution=BUFFER_RESOLUTION)
             for p, r in zip(pts, radii)]
    return unary_union(discs), pts


def _noisy_boundary_shape(seed=20200):
    """Case 20: an S curve whose boundary is perturbed like a vectorized trace."""
    pts = _bezier((60, 220), (120, 70), (190, 230), (240, 90))
    poly = _stroke(pts, 22.0)
    rng = np.random.default_rng(seed)
    coords = np.array(poly.exterior.coords)
    # A slow wobble plus per-vertex jitter: bumps big enough to spawn branches,
    # small enough that the true centerline is unchanged.
    phase = np.linspace(0, 14 * math.pi, len(coords))
    wobble = 0.9 * np.sin(phase) + rng.normal(0, 0.35, len(coords))
    centre = coords.mean(axis=0)
    vec = coords - centre
    vec /= np.maximum(np.linalg.norm(vec, axis=1, keepdims=True), 1e-9)
    noisy = coords + vec * wobble[:, None]
    noisy[-1] = noisy[0]
    return Polygon(noisy).buffer(0), pts


def build(out_dir: Path) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []

    for index, (name, elements) in enumerate(_cases(), start=1):
        svg_elements = []
        gt = []

        for element in elements:
            if isinstance(element, list):                       # boolean union
                geom = unary_union([_stroke(p, w, c, j) for p, w, c, j in element])
                svg_elements.append(geom)
                for p, w, _, _ in element:
                    gt.append({"points": np.asarray(p).tolist(), "width": w})
            elif isinstance(element[0], str) and element[0] == "variable":
                geom, pts = _variable_width_shape()
                svg_elements.append(geom)
                gt.append({"points": pts.tolist(), "width": None,
                           "widthProfile": [8.0, 34.0]})
            elif isinstance(element[0], str) and element[0] == "noisy":
                geom, pts = _noisy_boundary_shape()
                svg_elements.append(geom)
                gt.append({"points": pts.tolist(), "width": 22.0})
            else:
                pts, w, cap, join = element
                svg_elements.append(_stroke(pts, w, cap, join))
                gt.append({"points": np.asarray(pts).tolist(), "width": w})

        body = "\n".join(f'<path d="{_poly_to_d(g)}" fill="#222222" fill-rule="evenodd"/>'
                         for g in svg_elements)
        svg = ("\n".join([
            '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
            f'viewBox="0 0 {CANVAS:.0f} {CANVAS:.0f}">',
            body, "</svg>"]))

        stem = f"case-{index:02d}-{name}"
        (out_dir / f"{stem}.svg").write_text(svg)
        manifest.append({"index": index, "name": name, "file": f"{stem}.svg",
                         "elements": len(svg_elements),
                         "unioned": any(isinstance(e, list) for e in elements),
                         "groundTruth": gt})

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "debug/opencv-tracing/corpus")
    built = build(target)
    for case in built:
        print(f"{case['index']:2d}  {case['name']:<22} elements={case['elements']} "
              f"gt_paths={len(case['groundTruth'])}")
