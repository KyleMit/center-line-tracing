# Cross-backend leaderboard

Generated 2026-08-07 18:57:09 · 1322.9s wall clock · λ sweep 0.0–10.0 · selection tolerance 10%

Every backend is shown at **its own best setting**, which is the point of the exercise: no backend is penalized for a threshold someone else picked.

* **err** — symmetric difference / source ink area. Lower is better. This is *not* the same scale as `src/compare.js`, which reports differing pixels over the whole canvas; see NOTES.md §3.
* **cx** — complexity index (branches + control points / 100), measured **after canonicalization on both sides**: the automatic path splices degree-2 chains and most published graphs do not, so raw edge counts would credit pruning with a simplification that is only a change of representation.
* **published** — the best variant that track shipped, scored as-is.
* **auto** — automatic width-aware pruning selected by this harness, applied to that track's LEAST-processed variant. Where a track published variants from different libraries or skeletonizers, that variant may not be the same one as `published`, so this column is 'best reachable from the rawest graph', not a controlled pruning A/B. The controlled comparison is `abtest.md`.
* **raster** — colour-independent raster ink diff of the promoted result, as a cross-check on the vector number.


## house-wide

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| skimage-skan | 0.0152 / 64.1 | 0.0148 / 44.7 | 1.00 | **0.0148** | 0.9853 | 0.71 | 0.0146 | auto dominates |
| native-geometry | 0.0225 / 97.9 | 0.0221 / 75.4 | 0.50 | **0.0221** | 0.9782 | 1.32 | 0.0220 | auto dominates |
| opencv-tracing | 0.0265 / 70.5 | 0.0287 / 59.2 | 1.00 | **0.0265** | 0.9737 | 1.31 | 0.0287 | published better |
| autotrace | 0.0363 / 93.4 | 0.0363 / 93.4 | 0.00 | **0.0363** | 0.9639 | 1.34 | 0.0372 | tie |
| tegaki | 0.0410 / 28.1 | 0.0566 / 65.6 | 3.00 | **0.0410** | 0.9598 | 2.23 | 0.0558 | published better |
| flo-mat | 0.0501 / 61.6 | 0.0534 / 42.3 | 1.50 | **0.0501** | 0.9514 | 2.61 | 0.0532 | published better |
| polygon-voronoi | 0.1049 / 330.4 | 0.1130 / 115.1 | 2.00 | **0.1049** | 0.8978 | 1.73 | 0.0999 | published better |
| incumbent | 0.1781 / 35.4 | 0.1781 / 35.4 | 0.00 | **0.1781** | 0.8231 | 4.20 | 0.1781 | tie |

## butterfly-wide

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| skimage-skan | 0.0142 / 56.9 | 0.0142 / 56.9 | 0.00 | **0.0142** | 0.9859 | 0.52 | 0.0138 | tie |
| polygon-voronoi | 0.0239 / 334.3 | 0.0238 / 122.7 | 1.00 | **0.0238** | 0.9765 | 0.54 | 0.0237 | auto dominates |
| native-geometry | 0.0268 / 116.0 | 0.0268 / 116.0 | 0.00 | **0.0268** | 0.9734 | 0.48 | 0.0265 | tie |
| opencv-tracing | 0.0272 / 67.7 | 0.0288 / 57.3 | 1.00 | **0.0272** | 0.9730 | 0.88 | 0.0285 | published better |
| autotrace | 0.0448 / 94.5 | 0.0479 / 92.4 | 1.00 | **0.0448** | 0.9554 | 1.30 | 0.0479 | published better |
| tegaki | 0.0636 / 22.8 | 0.0668 / 21.9 | 5.00 | **0.0636** | 0.9387 | 1.30 | 0.0666 | published better |
| flo-mat | 0.0989 / 42.9 | 0.1047 / 31.6 | 1.50 | **0.0989** | 0.9063 | 3.75 | 0.1047 | published better |
| incumbent | 0.1167 / 25.5 | 0.1229 / 25.5 | 5.00 | **0.1167** | 0.8860 | 2.80 | 0.1230 | published better |

