#!/usr/bin/env python3
"""Controlled A/B: automatic width-aware pruning vs each track's own hand-tuned pruning.

Three tracks published variants that differ ONLY in the pruning stage, which makes
a clean comparison possible — everything upstream (rasterization, skeletonizer,
tracing, width estimation) is held fixed:

    flo-mat          <img>.json                    raw MAT, applySat: false
                     <img>-sat13.json              Scale Axis Transform, s = 1.3
    tegaki           <img>.prune-none.json         no pruning
                     <img>.prune-tegaki-length     Tegaki's length rule
                     <img>.prune-tegaki-width      Tegaki's width rule (spurWidthRatio 1.5)
    polygon-voronoi  <img>-fitodic.json            unfiltered Voronoi
                     <img>-fitodic+filter.json     branch filtering

For each pair: take the UNPRUNED graph, run automatic selection on it, and compare
against the track's own pruned graph. Both fidelity and complexity are reported,
because the whole point of model selection is the trade between them — a method
that only ever minimized error would just never prune.

    python3 experiments/pruning-scoring/abtest.py --jobs 4
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clg import CenterlineGraph, metrics, resolve, select, svgio  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DEBUG = REPO / "debug" / "pruning-scoring"

IMAGES = [
    "house-wide", "butterfly-wide", "boat-tall", "island-tall", "balloon-tall",
    "home-wide", "house-tall", "dinosaur-wide", "landscape-square", "sun-square",
]

PAIRS = {
    "flo-mat": {
        "raw": "debug/flo-mat/graphs/{img}.json",
        "tuned": {"sat-1.3": "debug/flo-mat/graphs/{img}-sat13.json"},
    },
    "tegaki": {
        "raw": "debug/tegaki/graphs/{img}.prune-none.json",
        "tuned": {
            "tegaki-length": "debug/tegaki/graphs/{img}.prune-tegaki-length.json",
            "tegaki-width": "debug/tegaki/graphs/{img}.prune-tegaki-width.json",
        },
    },
    "polygon-voronoi": {
        "raw": "debug/polygon-voronoi/graphs/{img}-fitodic.json",
        "tuned": {"fitodic-filter": "debug/polygon-voronoi/graphs/{img}-fitodic+filter.json"},
    },
}

# How much reconstruction error the selector may trade for simplicity, relative to
# the best candidate in the sweep.
TOLERANCE = 0.05


def _complexity(m: dict) -> float:
    """A single readable complexity number: branches + control points per 100 units."""
    return m["edges"] + m["control_points"] / 100.0


def verdict(pub: dict, auto: dict, *, tolerance: float = TOLERANCE) -> str:
    """Compare on both axes at once, since either alone is gameable."""
    err_pub, err_auto = pub["sym_diff_ratio"], auto["sym_diff_ratio"]
    cx_pub, cx_auto = _complexity(pub), _complexity(auto)
    better_err = err_auto < err_pub - 1e-9
    better_cx = cx_auto < cx_pub - 1e-9
    within = err_auto <= err_pub * (1 + tolerance) + 1e-9
    if better_err and (better_cx or abs(cx_auto - cx_pub) < 1e-9):
        return "auto-dominates"
    if better_err:
        return "auto-lower-error"
    if within and better_cx:
        return "auto-simpler-same-error"
    if within:
        return "tie"
    return "hand-tuned-better"


def _job(args) -> dict | None:
    track, image, spec, tolerance = args
    raw_path = REPO / spec["raw"].format(img=image)
    if not raw_path.exists():
        return None
    svg = resolve.resolve_source_svg(raw_path)
    if svg is None:
        return None
    src = svgio.load_source(str(svg))
    t0 = time.time()

    raw_graph = CenterlineGraph.load(raw_path)
    raw_m = metrics.score_graph(raw_graph, src)
    chosen, cands = select.select(raw_graph, src, tolerance=tolerance)
    if chosen is None:
        return None

    tuned = {}
    for name, pattern in spec["tuned"].items():
        p = REPO / pattern.format(img=image)
        if not p.exists():
            continue
        g = CenterlineGraph.load(p)
        tuned[name] = metrics.score_graph(g, src).to_dict()

    best_tuned_name = min(tuned, key=lambda k: tuned[k]["sym_diff_ratio"]) if tuned else None
    rec = {
        "track": track,
        "image": image,
        "unpruned": raw_m.to_dict(),
        "handTuned": tuned,
        "bestHandTuned": best_tuned_name,
        "auto": {"lam": chosen.lam, **chosen.metrics.to_dict()},
        "sweep": [c.to_dict() for c in cands],
        "seconds": round(time.time() - t0, 2),
    }
    if best_tuned_name:
        rec["verdict"] = verdict(tuned[best_tuned_name], rec["auto"], tolerance=tolerance)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", nargs="*", default=IMAGES)
    ap.add_argument("--tracks", nargs="*", default=list(PAIRS))
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--tolerance", type=float, default=TOLERANCE)
    ap.add_argument("--out", default=str(DEBUG / "abtest.json"))
    args = ap.parse_args()

    work = [(t, i, PAIRS[t], args.tolerance) for t in args.tracks for i in args.images]
    results = []
    with Pool(args.jobs) as pool:
        for rec in pool.imap_unordered(_job, work):
            if rec:
                results.append(rec)
                print(f"  {rec['track']}/{rec['image']}: {rec.get('verdict', '-')} "
                      f"(lam {rec['auto']['lam']}, {rec['seconds']}s)", flush=True)

    results.sort(key=lambda r: (r["track"], IMAGES.index(r["image"])
                                if r["image"] in IMAGES else 99))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, indent=1))

    md = ["# Automatic pruning vs hand-tuned pruning — controlled A/B\n",
          f"Generated {time.strftime('%Y-%m-%d %H:%M:%S')} · "
          f"selection tolerance {args.tolerance:.0%}\n",
          "Same backend, same everything upstream; only the pruning stage differs. "
          "`err` is symmetric difference / source ink area. `cx` is a complexity index "
          "(branches + control points / 100). Automatic pruning starts from the "
          "**unpruned** graph.\n"]
    for track in args.tracks:
        rows = [r for r in results if r["track"] == track]
        if not rows:
            continue
        md.append(f"\n## {track}\n")
        md.append("| image | unpruned err / cx | hand-tuned err / cx | auto err / cx "
                  "| auto λ | verdict |")
        md.append("|---|---|---|---|---|---|")
        for r in rows:
            un, au = r["unpruned"], r["auto"]
            ht = r["handTuned"].get(r["bestHandTuned"]) if r["bestHandTuned"] else None
            ht_cell = (f"{ht['sym_diff_ratio']:.4f} / {_complexity(ht):.1f}") if ht else "--"
            md.append(
                f"| {r['image']} | {un['sym_diff_ratio']:.4f} / {_complexity(un):.1f} "
                f"| {ht_cell} "
                f"| {au['sym_diff_ratio']:.4f} / {_complexity(au):.1f} "
                f"| {au['lam']:.2f} | {r.get('verdict', '-')} |"
            )
        wins = sum(1 for r in rows if r.get("verdict", "").startswith("auto"))
        md.append(f"\n**{wins}/{len(rows)} images: automatic pruning wins or ties "
                  f"favourably.**\n")
    (DEBUG / "abtest.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    print(f"\nwrote {args.out} and {DEBUG / 'abtest.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
