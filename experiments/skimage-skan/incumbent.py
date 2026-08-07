#!/usr/bin/env python3
"""Score the incumbent's promoted outputs with *this* track's scorer.

The incumbent's numbers are quoted from docs/current-attempt-handoff.md; this
re-measures them on this machine, with the same IoU / boundary / complexity
metrics used for everything else, so the head-to-head is apples-to-apples
rather than a comparison of two differently-defined percentages.

    python3 experiments/skimage-skan/incumbent.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench  # noqa: E402
import metrics as M  # noqa: E402
import svgio  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
PAIRS = ["dinosaur-wide", "landscape-square", "sun-square"]


def path_stats(text: str) -> tuple[int, int]:
    paths = re.findall(r'<path[^>]*d="([^"]*)"', text)
    return len(paths), sum(len(re.findall(r"[MLCQAZ]", d)) for d in paths)


def main() -> None:
    store = bench.load_metrics()
    records = []
    for name in PAIRS:
        src = REPO / "inputs" / f"{name}.svg"
        out = REPO / "outputs" / f"{name}.svg"
        if not out.exists():
            print(f"skip {name}: no incumbent output")
            continue
        doc = svgio.load(src)
        n_paths, n_cmds = path_stats(out.read_text())
        rec = {
            "image": name, "tag": "incumbent",
            "source": str(src.relative_to(REPO)),
            "output": str(out.relative_to(REPO)),
            "svgPaths": n_paths, "pathCommands": n_cmds,
            "fileBytes": out.stat().st_size,
            "pixelDiffPct": M.pixel_diff(src, out, 1200,
                                         bench.DEBUG / "diffs" / f"{name}__incumbent.png"),
        }
        rec.update(M.restroke_score(doc, out, scale=4.0))
        records.append(rec)
    bench.merge(store, records)
    bench.save_metrics(store)

    print(f"{'image':18s} {'IoU':>7s} {'pixel%':>7s} {'bMed':>6s} {'bP95':>6s} "
          f"{'paths':>6s} {'cmds':>7s} {'bytes':>8s}")
    for r in records:
        print(f"{r['image']:18s} {r['iou']:7.4f} {r['pixelDiffPct']:7.2f} "
              f"{r['boundaryMedian']:6.3f} {r['boundaryP95']:6.2f} "
              f"{r['svgPaths']:6d} {r['pathCommands']:7d} {r['fileBytes']:8d}")


if __name__ == "__main__":
    main()
