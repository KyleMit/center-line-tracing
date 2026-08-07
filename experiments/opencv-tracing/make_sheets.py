"""Generate this track's contact sheets from a completed `metrics.json`.

    python3 experiments/opencv-tracing/make_sheets.py

Writes into `debug/opencv-tracing/sheets/`:
    corpus-junctions.{png,html}   cases 1-6 and 13-16, the first target
    corpus-full.{png,html}        all 20 synthetic cases
    real-ladder.{png,html}        the real inputs attempted
    progress-house-wide.{png,html}  the iteration trajectory on the focus image
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import bench
import pipeline
import sheets
import svgraster

DEBUG = bench.DEBUG
OUT = DEBUG / "sheets"
HAIR = DEBUG / "hairline"

# The iteration trajectory, in the order it actually happened. Each entry is
# what changed, so the progress sheet reads as an experiment log.
PROGRESS = [
    ("raw thinning + skeleton-tracing", {"cap_extend": "none", "simplify_px": 0.0}),
    ("cap extension to the boundary (WORSE)", {"cap_extend": "boundary", "simplify_px": 0.0}),
    ("cap extension to boundary - R", {"cap_extend": "round", "simplify_px": 0.0}),
    ("+ 0.5px Douglas-Peucker cleanup", {"cap_extend": "round", "simplify_px": 0.5}),
    ("Guo-Hall instead of Zhang-Suen", {"cap_extend": "round", "simplify_px": 0.5,
                                        "thinning": "guohall"}),
]


def _pixel_diff(input_svg: Path, output_svg: Path) -> float:
    """Run the incumbent's src/compare.js, for continuity with its numbers."""
    tmp = OUT / "_render"
    tmp.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["node", str(bench.ROOT / "src" / "compare.js"), str(input_svg), str(output_svg),
         "1200", str(tmp / "d.png"), str(tmp / "s.png")],
        capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        if "differing pixels" in line:
            return float(line.split("=")[-1].strip().rstrip("%"))
    return float("nan")


def rows_for(runs: list, names: list[str]) -> list:
    rows = []
    for name in names:
        run = next((r for r in runs
                    if r["target"] == name and r["configLabel"] == "default"), None)
        if run is None:
            continue
        target = next(t for t in bench.resolve_targets([name]) if t["name"] == name)
        output_svg = bench.OUTPUTS / f"{name}.svg"
        if not output_svg.exists():
            continue
        tags = ", ".join(f"{k}:{v}" for k, v in run["tags"].items() if v) or "no tags"
        rows.append({
            "name": name, "input_svg": target["path"], "output_svg": output_svg,
            "hairline_svg": HAIR / f"{name}.svg",
            "iou": run["reconstruction"]["iou"],
            "sym": run["reconstruction"]["symDiffFraction"],
            "tagline": tags,
        })
    return rows


def main():
    payload = json.loads((DEBUG / "metrics.json").read_text())
    runs = payload["runs"]
    OUT.mkdir(parents=True, exist_ok=True)

    synthetic = [r["target"] for r in runs
                 if r["kind"] == "synthetic" and r["configLabel"] == "default"]
    real = [r["target"] for r in runs
            if r["kind"] == "real" and r["configLabel"] == "default"]
    first_target = [n for n in synthetic
                    if int(n.split("-")[1]) in (1, 2, 3, 4, 5, 6, 13, 14, 15, 16)]

    sheets.comparison_sheet(rows_for(runs, first_target), OUT / "corpus-junctions",
                            "opencv-tracing — first target: corpus 1-6, 13-16")
    sheets.comparison_sheet(rows_for(runs, synthetic), OUT / "corpus-full",
                            "opencv-tracing — full synthetic corpus (20 cases)")
    real_rows = sheets.comparison_sheet(rows_for(runs, real), OUT / "real-ladder",
                                        "opencv-tracing — real ladder")

    # Progress sheet on the focus image.
    focus = "house-wide"
    target = next(t for t in bench.resolve_targets([focus]) if t["name"] == focus)
    svg_text = target["path"].read_text()
    viewbox = svgraster.read_viewbox(svg_text)
    entries = []
    work = OUT / "_progress"
    work.mkdir(parents=True, exist_ok=True)
    for i, (tag, overrides) in enumerate(PROGRESS):
        config = dict(bench.DEFAULT_CONFIG)
        config.update(overrides)
        result = bench.run_one(target, config)
        rasters, _ = svgraster.rasterize_elements(
            svg_text, bench.MASKS / focus / f"s{config['scale']:g}", config["scale"])
        graphs = [pipeline.process_element(
            r, j, thinning=config["thinning"], tracer=config["tracer"],
            cap_extend=config["cap_extend"], csize=config["csize"],
            simplify_px=config["simplify_px"]) for j, r in enumerate(rasters)]
        path = work / f"{i:02d}.svg"
        path.write_text(pipeline.graph_to_svg(graphs, viewbox))
        entries.append({
            "tag": tag, "output_svg": path,
            "score": (f"IoU {result['reconstruction']['iou']:.4f}  "
                      f"diff {_pixel_diff(target['path'], path):.2f}%  "
                      f"V {result['complexity']['vertexCount']}"),
        })
    sheets.progress_sheet(entries, OUT / "progress-house-wide",
                          f"opencv-tracing — iteration trajectory on {focus}")

    # Pixel-diff continuity numbers against the incumbent's own harness.
    diffs = {row["name"]: _pixel_diff(row["input_svg"], row["output_svg"])
             for row in real_rows}
    (DEBUG / "pixel-diff.json").write_text(json.dumps(diffs, indent=1))
    print(json.dumps(diffs, indent=1))


if __name__ == "__main__":
    main()