## boat-tall

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| skimage-skan | 0.0153 / 88.1 | 0.0160 / 76.9 | 0.50 | **0.0153** | 0.9848 | 0.32 | 0.0160 | auto simpler |
| native-geometry | 0.0196 / 100.3 | 0.0200 / 79.6 | 3.00 | **0.0196** | 0.9805 | 0.36 | 0.0203 | auto simpler |
| autotrace | 0.0446 / 110.1 | 0.0454 / 108.9 | 1.50 | **0.0446** | 0.9558 | 0.91 | 0.0459 | auto simpler |
| tegaki | 0.0543 / 31.2 | 0.0543 / 31.2 | 0.00 | **0.0543** | 0.9477 | 1.06 | 0.0543 | tie |
| flo-mat | 0.0722 / 61.6 | 0.0742 / 40.1 | 1.50 | **0.0722** | 0.9307 | 2.19 | 0.0748 | auto simpler |
| polygon-voronoi | 0.0756 / 325.4 | 0.0778 / 131.5 | 1.50 | **0.0756** | 0.9261 | 0.51 | 0.0688 | auto simpler |
| incumbent | 0.1325 / 35.9 | 0.1325 / 35.9 | 0.00 | **0.1325** | 0.8750 | 2.22 | 0.1318 | tie |

## island-tall

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| skimage-skan | 0.0199 / 99.7 | 0.0217 / 60.9 | 1.00 | **0.0199** | 0.9803 | 0.74 | 0.0217 | published better |
| native-geometry | 0.0263 / 141.2 | 0.0279 / 120.9 | 3.00 | **0.0263** | 0.9740 | 1.10 | 0.0280 | published better |
| autotrace | 0.0464 / 107.2 | 0.0501 / 103.9 | 5.00 | **0.0464** | 0.9540 | 1.47 | 0.0500 | published better |
| tegaki | 0.0548 / 36.1 | 0.0627 / 35.0 | 5.00 | **0.0548** | 0.9470 | 1.85 | 0.0625 | published better |
| flo-mat | 0.0600 / 75.0 | 0.0604 / 54.5 | 3.00 | **0.0600** | 0.9419 | 2.28 | 0.0599 | auto simpler |
| polygon-voronoi | 0.0690 / 392.3 | 0.0720 / 124.4 | 5.00 | **0.0690** | 0.9326 | 0.68 | 0.0658 | auto simpler |
| incumbent | 0.1178 / 44.9 | 0.1285 / 44.9 | 5.00 | **0.1178** | 0.8885 | 2.67 | 0.1282 | published better |

## balloon-tall

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| skimage-skan | 0.0188 / 146.6 | 0.0205 / 87.5 | 1.00 | **0.0188** | 0.9814 | 0.54 | 0.0205 | published better |
| native-geometry | 0.0243 / 143.8 | 0.0243 / 137.6 | 2.00 | **0.0243** | 0.9759 | 0.57 | 0.0240 | auto simpler |
| autotrace | 0.0415 / 136.4 | 0.0430 / 133.1 | 1.50 | **0.0415** | 0.9589 | 0.89 | 0.0427 | auto simpler |
| tegaki | 0.0627 / 54.3 | 0.0645 / 51.2 | 3.00 | **0.0627** | 0.9396 | 1.26 | 0.0641 | auto simpler |
| flo-mat | 0.0913 / 101.5 | 0.0937 / 72.9 | 2.00 | **0.0913** | 0.9133 | 2.38 | 0.0928 | auto simpler |
| polygon-voronoi | 0.0985 / 403.7 | 0.1012 / 157.4 | 1.00 | **0.0985** | 0.9039 | 0.73 | 0.0908 | auto simpler |
| incumbent | 0.1452 / 60.6 | 0.1459 / 60.6 | 3.00 | **0.1452** | 0.8639 | 2.43 | 0.1450 | tie |

