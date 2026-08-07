# Path complexity and wobble

Medians across each backend's promoted graphs. `wobble` is RMS perpendicular
deviation from the path's own one-stroke-width low-pass with the curvature bias
removed, in stroke radii — an exact line scores 0.000, an exact arc 0.002.

| backend | points / width | wobble | turning / width | reversals / width | reads as |
|---|---|---|---|---|---|
| incumbent | 0.56 | 0.0250 | 0.154 | 0.06 | smooth |
| tegaki | 0.83 | 0.0334 | 0.294 | 0.12 | smooth |
| flo-mat | 1.33 | 0.0292 | 0.198 | 0.09 | smooth |
| skimage-skan | 2.20 | 0.0195 | 0.224 | 0.20 | drawn in one motion |
| opencv-tracing | 5.00 | 0.0204 | 0.310 | 0.35 | smooth |
| native-geometry | 10.33 | 0.0192 | 0.203 | 0.06 | drawn in one motion |
| autotrace | 14.04 | 0.0244 | 0.216 | 0.08 | smooth |
| polygon-voronoi | 15.75 | 0.0170 | 0.206 | 0.07 | drawn in one motion |

## One shared stroke — house-wide

The longest stroke every backend recovered, so the geometry is held fixed.

| backend | control points | length | points / width | wobble |
|---|---|---|---|---|
| incumbent | 21 | 1314 | 0.29 | 0.0111 |
| tegaki | 36 | 1310 | 0.58 | 0.0109 |
| flo-mat | 61 | 1317 | 0.97 | 0.0154 |
| skimage-skan | 116 | 1318 | 1.85 | 0.0104 |
| opencv-tracing | 336 | 1324 | 5.28 | 0.0141 |
| native-geometry | 473 | 1317 | 7.53 | 0.0096 |
| autotrace | 756 | 1317 | 11.84 | 0.0077 |
| polygon-voronoi | 1321 | 1319 | 20.99 | 0.0099 |
