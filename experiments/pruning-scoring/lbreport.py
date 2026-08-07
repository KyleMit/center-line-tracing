#!/usr/bin/env python3
"""Render the cross-backend leaderboard from metrics.json (no re-scoring).

    python3 experiments/pruning-scoring/lbreport.py

Framing note: comparing `published` against `auto` on error alone misreads what
the selector does. It is allowed to trade a little error for a simpler graph, so a
row where auto has slightly higher error and much lower complexity is a success,
not a regression. Both axes are shown, and the verdict column judges both.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from complexity import canonical_index  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DEBUG = REPO / "debug" / "pruning-scoring"

IMAGE_ORDER = [
    "house-wide", "butterfly-wide", "boat-tall", "island-tall", "balloon-tall",
    "home-wide", "house-tall", "dinosaur-wide", "landscape-square", "sun-square",
]


def cx(m: dict) -> float:
    return m["edges"] + m["control_points"] / 100.0


def verdict(pub: dict, auto: dict | None, tolerance: float = 0.05) -> str:
    if not auto:
        return "-"
    pub_cx = canonical_index(pub["graph"]) if pub.get("graph") else cx(pub)
    better_err = auto["sym_diff_ratio"] < pub["sym_diff_ratio"] - 1e-9
    better_cx = cx(auto) < pub_cx - 1e-9
    within = auto["sym_diff_ratio"] <= pub["sym_diff_ratio"] * (1 + tolerance) + 1e-9
    if better_err and better_cx:
        return "auto dominates"
    if better_err:
        return "auto lower error"
    if within and better_cx:
        return "auto simpler"
    if within:
        return "tie"
    return "published better"


def main() -> int:
    data = json.loads((DEBUG / "metrics.json").read_text())
    results = [r for r in data["results"] if r.get("status") == "ok"]
    by = {(r["track"], r["image"]): r for r in results}
    tracks = sorted({r["track"] for r in results})
    images = [i for i in IMAGE_ORDER if any((t, i) in by for t in tracks)]

    out = [
        "# Cross-backend leaderboard\n",
        f"Generated {data['generated']} · {data['seconds']}s wall clock · "
        f"λ sweep {min(data['lambdas'])}–{max(data['lambdas'])} · "
        f"selection tolerance {data['tolerance']:.0%}\n",
        "Every backend is shown at **its own best setting**, which is the point of "
        "the exercise: no backend is penalized for a threshold someone else picked.\n",
        "* **err** — symmetric difference / source ink area. Lower is better. This is "
        "*not* the same scale as `src/compare.js`, which reports differing pixels over "
        "the whole canvas; see NOTES.md §3.",
        "* **cx** — complexity index (branches + control points / 100), measured "
        "**after canonicalization on both sides**: the automatic path splices "
        "degree-2 chains and most published graphs do not, so raw edge counts would "
        "credit pruning with a simplification that is only a change of representation.",
        "* **published** — the best variant that track shipped, scored as-is.",
        "* **auto** — automatic width-aware pruning selected by this harness, applied "
        "to that track's LEAST-processed variant. Where a track published variants "
        "from different libraries or skeletonizers, that variant may not be the same "
        "one as `published`, so this column is 'best reachable from the rawest graph', "
        "not a controlled pruning A/B. The controlled comparison is `abtest.md`.",
        "* **raster** — colour-independent raster ink diff of the promoted result, as "
        "a cross-check on the vector number.\n",
    ]

    # ---- per image
    for image in images:
        rows = []
        for track in tracks:
            r = by.get((track, image))
            if not r:
                continue
            pub = r["publishedBest"]
            auto = (r.get("auto") or {}).get("metrics")
            aob = (r.get("autoOnBest") or {}).get("metrics")
            best = min([m for m in (pub, auto, aob) if m],
                       key=lambda m: m["sym_diff_ratio"])
            rows.append((track, pub, auto, best, r))
        if not rows:
            continue
        rows.sort(key=lambda t: t[3]["sym_diff_ratio"])
        out.append(f"\n## {image}\n")
        out.append("| backend | published err / cx | auto err / cx | λ | best err "
                   "| IoU | boundary P95 | raster err | verdict |")
        out.append("|---|---|---|---|---|---|---|---|---|")
        for track, pub, auto, best, r in rows:
            lam = (r.get("auto") or {}).get("lam")
            raster = (r.get("rasterInk") or {}).get("symDiffRatio")
            pub_cx = canonical_index(pub["graph"]) if pub.get("graph") else cx(pub)
            auto_cell = f"{auto['sym_diff_ratio']:.4f} / {cx(auto):.1f}" if auto else "--"
            lam_cell = f"{lam:.2f}" if lam is not None else "--"
            raster_cell = f"{raster:.4f}" if raster is not None else "--"
            out.append(
                f"| {track} "
                f"| {pub['sym_diff_ratio']:.4f} / {pub_cx:.1f} "
                f"| {auto_cell} "
                f"| {lam_cell} "
                f"| **{best['sym_diff_ratio']:.4f}** "
                f"| {best['iou']:.4f} "
                f"| {best['boundary_p95']:.2f} "
                f"| {raster_cell} "
                f"| {verdict(pub, auto)} |"
            )

    # ---- summary
    tally: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    errs: dict[str, list[float]] = defaultdict(list)
    for r in results:
        pub = r["publishedBest"]
        auto = (r.get("auto") or {}).get("metrics")
        aob = (r.get("autoOnBest") or {}).get("metrics")
        tally[r["track"]][verdict(pub, auto)] += 1
        best = min([m for m in (pub, auto, aob) if m], key=lambda m: m["sym_diff_ratio"])
        errs[r["track"]].append(best["sym_diff_ratio"])

    out.append("\n## Backend ranking (median best-of error across all images)\n")
    out.append("| backend | images | median err | best err | worst err | "
               "auto dominates | auto simpler | tie | published better |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    ranked = sorted(errs, key=lambda t: sorted(errs[t])[len(errs[t]) // 2])
    for track in ranked:
        v = sorted(errs[track])
        t = tally[track]
        out.append(
            f"| {track} | {len(v)} | **{v[len(v) // 2]:.4f}** | {v[0]:.4f} | {v[-1]:.4f} "
            f"| {t['auto dominates']} | {t['auto simpler']} | {t['tie']} "
            f"| {t['published better']} |"
        )

    path = DEBUG / "leaderboard.md"
    path.write_text("\n".join(out) + "\n")
    print("\n".join(out))
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
