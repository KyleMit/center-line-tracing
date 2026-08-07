"""Render `metrics.json` as the markdown tables that go into NOTES.md.

    python3 experiments/opencv-tracing/report.py > /tmp/tables.md

Kept separate from bench.py so the tables can be regenerated without re-running
anything, and so the numbers in NOTES.md are always transcribed by a program
rather than by hand.
"""

from __future__ import annotations

import json
from pathlib import Path

DEBUG = Path(__file__).resolve().parents[2] / "debug" / "opencv-tracing"


def _get(run, *path, default=float("nan")):
    node = run
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def corpus_table(runs, label="default"):
    rows = ["| # | case | IoU | sym % | bound P95 | cl→gt P95 | gt→cl P95 | cov | E | V | tags |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for run in runs:
        if run["kind"] != "synthetic" or run["configLabel"] != label:
            continue
        name = run["target"]
        index = name.split("-")[1]
        tags = ", ".join(f"{k} {v}" for k, v in run["tags"].items() if v) or "—"
        rows.append(
            f"| {int(index)} | {name.split('-', 2)[2]} "
            f"| {_get(run, 'reconstruction', 'iou'):.4f} "
            f"| {_get(run, 'reconstruction', 'symDiffFraction') * 100:.2f} "
            f"| {_get(run, 'reconstruction', 'boundaryP95'):.2f} "
            f"| {_get(run, 'centerline', 'centerlineToGtP95'):.3f} "
            f"| {_get(run, 'centerline', 'gtToCenterlineP95'):.3f} "
            f"| {_get(run, 'centerline', 'gtCoverageFraction'):.3f} "
            f"| {run['complexity']['edgeCount']} "
            f"| {run['complexity']['vertexCount']} | {tags} |")
    return "\n".join(rows)


def thinning_table(runs):
    by_target = {}
    for run in runs:
        by_target.setdefault(run["target"], {})[run["configLabel"]] = run

    rows = ["| case | ZS IoU | GH IoU | Δ | ZS edges | GH edges | ZS tags | GH tags | winner |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    zs_wins = gh_wins = 0
    for name, configs in by_target.items():
        zs, gh = configs.get("default"), configs.get("thinning=guohall")
        if not zs or not gh:
            continue
        a = _get(zs, "reconstruction", "iou")
        b = _get(gh, "reconstruction", "iou")
        zt = sum(zs["tags"].values())
        gt = sum(gh["tags"].values())
        # Reconstruction first; a tie on IoU is broken by graph simplicity,
        # which report §11 says to prefer.
        if abs(a - b) > 0.002:
            winner = "Zhang-Suen" if a > b else "Guo-Hall"
        elif zt != gt:
            winner = "Zhang-Suen" if zt < gt else "Guo-Hall"
        else:
            winner = "tie"
        zs_wins += winner == "Zhang-Suen"
        gh_wins += winner == "Guo-Hall"
        rows.append(f"| {name} | {a:.4f} | {b:.4f} | {b - a:+.4f} "
                    f"| {zs['complexity']['edgeCount']} | {gh['complexity']['edgeCount']} "
                    f"| {zt} | {gt} | {winner} |")
    rows.append(f"\n**Zhang-Suen wins {zs_wins}, Guo-Hall wins {gh_wins}, "
                f"{len(by_target) - zs_wins - gh_wins} tie.**")
    return "\n".join(rows)


def real_table(runs, pixel_diff: dict):
    rows = ["| image | elements | IoU | sym % | pixel diff % | edges | vertices | "
            "extract s | s/element | tags |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for run in runs:
        if run["kind"] != "real" or run["configLabel"] != "default":
            continue
        tags = ", ".join(f"{k} {v}" for k, v in run["tags"].items() if v) or "—"
        diff = pixel_diff.get(run["target"], float("nan"))
        rows.append(
            f"| {run['target']} | {run['elements']} "
            f"| {_get(run, 'reconstruction', 'iou'):.4f} "
            f"| {_get(run, 'reconstruction', 'symDiffFraction') * 100:.2f} "
            f"| **{diff:.2f}** "
            f"| {run['complexity']['edgeCount']} | {run['complexity']['vertexCount']} "
            f"| {run['runtime']['extract_s']:.2f} "
            f"| {run['runtime']['extract_s_per_element']:.3f} | {tags} |")
    return "\n".join(rows)


def speed_table(speed):
    rows = [f"Masks: **{speed['maskMegapixels']:.1f} Mpx** across "
            f"{speed['maskCount']} elements, best of {speed['repeats']}.", "",
            "| stage | implementation | seconds | Mpx/s | vs OpenCV ZS |",
            "|---|---|---:|---:|---:|"]
    base = speed["skeletonizers"]["cv2.ximgproc.thinning(ZHANGSUEN)"]["seconds"]
    for label, entry in speed["skeletonizers"].items():
        rows.append(f"| skeletonize | `{label}` | {entry['seconds']:.3f} "
                    f"| {entry['megapixels_per_s']:.1f} | {entry['seconds'] / base:.2f}x |")
    for label, entry in speed["tracers"].items():
        if entry.get("seconds") is None:
            rows.append(f"| trace | `{label}` | — | — | {entry['note']} |")
        else:
            rows.append(f"| trace | `{label}` | {entry['seconds']:.3f} "
                        f"| {entry['megapixels_per_s']:.1f} "
                        f"| {entry['seconds'] / base:.2f}x |")
    return "\n".join(rows)


def variable_width_table(runs):
    rows = ["| case | constant-width IoU | derived-profile IoU | Δ |", "|---|---:|---:|---:|"]
    for run in runs:
        if run["configLabel"] != "default":
            continue
        a = _get(run, "reconstruction", "iou")
        b = _get(run, "reconstructionVariableWidth", "iou")
        if a != a or b != b:
            continue
        rows.append(f"| {run['target']} | {a:.4f} | {b:.4f} | {b - a:+.4f} |")
    return "\n".join(rows)


def main():
    payload = json.loads((DEBUG / "metrics.json").read_text())
    runs = payload["runs"]
    pixel_diff = {}
    if (DEBUG / "pixel-diff.json").exists():
        pixel_diff = json.loads((DEBUG / "pixel-diff.json").read_text())

    print("### Synthetic corpus — default config (Zhang-Suen, st-c, cap=round)\n")
    print(corpus_table(runs))
    print("\n### Zhang-Suen vs Guo-Hall, identical masks\n")
    print(thinning_table(runs))
    print("\n### Real ladder\n")
    print(real_table(runs, pixel_diff))
    print("\n### Derived radius: constant width vs the sampled profile\n")
    print(variable_width_table(runs))
    if "speed" in payload:
        print("\n### Runtime\n")
        print(speed_table(payload["speed"]))
    if "tracerAgreement" in payload:
        print("\n### Cross-runtime agreement\n")
        for label, per_target in payload["tracerAgreement"].items():
            checked = {k: v for k, v in per_target.items() if v is not None}
            agree = sum(1 for v in checked.values() if v)
            skipped = len(per_target) - len(checked)
            note = f" ({skipped} skipped as too slow)" if skipped else ""
            print(f"- `{label}` vs `st-c`: identical polylines on "
                  f"**{agree}/{len(checked)}** targets{note}")
            for name, ok in checked.items():
                if not ok:
                    print(f"  - MISMATCH on {name}")


if __name__ == "__main__":
    main()