## home-wide

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| skimage-skan | 0.0223 / 90.6 | 0.0243 / 51.7 | 1.00 | **0.0223** | 0.9780 | 0.86 | 0.0226 | published better |
| native-geometry | 0.0410 / 124.8 | 0.0410 / 124.8 | 0.00 | **0.0410** | 0.9596 | 1.17 | 0.0400 | tie |
| autotrace | 0.0495 / 103.6 | 0.0495 / 103.6 | 0.00 | **0.0495** | 0.9509 | 1.12 | 0.0488 | tie |
| flo-mat | 0.0498 / 96.8 | 0.0498 / 96.8 | 0.00 | **0.0498** | 0.9518 | 2.09 | 0.0493 | auto lower error |
| tegaki | 0.0622 / 36.9 | 0.0717 / 39.1 | 0.00 | **0.0622** | 0.9400 | 1.64 | 0.0703 | published better |
| polygon-voronoi | 0.1070 / 343.1 | 0.1040 / 141.7 | 0.50 | **0.1040** | 0.8987 | 1.32 | 0.0911 | auto dominates |
| incumbent | 0.1522 / 34.1 | 0.1618 / 34.1 | 5.00 | **0.1522** | 0.8563 | 3.10 | 0.1605 | published better |

## house-tall

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| skimage-skan | 0.0184 / 121.6 | 0.0184 / 121.6 | 0.00 | **0.0184** | 0.9818 | 0.71 | 0.0180 | tie |
| native-geometry | 0.0263 / 167.7 | 0.0286 / 158.4 | 3.00 | **0.0263** | 0.9740 | 1.11 | 0.0289 | published better |
| autotrace | 0.0451 / 132.8 | 0.0489 / 128.1 | 5.00 | **0.0451** | 0.9553 | 1.43 | 0.0483 | published better |
| flo-mat | 0.0458 / 100.3 | 0.0479 / 71.6 | 1.00 | **0.0458** | 0.9555 | 1.68 | 0.0480 | auto simpler |
| polygon-voronoi | 0.0569 / 509.4 | 0.0604 / 155.6 | 1.50 | **0.0569** | 0.9445 | 0.95 | 0.0517 | published better |
| tegaki | 0.0581 / 42.3 | 0.0673 / 43.1 | 5.00 | **0.0581** | 0.9436 | 1.93 | 0.0673 | published better |
| incumbent | 0.1119 / 51.8 | 0.1162 / 51.8 | 3.00 | **0.1119** | 0.8929 | 2.61 | 0.1161 | tie |

## dinosaur-wide

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| skimage-skan | 0.0162 / 117.0 | 0.0162 / 117.0 | 0.00 | **0.0162** | 0.9839 | 0.45 | 0.0159 | tie |
| opencv-tracing | 0.0204 / 129.3 | 0.0204 / 129.3 | 0.00 | **0.0204** | 0.9797 | 0.67 | 0.0194 | tie |
| native-geometry | 0.0336 / 183.5 | 0.0359 / 166.9 | 2.00 | **0.0336** | 0.9671 | 1.10 | 0.0353 | published better |
| polygon-voronoi | 0.0404 / 402.1 | 0.0397 / 210.1 | 1.50 | **0.0397** | 0.9609 | 0.61 | 0.0354 | auto dominates |
| autotrace | 0.0426 / 163.6 | 0.0456 / 157.8 | 5.00 | **0.0426** | 0.9578 | 1.03 | 0.0454 | published better |
| flo-mat | 0.0499 / 77.2 | 0.0526 / 75.4 | 1.00 | **0.0499** | 0.9514 | 1.64 | 0.0521 | published better |
| tegaki | 0.0606 / 49.6 | 0.1031 / 89.1 | 10.00 | **0.0606** | 0.9414 | 1.51 | 0.1027 | published better |
| incumbent | 0.0849 / 244.5 | 0.0870 / 244.5 | 5.00 | **0.0849** | 0.9212 | 1.44 | 0.0872 | tie |

