# Cross-backend leaderboard

Generated 2026-08-07 22:03:46 · 5.3s · tolerance 10% · lambdas 0.0..10.0

`published` = the track's own best variant, scored as it shipped. `auto` = automatic width-aware pruning selected by this harness, starting from that track's least-processed variant.

Error is symmetric difference as a fraction of source ink area (lower is better).


## butterfly-wide

| backend | published err | published IoU | auto err | auto λ | auto IoU | best err | branches | ctrl pts | raster sym |
|---|---|---|---|---|---|---|---|---|---|
| incumbent | 0.1229 | 0.8798 | 0.1229 | 0.00 | 0.8798 | **0.1229** | 22 | 353 | 0.1230 |

## house-tall

| backend | published err | published IoU | auto err | auto λ | auto IoU | best err | branches | ctrl pts | raster sym |
|---|---|---|---|---|---|---|---|---|---|
| incumbent | 0.1162 | 0.8887 | 0.1231 | 5.00 | 0.8821 | **0.1162** | 48 | 377 | 0.1229 |

## sun-square

| backend | published err | published IoU | auto err | auto λ | auto IoU | best err | branches | ctrl pts | raster sym |
|---|---|---|---|---|---|---|---|---|---|
| incumbent | 0.2104 | 0.7958 | 0.2288 | 5.00 | 0.7778 | **0.2104** | 34 | 308 | 0.2281 |

# Automatic pruning vs the tracks' own thresholds

| backend | images | auto better | auto worse | median published err | median auto err | median best-of err |
|---|---|---|---|---|---|---|
| incumbent | 3 | 0 | 2 | 0.1229 | 0.1231 | 0.1229 |
