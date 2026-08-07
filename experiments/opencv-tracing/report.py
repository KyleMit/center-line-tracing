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
        # Whichever thinner is the default carries the "default" label, so look
        # up both by explicit name and fall back to the default label.
        zs = configs.get("thinning=zhangsuen") or configs.get("default")
        gh = configs.get("thinning=guohall") or configs.get("default")
        if zs is gh:
            continue
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
        entry = pixel_diff.get(run["target"], {})
        # pixel-diff.json holds one entry per thinner; pick the run's own.
        diff = entry.get(run["config"]["thinning"], {}).get("pixelDiffPct", float("nan")) \
            if isinstance(entry, dict) else entry
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
                        f"| measured on {entry['measuredMegapixels']:.1f} Mpx |")
    rows.append("")
    rows.append("Tracers are compared by throughput (Mpx/s), not by wall time: each "
                "is measured on as many masks as its own budget allowed, because the "
                "pure-script implementations cannot process the full set in "
                "reasonable time.")
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
    import sys
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEBUG / "metrics.json"
    payload = json.loads(source.read_text())
    runs = payload["runs"]
    pixel_diff = {}
    if (DEBUG / "pixel-diff.json").exists():
        pixel_diff = json.loads((DEBUG / "pixel-diff.json").read_text())

    cfg = payload.get("defaultConfig", {})
    print(f"### Synthetic corpus — default config "
          f"({cfg.get('thinning')}, {cfg.get('tracer')}, cap={cfg.get('cap_extend')})\n")
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
        print("| runtime | target | bit-identical | same polyline count | "
              "max deviation (px) |")
        print("|---|---|---|---|---:|")
        for label, per_target in payload["tracerAgreement"].items():
            for name, entry in per_target.items():
                if entry is None:
                    print(f"| `{label}` | {name} | skipped (too slow) | — | — |")
                    continue
                print(f"| `{label}` | {name} | {'yes' if entry['exact'] else '**no**'} "
                      f"| {'yes' if entry['samePolylineCount'] else '**no**'} "
                      f"| {entry['maxDeviationPx']:.2f} |")


if __name__ == "__main__":
    main()
