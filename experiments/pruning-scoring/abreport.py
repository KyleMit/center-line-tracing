#!/usr/bin/env python3
"""Post-process abtest.json into the summary table, without re-running the sweeps.

Separates two questions that the single "verdict" column conflates:

  1. Can width-aware pruning REACH a better operating point than the track's own
     pruning? -> compare the best candidate in the sweep against hand-tuned.
  2. Does the automatic SELECTION RULE pick it? -> compare the selected candidate.

Both matter. (1) is about the pruning features, (2) is about the model-selection
criterion, and a method can succeed at one and fail at the other.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEBUG = REPO / "debug" / "pruning-scoring"


def complexity(edges: float, control_points: float) -> float:
    return edges + control_points / 100.0


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEBUG / "abtest.json"
    rows = json.loads(path.read_text())

    lines = [
        "# Automatic pruning vs hand-tuned pruning — controlled A/B\n",
        "Same backend, same rasterization, same tracing; **only the pruning stage "
        "differs**. Automatic pruning always starts from that track's UNPRUNED graph.\n",
        "* `err` — symmetric difference / source ink area (lower is better)",
        "* `cx` — complexity index: branches + control points / 100",
        "* `auto` — the candidate the selection rule chose",
        "* `reachable` — the best error any candidate in the sweep achieved, i.e. what "
        "width-aware pruning could reach with a perfect selection rule\n",
    ]

    tally: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for track in sorted({r["track"] for r in rows}):
        trows = [r for r in rows if r["track"] == track]
        lines.append(f"\n## {track}\n")
        lines.append("| image | unpruned err / cx | hand-tuned err / cx | auto err / cx "
                     "| λ | reachable err | verdict |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in sorted(trows, key=lambda x: x["image"]):
            un, au = r["unpruned"], r["auto"]
            ht = r["handTuned"].get(r["bestHandTuned"]) if r.get("bestHandTuned") else None
            reachable = min((c["error"] for c in r.get("sweep", [])), default=None)
            v = r.get("verdict", "-")
            tally[track][v] += 1
            if ht and reachable is not None and reachable < ht["sym_diff_ratio"] - 1e-9:
                tally[track]["reachable-beats-hand-tuned"] += 1
            ht_cell = (f"{ht['sym_diff_ratio']:.4f} / "
                       f"{complexity(ht['edges'], ht['control_points']):.1f}") if ht else "--"
            reach_cell = f"{reachable:.4f}" if reachable is not None else "--"
            lines.append(
                f"| {r['image']} "
                f"| {un['sym_diff_ratio']:.4f} / "
                f"{complexity(un['edges'], un['control_points']):.1f} "
                f"| {ht_cell} "
                f"| {au['sym_diff_ratio']:.4f} / "
                f"{complexity(au['edges'], au['control_points']):.1f} "
                f"| {au['lam']:.2f} "
                f"| {reach_cell} "
                f"| {v} |"
            )

    lines.append("\n## Summary\n")
    lines.append("| backend | images | auto dominates | auto lower error | "
                 "auto simpler, same error | tie | hand-tuned better | "
                 "a sweep candidate beat hand-tuned |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for track, t in sorted(tally.items()):
        n = sum(v for k, v in t.items() if k != "reachable-beats-hand-tuned")
        lines.append(
            f"| {track} | {n} | {t['auto-dominates']} | {t['auto-lower-error']} | "
            f"{t['auto-simpler-same-error']} | {t['tie']} | {t['hand-tuned-better']} | "
            f"{t['reachable-beats-hand-tuned']} |"
        )

    out = DEBUG / "abtest.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
