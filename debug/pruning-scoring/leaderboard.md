# Cross-backend leaderboard

Generated 2026-08-07 17:42:06 · 122.8s · tolerance 10% · lambdas 0.0..10.0

`published` = the track's own best variant, scored as it shipped. `auto` = automatic width-aware pruning selected by this harness, starting from that track's least-processed variant.

Error is symmetric difference as a fraction of source ink area (lower is better).


## house-wide

| backend | published err | published IoU | auto err | auto λ | auto IoU | best err | branches | ctrl pts | raster sym |
|---|---|---|---|---|---|---|---|---|---|
| native-geometry | 0.0225 | 0.9778 | 0.0221 | 0.50 | 0.9782 | **0.0221** | 39 | 3643 | 0.0220 |
| skimage-skan | 0.0243 | 0.9760 | 0.0247 | 1.00 | 0.9756 | **0.0243** | 55 | 1114 | 0.0241 |
| opencv-tracing | 0.0330 | 0.9674 | 0.0350 | 0.75 | 0.9654 | **0.0330** | 48 | 2245 | 0.0350 |
| autotrace | 0.0370 | 0.9633 | 0.0370 | 0.00 | 0.9633 | **0.0370** | 25 | 6843 | 0.0377 |
| tegaki | 0.0410 | 0.9598 | 0.0566 | 3.00 | 0.9448 | **0.0410** | 25 | 505 | 0.0472 |
| flo-mat | 0.0553 | 0.9468 | 0.0634 | 1.50 | 0.9389 | **0.0553** | 297 | 861 | 0.0626 |
| polygon-voronoi | 0.1106 | 0.8925 | 0.1185 | 2.00 | 0.8841 | **0.1106** | 239 | 9135 | 0.1057 |
| incumbent | 0.1676 | 0.8336 | 0.1781 | 5.00 | 0.8231 | **0.1676** | 37 | 245 | 0.1781 |

# Automatic pruning vs the tracks' own thresholds

| backend | images | auto better | auto worse | median published err | median auto err | median best-of err |
|---|---|---|---|---|---|---|
| autotrace | 1 | 0 | 0 | 0.0370 | 0.0370 | 0.0370 |
| flo-mat | 1 | 0 | 1 | 0.0553 | 0.0634 | 0.0553 |
| incumbent | 1 | 0 | 1 | 0.1676 | 0.1781 | 0.1676 |
| native-geometry | 1 | 1 | 0 | 0.0225 | 0.0221 | 0.0221 |
| opencv-tracing | 1 | 0 | 1 | 0.0330 | 0.0350 | 0.0330 |
| polygon-voronoi | 1 | 0 | 1 | 0.1106 | 0.1185 | 0.1106 |
| skimage-skan | 1 | 0 | 1 | 0.0243 | 0.0247 | 0.0243 |
| tegaki | 1 | 0 | 1 | 0.0410 | 0.0566 | 0.0410 |
