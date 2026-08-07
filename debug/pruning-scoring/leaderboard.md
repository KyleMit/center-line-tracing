# Cross-backend leaderboard

Generated 2026-08-07 18:15:06 · 6.6s · tolerance 10% · lambdas 0.0..10.0

`published` = the track's own best variant, scored as it shipped. `auto` = automatic width-aware pruning selected by this harness, starting from that track's least-processed variant.

Error is symmetric difference as a fraction of source ink area (lower is better).


## house-wide

| backend | published err | published IoU | auto err | auto λ | auto IoU | best err | branches | ctrl pts | raster sym |
|---|---|---|---|---|---|---|---|---|---|
| incumbent | 0.1781 | 0.8231 | 0.1781 | 0.00 | 0.8231 | **0.1781** | 33 | 235 | 0.1781 |

# Automatic pruning vs the tracks' own thresholds

| backend | images | auto better | auto worse | median published err | median auto err | median best-of err |
|---|---|---|---|---|---|---|
| incumbent | 1 | 0 | 0 | 0.1781 | 0.1781 | 0.1781 |
