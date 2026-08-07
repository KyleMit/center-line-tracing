#!/usr/bin/env python3
"""Re-runnable benchmark: one config (or a sweep) over the input ladder.

    python3 experiments/autotrace/bench.py --images house-wide dinosaur-wide \
        --mode element --scale 4 --label base

Writes debug/autotrace/metrics.json (accumulated, keyed by label+image),
promoted SVGs on request, and per-image quad strips for the contact sheet.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cli  # noqa: E402
import pipeline  # noqa: E402
from overlay import write_overlay, write_quad  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
INPUTS = REPO / "inputs"
DEBUG = REPO / "debug" / "autotrace"
METRICS = DEBUG / "metrics.json"

LADDER = [
    "house-wide", "butterfly-wide", "boat-tall", "island-tall", "balloon-tall",
    "home-wide", "house-tall", "dinosaur-wide", "landscape-square", "sun-square",
]

# Recorded elsewhere in the repo, for direct comparison in the report table.
REFERENCE = {
    "dinosaur-wide": {"incumbent": 0.02, "prior_autotrace_raw": 3.10,
                      "prior_autotrace_bestfixedwidth": 0.17},
    "landscape-square": {"incumbent": 0.73, "prior_autotrace_raw": 15.61,
                         "prior_autotrace_bestfixedwidth": 1.79},
}


def compare_js(a: Path, b: Path, size=1200) -> float:
    """The incumbent's pixel-diff %, kept verbatim for score continuity."""
    out = DEBUG / "tmp-diff.png"
    r = subprocess.run(
        ["node", str(REPO / "src" / "compare.js"), str(a), str(b), str(size), str(out)],
        capture_output=True, text=True, cwd=REPO,
    )
    for line in r.stdout.splitlines():
        if "differing pixels" in line:
            return float(line.rsplit("= ", 1)[1].rstrip("%"))
    raise RuntimeError(r.stdout + r.stderr)


def load_metrics():
    if METRICS.exists():
        return json.loads(METRICS.read_text())
    return {}


def save_metrics(m):
    METRICS.parent.mkdir(parents=True, exist_ok=True)
    METRICS.write_text(json.dumps(m, indent=1, sort_keys=True))


def run_one(image: str, cfg: pipeline.Config, label: str, keep_svg=True,
            quad=False, overlay=False, graph=False):
    inp = INPUTS / f"{image}.svg"
    t0 = time.perf_counter()
    svg, result = pipeline.run(inp, cfg, cli.SCRATCH)
    wall = time.perf_counter() - t0

    outdir = DEBUG / "runs" / label
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"{image}.svg"
    out.write_text(svg)

    m, _, _ = cli.score_output(inp, svg, result)
    m["compare_js_pct"] = compare_js(inp, out)
    m["runtime_s"] = round(wall, 3)
    m["per_element_s"] = round(wall / max(1, result["n_source_elements"]), 4)
    m["n_source_elements"] = result["n_source_elements"]
    m["failure_tags"] = result.get("failure_tags", {})
    m["config"] = cfg.tag()

    if graph and "graph" in result:
        gdir = DEBUG / "graphs"
        gdir.mkdir(parents=True, exist_ok=True)
        (gdir / f"{image}.json").write_text(json.dumps(result["graph"], indent=1))
    if quad:
        write_quad(inp, svg, DEBUG / "sheets" / "tiles" / f"{label}__{image}.png")
    if overlay:
        write_overlay(inp, svg, DEBUG / "sheets" / "overlays" / f"{label}__{image}.png")
    if not keep_svg:
        out.unlink()
    return m, result, svg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", nargs="*", default=["house-wide"])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--label", required=True)
    ap.add_argument("--quad", action="store_true")
    ap.add_argument("--overlay", action="store_true")
    ap.add_argument("--graph", action="store_true")
    cli.add_args(ap)
    a = ap.parse_args()

    images = LADDER if a.all else a.images
    cfg = cli.build_config(a)
    store = load_metrics()
    store.setdefault(a.label, {"config": cfg.tag(), "images": {}})
    store[a.label]["config"] = cfg.tag()

    rows = []
    for im in images:
        try:
            m, _, _ = run_one(im, cfg, a.label, quad=a.quad, overlay=a.overlay,
                              graph=a.graph)
        except Exception as e:
            traceback.print_exc()
            m = {"error": f"{type(e).__name__}: {e}"}
        store[a.label]["images"][im] = m
        rows.append((im, m))
        save_metrics(store)
        print(f"{im:20s} " + (
            f"ERROR {m['error']}" if "error" in m else
            f"diff {m['compare_js_pct']:6.2f}%  IoU {m['iou']:.4f}  "
            f"bP95 {m['boundary_p95_user']:6.2f}  strokes {m['n_strokes']:4d}  "
            f"{m['runtime_s']:6.1f}s  tags {m['failure_tags']}"
        ), flush=True)

    print(f"\n== {a.label}  ({cfg.tag()}) ==")
    print(f"{'image':20s} {'diff%':>7s} {'IoU':>7s} {'bMed':>6s} {'bP95':>6s} "
          f"{'strokes':>7s} {'ref':>18s}")
    for im, m in rows:
        if "error" in m:
            print(f"{im:20s}  ERROR")
            continue
        ref = REFERENCE.get(im, {})
        reftxt = f"inc {ref['incumbent']}% / at {ref['prior_autotrace_bestfixedwidth']}%" if ref else ""
        print(f"{im:20s} {m['compare_js_pct']:7.2f} {m['iou']:7.4f} "
              f"{m['boundary_median_user']:6.2f} {m['boundary_p95_user']:6.2f} "
              f"{m['n_strokes']:7d} {reftxt:>18s}")


if __name__ == "__main__":
    main()
