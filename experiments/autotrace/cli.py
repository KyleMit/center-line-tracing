#!/usr/bin/env python3
"""One-shot: trace an input SVG, score it, write graph JSON + overlay.

    python3 experiments/autotrace/cli.py inputs/house-wide.svg \
        --mode element --scale 4 --out debug/autotrace/house-wide.svg
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import atrace  # noqa: E402
import metrics  # noqa: E402
import pipeline  # noqa: E402
from overlay import write_overlay  # noqa: E402
from svgio import Document, Renderer  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
DEBUG = REPO / "debug" / "autotrace"
SCRATCH = Path("/tmp/claude-0/-home-user-center-line-tracing/"
               "06888930-c1d3-5025-96f2-3d47c53efe6c/scratchpad/autotrace-work")


def build_config(a) -> pipeline.Config:
    return pipeline.Config(
        mode=a.mode, scale=a.scale, stat=a.stat, endpoint_trim=a.endpoint_trim,
        stroke_scale=a.stroke_scale, cap_extend=a.cap_extend,
        drop_outlines=a.drop_outlines, min_length_px=a.min_length_px,
        outline_frac=a.outline_frac,
        params=atrace.TraceParams(
            corner_threshold=a.corner_threshold,
            error_threshold=a.error_threshold,
            filter_iterations=a.filter_iterations,
            despeckle_level=a.despeckle_level,
            despeckle_tightness=a.despeckle_tightness,
            line_threshold=a.line_threshold,
            preserve_width=a.preserve_width,
        ),
    )


def add_args(p):
    p.add_argument("--mode", default="element", choices=["raw", "color", "element"])
    p.add_argument("--scale", type=float, default=4.0)
    p.add_argument("--stat", default="median", choices=list(__import__("width").STATS))
    p.add_argument("--endpoint-trim", type=float, default=0.0)
    p.add_argument("--stroke-scale", type=float, default=1.0)
    p.add_argument("--cap-extend", action="store_true")
    p.add_argument("--drop-outlines", action="store_true")
    p.add_argument("--min-length-px", type=float, default=0.0)
    p.add_argument("--outline-frac", type=float, default=0.40)
    p.add_argument("--corner-threshold", type=float, default=100.0)
    p.add_argument("--error-threshold", type=float, default=2.0)
    p.add_argument("--filter-iterations", type=int, default=4)
    p.add_argument("--despeckle-level", type=int, default=0)
    p.add_argument("--despeckle-tightness", type=float, default=2.0)
    p.add_argument("--line-threshold", type=float, default=1.0)
    p.add_argument("--preserve-width", action="store_true")


def score_output(input_svg: Path, out_svg_text: str, result: dict, score_scale=1.0):
    """Raster-compare original vs reconstruction on one common frame."""
    doc = Document(input_svg)
    box = (doc.vx, doc.vy, doc.vw, doc.vh)
    s = score_scale * (1200.0 / max(doc.vw, doc.vh))
    r = Renderer(SCRATCH / "score")
    try:
        a, b, frame = metrics.masks(r, box, s, input_svg.read_text(), out_svg_text)
    finally:
        r.close()
    m = metrics.score(a, b, frame.scale)
    m.update(metrics.complexity(result))
    m.update(metrics.width_error(result))
    return m, a, b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--out", default=None)
    ap.add_argument("--overlay", default=None)
    ap.add_argument("--graph", default=None)
    add_args(ap)
    a = ap.parse_args()

    inp = Path(a.input)
    cfg = build_config(a)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    svg, result = pipeline.run(inp, cfg, SCRATCH)

    out = Path(a.out) if a.out else DEBUG / f"{inp.stem}.{cfg.tag()}.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg)

    m, _, _ = score_output(inp, svg, result)
    result["metrics"] = m
    print(json.dumps({"out": str(out), "tag": cfg.tag(), **{
        k: (round(v, 5) if isinstance(v, float) else v)
        for k, v in m.items()}}, indent=2))

    if a.graph and "graph" in result:
        gp = Path(a.graph)
        gp.parent.mkdir(parents=True, exist_ok=True)
        gp.write_text(json.dumps(result["graph"], indent=1))
    if a.overlay:
        write_overlay(inp, svg, Path(a.overlay))
        print("overlay ->", a.overlay)
    (DEBUG / "last-result.json").write_text(
        json.dumps({k: v for k, v in result.items() if k != "graph"}, indent=1, default=str))


if __name__ == "__main__":
    main()
