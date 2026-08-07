# Cross-backend leaderboard

Generated 2026-08-07 18:25:20 · 607.0s wall clock · λ sweep 0.0–10.0 · selection tolerance 10%

Every backend is shown at **its own best setting**, which is the point of the exercise: no backend is penalized for a threshold someone else picked.

* **err** — symmetric difference / source ink area. Lower is better. This is *not* the same scale as `src/compare.js`, which reports differing pixels over the whole canvas; see NOTES.md §3.
* **cx** — complexity index (branches + control points / 100), measured **after canonicalization on both sides**: the automatic path splices degree-2 chains and most published graphs do not, so raw edge counts would credit pruning with a simplification that is only a change of representation.
* **published** — the best variant that track shipped, scored as-is.
* **auto** — automatic width-aware pruning selected by this harness, applied to that track's LEAST-processed variant. Where a track published variants from different libraries or skeletonizers, that variant may not be the same one as `published`, so this column is 'best reachable from the rawest graph', not a controlled pruning A/B. The controlled comparison is `abtest.md`.
* **raster** — colour-independent raster ink diff of the promoted result, as a cross-check on the vector number.


## house-wide

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| autotrace | 0.0363 / 93.4 | 0.0363 / 93.4 | 0.00 | **0.0363** | 0.9639 | 1.34 | 0.0372 | tie |
| flo-mat | 0.0501 / 61.6 | 0.0534 / 42.3 | 1.50 | **0.0501** | 0.9514 | 2.61 | 0.0532 | published better |

## butterfly-wide

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| autotrace | 0.0448 / 94.5 | 0.0479 / 92.4 | 1.00 | **0.0448** | 0.9554 | 1.30 | 0.0479 | published better |
| flo-mat | 0.0989 / 42.9 | 0.1047 / 31.6 | 1.50 | **0.0989** | 0.9063 | 3.75 | 0.1047 | published better |

## boat-tall

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| autotrace | 0.0446 / 110.1 | 0.0454 / 108.9 | 1.50 | **0.0446** | 0.9558 | 0.91 | 0.0459 | auto simpler |
| flo-mat | 0.0722 / 61.6 | 0.0742 / 40.1 | 1.50 | **0.0722** | 0.9307 | 2.19 | 0.0748 | auto simpler |

## island-tall

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| autotrace | 0.0464 / 107.2 | 0.0501 / 103.9 | 5.00 | **0.0464** | 0.9540 | 1.47 | 0.0500 | published better |
| flo-mat | 0.0600 / 75.0 | 0.0604 / 54.5 | 3.00 | **0.0600** | 0.9419 | 2.28 | 0.0599 | auto simpler |

## balloon-tall

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| autotrace | 0.0415 / 136.4 | 0.0430 / 133.1 | 1.50 | **0.0415** | 0.9589 | 0.89 | 0.0427 | auto simpler |
| flo-mat | 0.0913 / 101.5 | 0.0937 / 72.9 | 2.00 | **0.0913** | 0.9133 | 2.38 | 0.0928 | auto simpler |

## home-wide

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| autotrace | 0.0495 / 103.6 | 0.0495 / 103.6 | 0.00 | **0.0495** | 0.9509 | 1.12 | 0.0488 | tie |
| flo-mat | 0.0498 / 96.8 | 0.0498 / 96.8 | 0.00 | **0.0498** | 0.9518 | 2.09 | 0.0493 | auto lower error |

## house-tall

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| autotrace | 0.0451 / 132.8 | 0.0489 / 128.1 | 5.00 | **0.0451** | 0.9553 | 1.43 | 0.0483 | published better |
| flo-mat | 0.0458 / 100.3 | 0.0479 / 71.6 | 1.00 | **0.0458** | 0.9555 | 1.68 | 0.0480 | auto simpler |

## dinosaur-wide

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| flo-mat | 0.0499 / 77.2 | 0.0526 / 75.4 | 1.00 | **0.0499** | 0.9514 | 1.64 | 0.0521 | published better |

## landscape-square

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| flo-mat | 0.0589 / 201.2 | 0.0638 / 152.2 | 1.00 | **0.0589** | 0.9435 | 3.01 | 0.0638 | published better |

## sun-square

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| flo-mat | 0.0341 / 39.7 | 0.0359 / 37.6 | 1.00 | **0.0341** | 0.9669 | 2.62 | 0.0360 | published better |

## Backend ranking (median best-of error across all images)

| backend | images | median err | best err | worst err | auto dominates | auto simpler | tie | published better |
|---|---|---|---|---|---|---|---|---|
| autotrace | 7 | **0.0448** | 0.0363 | 0.0495 | 0 | 2 | 2 | 3 |
| flo-mat | 10 | **0.0589** | 0.0341 | 0.0989 | 0 | 4 | 0 | 5 |
