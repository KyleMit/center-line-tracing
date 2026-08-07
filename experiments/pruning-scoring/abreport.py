#!/usr/bin/env python3
"""Render the controlled A/B table from abtest.json, without re-running the sweeps.

Two things this reporter fixes about a naive reading of the raw results:

1. **Complexity is measured after canonicalization on BOTH sides.** The automatic
   path splices degree-2 chains before pruning; the published graphs mostly do not.
   Comparing raw edge counts credits automatic pruning with a large simplification
   that is only a change of representation (flo-mat house-wide: 277 edges -> 36
   branches with nothing removed). See complexity.py.

2. **The trade is reported as a trade.** A verdict label alone hides the shape of
   the result; `Δerr` and `Δcx` against the track's own pruning say what actually
   happened. Separately, `reachable` is the best error any candidate in the sweep
   achieved, which separates "can width-aware pruning get there" from "does the
   selection rule pick it".
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

PAIR_FILES = {
    "flo-mat": ("debug/flo-mat/graphs/{img}.json",
                {"sat-1.3": "debug/flo-mat/graphs/{img}-sat13.json"}),
    "tegaki": ("debug/tegaki/graphs/{img}.prune-none.json",
               {"tegaki-length": "debug/tegaki/graphs/{img}.prune-tegaki-length.json",
                "tegaki-width": "debug/tegaki/graphs/{img}.prune-tegaki-width.json"}),
    "polygon-voronoi": ("debug/polygon-voronoi/graphs/{img}-fitodic.json",
                        {"fitodic-filter":
                         "debug/polygon-voronoi/graphs/{img}-fitodic+filter.json"}),
}


def pct(new: float, old: float) -> str:
    if old <= 0:
        return "--"
    return f"{100.0 * (new - old) / old:+.0f}%"


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEBUG / "abtest.json"
    rows = json.loads(path.read_text())

    lines = [
        "# Automatic pruning vs hand-tuned pruning — controlled A/B\n",
        "Same backend, same rasterization, same tracing; **only the pruning stage "
        "differs**. Automatic pruning always starts from that track's UNPRUNED graph.\n",
        "* **err** — symmetric difference / source ink area (lower is better)",
        "* **cx** — complexity index (branches + control points / 100), measured "
        "**after canonicalization on both sides** so the comparison is like for like",
        "* **Δerr / Δcx** — automatic vs that track's own pruning",
        "* **reachable** — the lowest error any candidate in the sweep achieved: what "
        "width-aware pruning could reach with a perfect selection rule\n",
    ]

    tally: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for track in sorted({r["track"] for r in rows}):
        raw_pat, tuned_pats = PAIR_FILES.get(track, (None, {}))
        trows = sorted((r for r in rows if r["track"] == track), key=lambda x: x["image"])
        lines.append(f"\n## {track}\n")
        lines.append("| image | unpruned err / cx | hand-tuned err / cx | auto err / cx "
                     "| λ | Δerr | Δcx | reachable |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in trows:
            img = r["image"]
            un, au = r["unpruned"], r["auto"]
            ht_name = r.get("bestHandTuned")
            ht = r["handTuned"].get(ht_name) if ht_name else None
            reachable = min((c["error"] for c in r.get("sweep", [])), default=None)

            # canonical complexity for the two published graphs
            un_cx = canonical_index(raw_pat.format(img=img)) if raw_pat else None
            ht_cx = (canonical_index(tuned_pats[ht_name].format(img=img))
                     if (ht_name and ht_name in tuned_pats) else None)
            au_cx = au["edges"] + au["control_points"] / 100.0   # already canonical

            d_err = pct(au["sym_diff_ratio"], ht["sym_diff_ratio"]) if ht else "--"
            d_cx = pct(au_cx, ht_cx) if ht_cx else "--"
            if ht:
                tally[track][r.get("verdict", "-")] += 1
                if reachable is not None and reachable < ht["sym_diff_ratio"] - 1e-9:
                    tally[track]["sweep beat hand-tuned"] += 1
                if au_cx < ht_cx - 1e-9 and au["sym_diff_ratio"] <= \
                        ht["sym_diff_ratio"] * 1.05 + 1e-12:
                    tally[track]["simpler within 5%"] += 1

            un_cell = (f"{un['sym_diff_ratio']:.4f} / {un_cx:.1f}"
                       if un_cx is not None else f"{un['sym_diff_ratio']:.4f} / --")
            ht_cell = (f"{ht['sym_diff_ratio']:.4f} / {ht_cx:.1f}"
                       if ht and ht_cx is not None else "--")
            reach_cell = f"{reachable:.4f}" if reachable is not None else "--"
            lines.append(
                f"| {img} | {un_cell} | {ht_cell} "
                f"| {au['sym_diff_ratio']:.4f} / {au_cx:.1f} "
                f"| {au['lam']:.2f} | {d_err} | {d_cx} | {reach_cell} |"
            )

    lines.append("\n## Summary\n")
    lines.append("| backend | images | auto dominates | auto lower error "
                 "| auto simpler at same error | simpler within 5% | tie "
                 "| hand-tuned better | a sweep candidate beat hand-tuned |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for track, t in sorted(tally.items()):
        n = sum(v for k, v in t.items()
                if k not in ("sweep beat hand-tuned", "simpler within 5%"))
        lines.append(
            f"| {track} | {n} | {t['auto-dominates']} | {t['auto-lower-error']} "
            f"| {t['auto-simpler-same-error']} | {t['simpler within 5%']} "
            f"| {t['tie']} | {t['hand-tuned-better']} | {t['sweep beat hand-tuned']} |"
        )

    out = DEBUG / "abtest.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
