#!/usr/bin/env python3
"""Held-out test of the pruning decision itself, with labelled ground truth.

The handoff's warning is that thresholds get fitted to the ten real inputs. This
corpus is generated from scratch and never derived from them, so it is a genuine
held-out check — and unlike the real ladder it labels every branch, so pruning can
be scored as a classifier rather than only through reconstruction error.

Construction, per case:

  * a TRUE centerline (line / arc / S / Y / T) at a known radius R;
  * zero or more REAL detail branches — short but genuine strokes, consistent
    width, that a good pruner must KEEP. These ARE in the source fill;
  * NOISE spurs of known normalized length L/(2R), tapering in radius the way a
    medial-axis branch off a boundary bump does. These are NOT in the source fill.

The source SVG is the exact Shapely buffer of (true centerline + real branches),
so the only thing pruning has to discover is which branches are noise.

    python3 experiments/pruning-scoring/synthprune.py
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shapely.geometry import LineString, Point  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from clg import CenterlineGraph, geom, prune, svgio  # noqa: E402
from clg.graph import Edge, Node  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "debug" / "pruning-scoring" / "synthetic"

R_DEFAULT = 12.0
CANVAS = (0.0, 0.0, 900.0, 700.0)


def _line(n=60):
    return [(120.0 + i * (660.0 / n), 350.0) for i in range(n + 1)]


def _arc(n=90):
    return [
        (450.0 + 260.0 * math.cos(math.pi * (0.15 + 0.7 * i / n)),
         420.0 - 260.0 * math.sin(math.pi * (0.15 + 0.7 * i / n)))
        for i in range(n + 1)
    ]


def _s_curve(n=120):
    return [
        (120.0 + i * (660.0 / n), 350.0 + 140.0 * math.sin(2 * math.pi * i / n))
        for i in range(n + 1)
    ]


def _y_junction():
    stem = [(450.0, 640.0 - i * 8.0) for i in range(31)]        # up to (450, 400)
    left = [(450.0 - i * 6.0, 400.0 - i * 7.0) for i in range(31)]
    right = [(450.0 + i * 6.0, 400.0 - i * 7.0) for i in range(31)]
    return [stem, left, right]


def _t_junction():
    bar = [(120.0 + i * 11.0, 260.0) for i in range(61)]
    stem = [(450.0, 260.0 + i * 6.0) for i in range(51)]
    return [bar, stem]


SHAPES = {
    "line": lambda: [_line()],
    "arc": lambda: [_arc()],
    "s-curve": lambda: [_s_curve()],
    "y-junction": _y_junction,
    "t-junction": _t_junction,
}


def _perp(pts, i):
    a = pts[max(0, i - 1)]
    b = pts[min(len(pts) - 1, i + 1)]
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1.0
    return (-dy / n, dx / n)


def _spur(base, direction, length, r_base, *, taper=0.25, steps=8, jitter=0.0, rng=None):
    """A noise spur: leaves `base` along `direction`, radius tapering to `taper * r_base`."""
    pts, radii = [base], [r_base]
    dx, dy = direction
    for k in range(1, steps + 1):
        t = k / steps
        if jitter and rng:
            ang = rng.uniform(-jitter, jitter)
            c, s = math.cos(ang), math.sin(ang)
            dx, dy = dx * c - dy * s, dx * s + dy * c
        pts.append((base[0] + dx * length * t, base[1] + dy * length * t))
        radii.append(r_base * (1.0 - (1.0 - taper) * t))
    return pts, radii


def build_case(name: str, *, radius: float = R_DEFAULT, n_spurs: int = 14,
               n_real: int = 2, seed: int = 0) -> dict:
    rng = random.Random(seed)
    true_polys = SHAPES[name]()

    g = CenterlineGraph(image=f"synthprune-{name}", backend="synthetic-truth",
                        units="svg-user", view_box=list(CANVAS), radius_source="native")
    labels: dict[str, str] = {}
    spur_norm: dict[str, float] = {}   # designed length in stroke widths, per spur
    nid = [0]
    eid = [0]

    def add_node(p, r):
        nid[0] += 1
        n = Node(id=f"n{nid[0]}", x=p[0], y=p[1], radius=r)
        g.nodes[n.id] = n
        return n.id

    def add_edge(pts, radii, label, a=None, b=None):
        eid[0] += 1
        a = a or add_node(pts[0], radii[0])
        b = b or add_node(pts[-1], radii[-1])
        e = Edge(id=f"e{eid[0]}", frm=a, to=b, points=list(pts),
                 length=geom.polyline_length(pts), median_radius=geom.median(radii),
                 radius_profile=list(radii), source_element_id="synthetic")
        g.edges[e.id] = e
        labels[e.id] = label
        return e.id

    # --- the true centerline, plus shared nodes where sub-paths meet
    shared: dict[tuple[float, float], str] = {}

    def node_at(p, r):
        key = (round(p[0], 3), round(p[1], 3))
        if key not in shared:
            shared[key] = add_node(p, r)
        return shared[key]

    # --- decide where branches attach BEFORE building the trunk, so the trunk can
    #     be split at those vertices. A branch hanging off a coincident-but-separate
    #     node is not a branch at all: it is an isolated stroke, and none of the
    #     junction features (R_parent, continuation angle) would ever be exercised.
    attach: dict[int, list[dict]] = {}
    for k in range(n_real):
        host_i = 0
        poly = true_polys[host_i]
        i = int(len(poly) * (0.3 + 0.4 * (k + 1) / (n_real + 1)))
        attach.setdefault(host_i, []).append({"i": i, "kind": "real", "k": k})
    for k in range(n_spurs):
        host_i = k % len(true_polys)
        poly = true_polys[host_i]
        attach.setdefault(host_i, []).append(
            {"i": rng.randrange(4, len(poly) - 4), "kind": "noise", "k": k}
        )

    true_lines = []
    for host_i, poly in enumerate(true_polys):
        radii = [radius] * len(poly)
        cuts = sorted({a["i"] for a in attach.get(host_i, [])} | {0, len(poly) - 1})
        for lo, hi in zip(cuts[:-1], cuts[1:]):
            if hi - lo < 1:
                continue
            seg = poly[lo:hi + 1]
            add_edge(seg, radii[lo:hi + 1], "true",
                     a=node_at(poly[lo], radius), b=node_at(poly[hi], radius))
        true_lines.append(LineString(poly))

    for host_i, items in attach.items():
        poly = true_polys[host_i]
        for item in items:
            i = item["i"]
            base = poly[i]
            d = _perp(poly, i)
            if item["kind"] == "real":
                if item["k"] % 2:
                    d = (-d[0], -d[1])
                # 2.5-4 stroke widths at full parent width: genuine detail, must stay
                length = radius * 2 * rng.uniform(2.5, 4.0)
                pts = [(base[0] + d[0] * length * t / 10, base[1] + d[1] * length * t / 10)
                       for t in range(11)]
                add_edge(pts, [radius] * len(pts), "real", a=node_at(base, radius))
                true_lines.append(LineString(pts))
            else:
                if rng.random() < 0.5:
                    d = (-d[0], -d[1])
                ang = rng.uniform(-0.6, 0.6)
                c, s = math.cos(ang), math.sin(ang)
                d = (d[0] * c - d[1] * s, d[0] * s + d[1] * c)
                norm_len = rng.choice([0.08, 0.15, 0.25, 0.4, 0.6, 0.8, 1.0, 1.3])
                pts, radii_s = _spur(base, d, norm_len * 2 * radius, radius,
                                     taper=rng.uniform(0.15, 0.45), jitter=0.25, rng=rng)
                e = add_edge(pts, radii_s, "noise", a=node_at(base, radius))
                spur_norm[e] = norm_len

    fill = unary_union([ln.buffer(radius, quad_segs=24, cap_style=1, join_style=1)
                        for ln in true_lines])
    return {"name": name, "graph": g, "labels": labels, "fill": fill,
            "radius": radius, "spurNorm": spur_norm}


def write_case(case: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    svg_path = OUT / f"{case['name']}.svg"
    vb = CANVAS
    d = svgio.polygon_to_path_d(case["fill"])
    svg_path.write_text(
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'viewBox="{vb[0]:.2f} {vb[1]:.2f} {vb[2]:.2f} {vb[3]:.2f}">'
        f'<path d="{d}" fill="#1a1a1a" fill-rule="evenodd"/></svg>'
    )
    case["graph"].source = str(svg_path.relative_to(REPO))
    case["graph"].save(OUT / f"{case['name']}.raw.json")
    (OUT / f"{case['name']}.labels.json").write_text(json.dumps(case["labels"], indent=1))
    return svg_path


def evaluate(case: dict, lambdas) -> list[dict]:
    """Score pruning as a classifier at each strength."""
    labels = case["labels"]
    n_noise = sum(1 for v in labels.values() if v == "noise")
    n_keep = sum(1 for v in labels.values() if v != "noise")
    rows = []
    for lam in lambdas:
        pruned, info = prune.prune(case["graph"], lam)
        # Survival is tested GEOMETRICALLY, not by edge id: canonicalization merges
        # the trunk segments into one edge and the merged edge keeps only the first
        # id, so an id-membership test would score every spliced trunk piece as
        # "deleted". A branch survived if its far end is still covered by geometry.
        alive = _alive_by_geometry(pruned, case)
        removed_noise = sum(1 for eid, lab in labels.items()
                            if lab == "noise" and eid not in alive)
        removed_keep = sum(1 for eid, lab in labels.items()
                           if lab != "noise" and eid not in alive)
        rows.append({
            "lam": lam,
            "noiseRemoved": removed_noise,
            "noiseTotal": n_noise,
            "realRemoved": removed_keep,
            "realTotal": n_keep,
            "recall": removed_noise / n_noise if n_noise else 1.0,
            "realSurvival": 1.0 - (removed_keep / n_keep if n_keep else 0.0),
            "edges": len(pruned.edges),
            "byLength": _recall_by_length(case, alive),
        })
    return rows


def _alive_by_geometry(pruned, case: dict) -> set:
    """Which labelled branches survived, by exact merge provenance.

    An id-membership test alone is wrong (canonicalization splices trunk segments
    together and the survivor keeps only one id), and a distance test alone is also
    wrong (a deleted 2-unit spur's tip is still within a stroke radius of the
    trunk, so it scores as alive). Merge provenance gives the exact answer.
    """
    alive: set = set()
    for e in pruned.edges.values():
        alive.add(e.id)
        alive.update(e.extra.get("mergedFrom", []))
    return alive & set(case["labels"])


def _recall_by_length(case: dict, alive: set) -> dict:
    """Noise-removal rate bucketed by the spur's DESIGNED length in stroke widths.

    The aggregate rate is not the interesting number: spurs at 0.1 stroke widths
    are unambiguous artifacts and spurs at 1.3 are genuinely arguable detail. What
    matters is where the decision boundary lands.
    """
    buckets = [(0.0, 0.3), (0.3, 0.7), (0.7, 1.1), (1.1, 99.0)]
    out = {}
    for lo, hi in buckets:
        ids = [eid for eid, n in case["spurNorm"].items() if lo <= n < hi]
        if not ids:
            continue
        removed = sum(1 for eid in ids if eid not in alive)
        out[f"{lo:.1f}-{hi:.1f}"] = {"removed": removed, "total": len(ids)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--spurs", type=int, default=14)
    ap.add_argument("--lambdas", nargs="*", type=float,
                    default=[0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0])
    args = ap.parse_args()

    all_rows = {}
    for i, name in enumerate(SHAPES):
        case = build_case(name, n_spurs=args.spurs, seed=args.seed + i)
        write_case(case)
        rows = evaluate(case, args.lambdas)
        all_rows[name] = rows
        print(f"\n{name}  (radius {case['radius']:.0f}, "
              f"{rows[0]['noiseTotal']} noise spurs, {rows[0]['realTotal']} real branches)")
        print("  lam   noise removed   real branches kept   edges left")
        for r in rows:
            print(f"  {r['lam']:4.2f}   {r['noiseRemoved']:3d}/{r['noiseTotal']:<3d} "
                  f"({r['recall']:5.1%})   {r['realTotal'] - r['realRemoved']:3d}/"
                  f"{r['realTotal']:<3d} ({r['realSurvival']:5.1%})   {r['edges']:4d}")

    out = OUT / "classifier.json"
    out.write_text(json.dumps(all_rows, indent=1))

    # aggregate: the operating point where noise recall is highest with no real loss
    print("\nBest lambda per case (max noise recall with 100% real-branch survival):")
    best_lams = []
    for name, rows in all_rows.items():
        clean = [r for r in rows if r["realSurvival"] >= 1.0 - 1e-9]
        best = max(clean, key=lambda r: r["recall"]) if clean else None
        if best:
            best_lams.append(best["lam"])
            print(f"  {name:12s} lam {best['lam']:4.2f}  noise recall {best['recall']:5.1%}")
        else:
            print(f"  {name:12s} no lambda preserves every real branch")
    if best_lams:
        print(f"\nsafe operating range: lam {min(best_lams):.2f} .. {max(best_lams):.2f}")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