## landscape-square

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| opencv-tracing | 0.0204 / 236.8 | 0.0217 / 217.2 | 0.50 | **0.0204** | 0.9797 | 1.17 | 0.0216 | published better |
| skimage-skan | 0.0262 / 234.6 | 0.0268 / 207.0 | 0.50 | **0.0262** | 0.9743 | 1.61 | 0.0267 | auto simpler |
| autotrace | 0.0403 / 322.0 | 0.0439 / 313.2 | 2.00 | **0.0403** | 0.9600 | 2.27 | 0.0437 | published better |
| native-geometry | 0.0565 / 292.6 | 0.0600 / 270.2 | 1.50 | **0.0565** | 0.9446 | 3.46 | 0.0601 | published better |
| flo-mat | 0.0589 / 201.2 | 0.0638 / 152.2 | 1.00 | **0.0589** | 0.9435 | 3.01 | 0.0638 | published better |
| tegaki | 0.1167 / 84.8 | 0.1189 / 146.8 | 10.00 | **0.1167** | 0.8892 | 5.97 | 0.1187 | tie |
| incumbent | 0.1168 / 487.1 | 0.1191 / 487.1 | 3.00 | **0.1168** | 0.8894 | 5.06 | 0.1186 | tie |

## sun-square

| backend | published err / cx | auto err / cx | λ | best err | IoU | boundary P95 | raster err | verdict |
|---|---|---|---|---|---|---|---|---|
| polygon-voronoi | 0.0150 / 205.9 | 0.0118 / 67.8 | 0.50 | **0.0118** | 0.9883 | 0.43 | 0.0119 | auto dominates |
| flo-mat | 0.0341 / 39.7 | 0.0359 / 37.6 | 1.00 | **0.0341** | 0.9669 | 2.62 | 0.0360 | published better |
| skimage-skan | 0.0380 / 38.9 | 0.0390 / 33.7 | 1.00 | **0.0380** | 0.9631 | 2.33 | 0.0395 | auto simpler |
| autotrace | 0.0523 / 56.6 | 0.0523 / 56.6 | 0.00 | **0.0523** | 0.9488 | 2.73 | 0.0526 | tie |
| native-geometry | 0.0900 / 43.7 | 0.0925 / 41.6 | 1.50 | **0.0900** | 0.9133 | 4.11 | 0.0923 | auto simpler |
| tegaki | 0.1354 / 17.6 | 0.1451 / 16.6 | 5.00 | **0.1354** | 0.8694 | 6.06 | 0.1448 | published better |
| incumbent | 0.2104 / 29.0 | 0.2288 / 29.0 | 5.00 | **0.2104** | 0.7958 | 9.15 | 0.2281 | published better |

## Backend ranking (median best-of error across all images)

| backend | images | median err | best err | worst err | auto dominates | auto simpler | tie | published better |
|---|---|---|---|---|---|---|---|---|
| skimage-skan | 10 | **0.0188** | 0.0142 | 0.0380 | 1 | 3 | 3 | 3 |
| opencv-tracing | 4 | **0.0265** | 0.0204 | 0.0272 | 0 | 0 | 1 | 3 |
| native-geometry | 10 | **0.0268** | 0.0196 | 0.0900 | 1 | 3 | 2 | 4 |
| autotrace | 10 | **0.0448** | 0.0363 | 0.0523 | 0 | 2 | 3 | 5 |
| flo-mat | 10 | **0.0589** | 0.0341 | 0.0989 | 0 | 4 | 0 | 5 |
| tegaki | 10 | **0.0622** | 0.0410 | 0.1354 | 0 | 1 | 2 | 7 |
| polygon-voronoi | 9 | **0.0690** | 0.0118 | 0.1049 | 4 | 3 | 0 | 2 |
| incumbent | 10 | **0.1325** | 0.0849 | 0.2104 | 0 | 0 | 6 | 4 |
