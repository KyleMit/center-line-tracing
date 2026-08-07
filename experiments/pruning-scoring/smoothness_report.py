#!/usr/bin/env python3
"""Grade path complexity and wobble across every promoted graph.

    python3 experiments/pruning-scoring/smoothness_report.py
    python3 experiments/pruning-scoring/smoothness_report.py --stroke house-wide

Answers a question the reconstruction metrics cannot: is a backend's accuracy
coming from putting the line in the right place, or from wiggling along the
outline? Writes `debug/pruning-scoring/smoothness.json` plus a markdown table, and
with `--stroke` extracts one stroke recovered by every backend so the difference
can be looked at rather than inferred.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clg import CenterlineGraph, smoothness  # noqa: E402
from clg.smoothness import Smoothness, naturalness_grade  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DEBUG = REPO / "debug" / "pruning-scoring"
GRAPHS = DEBUG / "graphs"


def score_all() -> dict:
    out: dict[str, dict] = {}
    for gp in sorted(GRAPHS.rglob("*.json")):
        g = CenterlineGraph.load(gp)
        out.setdefault(gp.parent.name, {})[gp.stem] = smoothness.graph_smoothness(g).to_dict()
    return out


def longest_shared_stroke(image: str, *, min_span: float = 800.0) -> dict | None:
    """The longest stroke that EVERY backend recovered, for a like-for-like look.

    Comparing different strokes would confound the backend with the geometry, so
    this insists on one stroke, present everywhere, and reports the window.
    """
    picks = {}
    for track_dir in sorted(p for p in GRAPHS.iterdir() if p.is_dir()):
        gp = track_dir / f"{image}.json"
        if not gp.exists():
            continue
        g = CenterlineGraph.load(gp)
        best = None
        for e in g.edges.values():
            xs = [p[0] for p in e.points]
            if max(xs) - min(xs) < min_span:
                continue
            if best is None or e.length > best.length:
                best = e
        if best is not None:
            picks[track_dir.name] = best
    if len(picks) < 2:
        return None

    backends = []
    for name, e in sorted(picks.items()):
        pts = list(e.points)
        if pts[0][0] > pts[-1][0]:
            pts = list(reversed(pts))
        sm = smoothness.edge_smoothness(e)
        backends.append({
            "name": name,
            "points": [[round(x, 2), round(y, 2)] for x, y in pts],
            "totalPoints": len(e.points),
            "length": round(e.length, 1),
            "radius": round(e.median_radius or 0, 2),
            "vertsPerWidth": round(sm[0].verts_per_width, 2) if sm else None,
            "wiggle": round(sm[0].wiggle, 4) if sm else None,
        })
    ys = [p[1] for b in backends for p in b["points"]]
    return {"image": image, "yRange": [round(min(ys), 1), round(max(ys), 1)],
            "backends": backends}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stroke", default="house-wide",
                    help="image to pull one shared stroke from (default: house-wide)")
    ap.add_argument("--out", default=str(DEBUG / "smoothness.json"))
    args = ap.parse_args()

    per = score_all()
    detail = longest_shared_stroke(args.stroke)

    rows = []
    for track, imgs in per.items():
        med = lambda k: statistics.median(v[k] for v in imgs.values())  # noqa: E731
        w = med("wiggle")
        rows.append({
            "backend": track, "n": len(imgs),
            "wiggle": round(w, 5),
            "grade": naturalness_grade(Smoothness(wiggle=w))[0],
            "vertsPerWidth": round(med("verts_per_width"), 3),
            "turningPerWidth": round(med("turning_per_width"), 4),
            "reversalsPerWidth": round(med("reversals_per_width"), 4),
        })
    rows.sort(key=lambda r: r["vertsPerWidth"])

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(
        {"perImage": per, "summary": rows, "sharedStroke": detail}, indent=1))

    md = ["# Path complexity and wobble\n",
          "Medians across each backend's promoted graphs. `wobble` is RMS perpendicular",
          "deviation from the path's own one-stroke-width low-pass with the curvature bias",
          "removed, in stroke radii — an exact line scores 0.000, an exact arc 0.002.\n",
          "| backend | points / width | wobble | turning / width | reversals / width | reads as |",
          "|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['backend']} | {r['vertsPerWidth']:.2f} | {r['wiggle']:.4f} | "
                  f"{r['turningPerWidth']:.3f} | {r['reversalsPerWidth']:.2f} | {r['grade']} |")
    if detail:
        md.append(f"\n## One shared stroke — {detail['image']}\n")
        md.append("The longest stroke every backend recovered, so the geometry is held fixed.\n")
        md.append("| backend | control points | length | points / width | wobble |")
        md.append("|---|---|---|---|---|")
        for b in sorted(detail["backends"], key=lambda x: x["totalPoints"]):
            md.append(f"| {b['name']} | {b['totalPoints']} | {b['length']:.0f} | "
                      f"{b['vertsPerWidth']:.2f} | {b['wiggle']:.4f} |")
    (DEBUG / "smoothness.md").write_text("\n".join(md) + "\n")

    print("\n".join(md))
    print(f"\nwrote {args.out} and {DEBUG / 'smoothness.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
