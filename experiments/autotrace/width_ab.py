#!/usr/bin/env python3
"""The controlled A/B this whole track exists to run.

Hold the traced GEOMETRY fixed, and vary only how stroke width is chosen:

  A. one global width for the whole drawing, swept  -- what the earlier
     autotrace evaluation did, and the basis of its 0.17% / 1.79% numbers;
  B. per-path width measured from the source distance transform -- this track.

Because only the widths differ, any gap between the best A and B is attributable
to width recovery alone and to nothing else.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cli  # noqa: E402
import pipeline  # noqa: E402
from bench import compare_js  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
DEBUG = REPO / "debug" / "autotrace"


def set_global_width(svg: str, w: float) -> str:
    return re.sub(r'stroke-width="[^"]*"', f'stroke-width="{w:.3f}"', svg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", nargs="*",
                    default=["house-wide", "dinosaur-wide", "landscape-square"])
    ap.add_argument("--widths", nargs="*", type=float, default=None)
    cli.add_args(ap)
    a = ap.parse_args()
    cfg = cli.build_config(a)
    cfg.global_width = 0.0

    out = {}
    tmp = DEBUG / "ab"
    tmp.mkdir(parents=True, exist_ok=True)

    for im in a.images:
        inp = REPO / "inputs" / f"{im}.svg"
        svg, result = pipeline.run(inp, cfg, cli.SCRATCH)
        per_path_svg = tmp / f"{im}.perpath.svg"
        per_path_svg.write_text(svg)
        b = compare_js(inp, per_path_svg)

        widths = a.widths
        if widths is None:
            # sweep around the widths actually present in the drawing
            ws = [w for g in result["groups"] for w in g.get("width_user", [])]
            lo, hi = (min(ws), max(ws)) if ws else (2.0, 40.0)
            n = 13
            widths = [lo + (hi - lo) * i / (n - 1) for i in range(n)]

        rows = []
        for w in widths:
            f = tmp / f"{im}.gw{w:.2f}.svg"
            f.write_text(set_global_width(svg, w))
            rows.append({"width": round(w, 3), "compare_js_pct": compare_js(inp, f)})
            f.unlink()
            print(f"  {im}  global w={w:7.2f} -> {rows[-1]['compare_js_pct']:6.2f}%",
                  flush=True)
        best = min(rows, key=lambda r: r["compare_js_pct"])
        out[im] = {
            "per_path_pct": b,
            "best_global_width": best["width"],
            "best_global_pct": best["compare_js_pct"],
            "improvement_factor": round(best["compare_js_pct"] / b, 2) if b else None,
            "width_range_in_drawing": [round(min(ws), 2), round(max(ws), 2)] if ws else None,
            "sweep": rows,
        }
        print(f"{im}: per-path {b:.2f}%   best global {best['compare_js_pct']:.2f}% "
              f"@ w={best['width']:.2f}   -> {out[im]['improvement_factor']}x\n", flush=True)

    p = DEBUG / "width-ab.json"
    p.write_text(json.dumps(out, indent=1))
    print("->", p)


if __name__ == "__main__":
    main()
