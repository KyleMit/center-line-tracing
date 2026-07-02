#!/usr/bin/env python3
"""Synthetic check: a zigzag stroke's traced centerline should reach its apex.

Builds a V-shaped stroke mask (polyline with an acute turn) the same way the
drawing app would render it (round caps/joins), skeletonizes it, and verifies
that corner tip-mode recovers a single path whose turn reaches the true apex.
"""
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from skimage.morphology import skeletonize

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from convert_filled_svg_to_stroked_lines import trace_skeleton_paired  # noqa: E402


def stroke_mask(size, pts, radius):
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    mask = np.zeros((size, size), dtype=bool)
    for (y1, x1), (y2, x2) in zip(pts, pts[1:]):
        vy, vx = y2 - y1, x2 - x1
        L2 = vy * vy + vx * vx
        t = np.clip(((yy - y1) * vy + (xx - x1) * vx) / L2, 0, 1)
        d2 = (yy - (y1 + t * vy)) ** 2 + (xx - (x1 + t * vx)) ** 2
        mask |= d2 <= radius * radius
    return mask


def main():
    size = 220
    radius = 9.0
    apex = (110.0, 170.0)
    pts = [(60.0, 40.0), apex, (160.0, 40.0)]  # acute V pointing right
    mask = stroke_mask(size, pts, radius)

    skel = skeletonize(mask)
    dt = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)

    for tip_mode in ("excursion", "corner"):
        paths = trace_skeleton_paired(
            skel, pair_dot_cutoff=-0.2, overlap_spur_max_pixels=80,
            tip_mode=tip_mode, dt=dt, radius_px=radius,
        )
        paths = [p for p in paths if len(p) > 5]
        best = min(
            (min(math.hypot(y - apex[0], x - apex[1]) for y, x in p) for p in paths),
            default=float("inf"),
        )
        print(f"{tip_mode}: {len(paths)} paths, closest approach to apex = {best:.2f}px")
        if tip_mode == "corner":
            assert len(paths) == 1, f"expected one merged path, got {len(paths)}"
            assert best < 2.0, f"corner mode should reach the apex, got {best:.2f}px"
    print("tip corner test OK")


if __name__ == "__main__":
    main()
