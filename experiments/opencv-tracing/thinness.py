"""Audit how 8-thin each skeletonizer's output actually is.

    python3 experiments/opencv-tracing/thinness.py [target ...]

A "1-pixel skeleton" is supposed to be 8-thin: apart from endpoints and
junctions, every pixel should have exactly two 8-neighbours, and no three
mutually-adjacent pixels should form a triangle. Anything else is residue that
downstream graph analysis will read as real topology.

This exists because `cv2.ximgproc.thinning(THINNING_ZHANGSUEN)` turned out to
fail that test badly while `THINNING_GUOHALL` and both scikit-image
skeletonizers pass it — which is the single most consequential difference
between the two OpenCV variants, and it is invisible in reconstruction IoU.

Writes `debug/opencv-tracing/thinness.json`.
"""

from __future__ import annotations

import json
import sys

import numpy as np
from skimage.morphology import skeletonize

import bench
import pipeline
import svgraster
import tracers

NEIGHBOURS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def audit(skeleton: np.ndarray) -> dict:
    ys, xs = np.nonzero(skeleton)
    points = set(zip(ys.tolist(), xs.tolist()))

    degrees = []
    triangles = 0
    for (y, x) in points:
        neighbours = [(y + dy, x + dx) for dy, dx in NEIGHBOURS
                      if (y + dy, x + dx) in points]
        degrees.append(len(neighbours))
        for i in range(len(neighbours)):
            for j in range(i + 1, len(neighbours)):
                a, b = neighbours[i], neighbours[j]
                if max(abs(a[0] - b[0]), abs(a[1] - b[1])) == 1:
                    triangles += 1

    degrees = np.array(degrees) if degrees else np.zeros(0, int)
    return {
        "pixels": int(len(points)),
        "endpoints": int(np.count_nonzero(degrees == 1)),
        "degree3Plus": int(np.count_nonzero(degrees >= 3)),
        # Each triangle is counted once from each of its three corners.
        "triangles": triangles // 3,
        "trianglesPerKilopixel": (triangles / 3) / max(1, len(points)) * 1000,
    }


SKELETONIZERS = {
    "cv2.ximgproc.thinning(ZHANGSUEN)": lambda m: pipeline.thin(m, "zhangsuen"),
    "cv2.ximgproc.thinning(GUOHALL)": lambda m: pipeline.thin(m, "guohall"),
    "skimage.skeletonize(zhang)": lambda m: skeletonize(m, method="zhang"),
    "skimage.skeletonize(lee)": lambda m: skeletonize(m, method="lee"),
}


def main():
    targets = bench.resolve_targets(sys.argv[1:] or None)
    results = {}

    for target in targets:
        rasters, _ = svgraster.rasterize_elements(
            target["path"].read_text(), bench.MASKS / target["name"] / "s4", 4.0)
        per_skeletonizer = {}
        for label, fn in SKELETONIZERS.items():
            totals = {"pixels": 0, "endpoints": 0, "degree3Plus": 0, "triangles": 0,
                      "bespokeEdges": 0, "stcEdges": 0}
            for raster in rasters:
                skeleton = fn(raster.mask)
                stats = audit(skeleton)
                for key in ("pixels", "endpoints", "degree3Plus", "triangles"):
                    totals[key] += stats[key]
                totals["bespokeEdges"] += len(tracers.bespoke(skeleton))
                totals["stcEdges"] += len(tracers.st_c(skeleton))
            totals["trianglesPerKilopixel"] = (
                totals["triangles"] / max(1, totals["pixels"]) * 1000)
            per_skeletonizer[label] = totals
        results[target["name"]] = per_skeletonizer
        print(f"\n{target['name']}")
        for label, totals in per_skeletonizer.items():
            print(f"  {label:<38} px {totals['pixels']:6d}  deg>=3 {totals['degree3Plus']:5d}"
                  f"  triangles {totals['triangles']:5d}"
                  f"  ({totals['trianglesPerKilopixel']:6.1f}/kpx)"
                  f"  edges: bespoke {totals['bespokeEdges']:5d} st-c {totals['stcEdges']:4d}")

    out = bench.DEBUG / "thinness.json"
    out.write_text(json.dumps(results, indent=1))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
