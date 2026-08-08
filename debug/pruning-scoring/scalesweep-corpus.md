# Raster scale against GROUND-TRUTH centerlines

Generated 2026-08-07 22:04:51 · 43.5s · skimage-skan on its own 20-case synthetic corpus, auto-pruned by this layer at each scale.

Every other table in this directory measures *reconstruction* error, which cannot distinguish a smooth path in the wrong place from a smooth path in the right one. These shapes were generated from known centerlines, so this one can. Distances are SVG user units against a stroke radius of 10 (case 19 tapers 6 -> 16).


Both `01-horizontal-line` and `17-near-parallel` report the same numbers at every scale, which looks like a bug and is not: case 17 is two translated copies of case 01's capsule, so the two point-distance sets are identical.


## Medians over the 20 cases

`branches before` is counted after canonicalization but before pruning (the λ=0 candidate), because that is the input pruning actually sees — the published raw counts are higher.

| scale | cases | truth median | truth P95 | invented geometry (recovered->truth P95) | missed geometry (truth->recovered P95) | branches before | branches after pruning |
|---|---|---|---|---|---|---|---|
| 1 | 20 | 0.2511 | 0.5185 | 0.5161 | 0.5186 |     2 |     1 |
| 2 | 20 | 0.1897 | 0.3232 | 0.3017 | 0.3232 |     2 |     1 |
| 4 | 20 | 0.1363 | 0.1882 | 0.1881 | 0.1881 |     2 |     1 |
| 8 | 20 | 0.1332 | 0.2522 | 0.2520 | 0.2522 |     2 |     1 |
| 16 | 20 | 0.1435 | 0.2448 | 0.2434 | 0.2449 |     2 |     1 |

## Truth-centerline median error, per case

| case | scale 1 | scale 2 | scale 4 | scale 8 | scale 16 |
|---|---|---|---|---|---|
| 01-horizontal-line | 0.2563 | 0.1683 | **0.0921** | 0.1976 | 0.1436 |
| 02-diagonal-line | 0.2105 | 0.2018 | 0.1398 | 0.1679 | **0.0410** |
| 03-circular-arc | 0.1974 | 0.2123 | 0.0749 | **0.0535** | 0.0536 |
| 04-s-curve | 0.1791 | 0.2026 | 0.1174 | 0.0694 | **0.0499** |
| 05-tight-u | 0.2294 | 0.2459 | 0.0942 | **0.0539** | 0.1487 |
| 06-closed-loop | 0.1815 | 0.1517 | **0.1292** | 0.1329 | 0.1390 |
| 07-round-cap | 0.2511 | 0.2019 | **0.1013** | 0.1988 | 0.1435 |
| 08-butt-cap | 0.2709 | 0.1709 | 0.2178 | 0.0817 | **0.0401** |
| 09-square-cap | 0.2437 | 0.1466 | 0.0854 | 0.0440 | **0.0220** |
| 10-round-join | 0.2542 | 0.1919 | 0.1608 | 0.1332 | **0.1274** |
| 11-bevel-join | 0.2335 | 0.1803 | **0.1176** | 0.1936 | 0.1832 |
| 12-miter-join | 0.2635 | 0.1897 | 0.1919 | **0.0759** | 0.1453 |
| 13-x-separate | 0.1871 | 0.2198 | 0.1446 | 0.0863 | **0.0354** |
| 14-x-union | 0.1954 | **0.1184** | 0.2140 | 0.1950 | 0.1814 |
| 15-t-junction | 0.2560 | 0.1669 | 0.1455 | 0.1426 | **0.1250** |
| 16-y-junction | 0.2427 | 0.1473 | 0.1363 | 0.0784 | **0.0372** |
| 17-near-parallel | 0.2563 | 0.1683 | **0.0921** | 0.1976 | 0.1436 |
| 18-self-overlap | 0.3284 | **0.1787** | 0.2397 | 0.2189 | 0.2101 |
| 19-variable-width | 0.3782 | 0.2467 | 0.1320 | **0.0877** | 0.1746 |
| 20-noisy-boundary | 0.9002 | **0.6528** | 0.7367 | 0.7289 | 0.7775 |

## Does pruning keep up with the extra resolution?

Branch count before → after automatic pruning. Case 20 is the stress test and the one that answers the question: a single straight capsule under boundary jitter, whose true answer is one branch at every scale.

| case | scale 1 | scale 2 | scale 4 | scale 8 | scale 16 |
|---|---|---|---|---|---|
| 01-horizontal-line | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 |
| 02-diagonal-line | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 |
| 03-circular-arc | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 |
| 04-s-curve | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 |
| 05-tight-u | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 |
| 06-closed-loop | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 |
| 07-round-cap | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 |
| 08-butt-cap | 5 → 1 | 5 → 1 | 5 → 1 | 5 → 1 | 5 → 1 |
| 09-square-cap | 5 → 1 | 5 → 1 | 5 → 1 | 5 → 1 | 5 → 1 |
| 10-round-join | 1 → 1 | 1 → 1 | 1 → 1 | 3 → 3 | 3 → 3 |
| 11-bevel-join | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 | 1 → 1 |
| 12-miter-join | 3 → 1 | 3 → 1 | 3 → 1 | 3 → 1 | 3 → 1 |
| 13-x-separate | 2 → 2 | 2 → 2 | 2 → 2 | 2 → 2 | 2 → 2 |
| 14-x-union | 5 → 5 | 5 → 5 | 5 → 5 | 5 → 5 | 5 → 5 |
| 15-t-junction | 3 → 3 | 3 → 3 | 3 → 3 | 3 → 3 | 3 → 3 |
| 16-y-junction | 3 → 3 | 3 → 3 | 3 → 3 | 3 → 3 | 3 → 3 |
| 17-near-parallel | 2 → 2 | 2 → 2 | 2 → 2 | 2 → 2 | 2 → 2 |
| 18-self-overlap | 2 → 2 | 2 → 2 | 2 → 2 | 2 → 2 | 2 → 2 |
| 19-variable-width | 1 → 1 | 1 → 1 | 1 → 1 | 3 → 3 | 1 → 1 |
| 20-noisy-boundary | 20 → 1 | 23 → 4 | 43 → 4 | 106 → 21 | 201 → 59 |
