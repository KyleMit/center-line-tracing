#!/usr/bin/env python3
"""Emit the recommended skimage-skan output for every real drawing.

    python3 experiments/pruning-scoring/recommended.py

"Recommended" is what `scalesweep.md` concluded: raster scale 8 everywhere except
`sun-square` and `landscape-square`, which are better at scale 2 — plus this
layer's automatic width-aware pruning at whatever strength the selector picks.

The pruning is applied *inside skimage-skan's own graph model* rather than by
re-rendering the clg graph, because clg's writer collapses an edge to one median
radius and dense polylines. The backend's emitter keeps per-vertex width and the
Bézier fit, which is the whole reason its output is 34x lighter than the
incumbent's — re-rendering through the generic writer would show a worse drawing
than the pipeline actually produces.

Surviving-edge bookkeeping needs the merge provenance: canonicalization splices
degree-2 chains, so a kept branch carries its neighbours' ids in `mergedFrom`
rather than keeping them as separate edges. Matching on the spliced id alone
would drop most of the drawing.

Writes debug/pruning-scoring/recommended/<image>.svg and a manifest.json.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "experiments" / "skimage-skan"))

from clg import CenterlineGraph, select, smoothness, svgio  # noqa: E402

OUT = REPO / "debug" / "pruning-scoring" / "recommended"
LAMBDAS = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0)

IMAGES = [
    "house-wide", "butterfly-wide", "boat-tall", "island-tall", "balloon-tall",
    "home-wide", "house-tall", "dinosaur-wide", "landscape-square", "sun-square",
]

# From debug/pruning-scoring/scalesweep.md. The two exceptions are the drawings
# with thin tapering detail, where a finer raster resolves taper tails into
# skeleton structure that pruning then has to guess about.
SCALE = {img: 8.0 for img in IMAGES}
SCALE["sun-square"] = 2.0
SCALE["landscape-square"] = 2.0


def build(image: str) -> dict:
    import emit  # noqa: PLC0415
    import extract  # noqa: PLC0415
    import svgio as skan_svgio  # noqa: PLC0415

    scale = SCALE[image]
    src_svg = REPO / "inputs" / f"{image}.svg"
    doc = skan_svgio.load(src_svg)

    t0 = time.time()
    cfg = extract.ExtractConfig(scale=scale, method="medial-axis", simplify_eps=0.15)
    graph, _ = extract.extract_document(doc, cfg)
    emit.fit_beziers(graph, width_mode="piecewise")
    seconds = time.time() - t0

    fills = {f"e{e.index}": e.fill for e in doc.elements}
    edges_before = len(graph.edges)

    # score + select in the common layer
    tmp = OUT / "_graphs" / f"{image}.json"
    graph.save(tmp)
    src = svgio.load_source(src_svg)
    chosen, cands = select.select(CenterlineGraph.load(tmp), src, lambdas=LAMBDAS)
    raw = next((c for c in cands if c.lam == 0.0), None)

    kept: set[str] = set()
    for e in chosen.graph.edges.values():
        kept.add(e.id)
        kept.update(e.extra.get("mergedFrom", []))
    graph.edges = [e for e in graph.edges if e.id in kept]

    svg_text = emit.stroked_svg(graph, fills, use_beziers=True, piecewise=True)
    out_svg = OUT / f"{image}.svg"
    out_svg.parent.mkdir(parents=True, exist_ok=True)
    out_svg.write_text(svg_text)

    s = smoothness.graph_smoothness(chosen.graph)
    return {
        "image": image,
        "scale": scale,
        "lam": chosen.lam,
        "viewBox": graph.viewBox,
        "svg": str(out_svg.relative_to(REPO)),
        "source": f"inputs/{image}.svg",
        "seconds": round(seconds, 1),
        "edgesBeforePruning": edges_before,
        "edgesEmitted": len(graph.edges),
        "error": round(chosen.error, 4),
        "errorUnpruned": round(raw.error, 4) if raw else None,
        "iou": round(chosen.metrics.iou, 4),
        "controlPoints": chosen.metrics.control_points,
        "wobble": round(s.wiggle, 4),
        "pointsPerWidth": round(s.verts_per_width, 2),
        "grade": smoothness.naturalness_grade(s)[0],
        "bytes": len(svg_text),
        "sourceBytes": (REPO / "inputs" / f"{image}.svg").stat().st_size,
    }


def main() -> int:
    records = []
    for image in IMAGES:
        rec = build(image)
        records.append(rec)
        print(f"  {rec['image']:18s} scale {rec['scale']:g}  lam {rec['lam']:4.2f}  "
              f"err {rec['error']:.4f}  wobble {rec['wobble']:.4f}  "
              f"{rec['edgesEmitted']:4d} strokes  {rec['bytes'] // 1024:3d} KB "
              f"({rec['seconds']}s)", flush=True)
    (OUT / "manifest.json").write_text(json.dumps(records, indent=1))
    print(f"\nwrote {len(records)} SVGs -> {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
