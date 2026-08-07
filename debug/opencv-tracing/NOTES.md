# Track 6 — OpenCV thinning + `skeleton-tracing`

**Slug:** `opencv-tracing` · **Branch:** `claude/centerline-opencv-tracing` ·
Report §6.6, §6.8, §4.4, §18.6/18.10

This track is the **speed-and-portability** path. It is not trying to top the
leaderboard; it is trying to say precisely what portability costs in quality,
measured against Track 3 (scikit-image `medial_axis`) on identical masks.

---

## 1. The rasterization contract — Track 3 must match this

Tracks 3 and 6 are a controlled comparison (Euclidean medial axis vs
morphological thinning). Common Setup says whichever pushes first records its
settings and the other matches. **Track 6 pushed first; these are the settings.**

| Knob | Value |
|---|---|
| Renderer | `@resvg/resvg-js` **2.6.2** (report §7.1 — chosen for determinism, §15) |
| `fitTo` | `{ mode: 'zoom', value: scale }` — **not** `'width'`; `'width'` rescales when you crop |
| Default scale | `4.0` (raster pixels per SVG user unit) |
| Unit of work | one **filled element**, not the whole drawing, not merged by colour |
| Crop | element bbox expanded by `pad = 4.0` user units, then **snapped outward onto the global canvas pixel grid** |
| Background | opaque black `<rect>` at the padded bbox, inside the SVG |
| Shape fill | `#ffffff`, all stroke/fill attributes stripped from the source element |
| Antialiasing | resvg default (shape AA on) |
| Threshold | `red > 128` |
| Pixel → SVG | `svg = cropOrigin + (pixelIndex + 0.5) / scale` |
| Fonts | `loadSystemFonts: false` (determinism) |

Implementation: `experiments/opencv-tracing/rasterize.mjs` +
`svgraster.py`. Import `svgraster.rasterize_elements()` directly if you want
byte-identical masks — it is not track-specific.

**Two things worth stealing:**

1. **Crop, don't render the full canvas.** Report §16 says to, and it is worth
   28x: 19 elements of `house-wide.svg` took **35.0 s** rendered full-canvas
   (6648x3784 each) and **1.23 s** cropped. The masks are identical where it
   matters.
2. **Snap the crop to the global pixel grid.** Without snapping, resvg rounds a
   fractional crop origin and every element lands up to half a pixel off its true
   position. Compositing the crops back onto the full canvas scored IoU 0.9938;
   with snapping, 0.99990. That half pixel is a systematic bias in every
   centerline the pipeline produces, and it is invisible unless you check.

---

## 2. What this backend is

```
SVG
 → resvg mask, per filled element          (contract above)
 → cv2.ximgproc.thinning                   ZHANGSUEN | GUOHALL
 → skeleton-tracing                        C | Python | JS, all vendored
 → radius from a separate cv2.distanceTransform, sampled along the polylines
 → common graph model (report §13)
 → re-stroked SVG
```

Versions pinned for reproducibility: OpenCV **5.0.0**
(`opencv-contrib-python-headless`, Apache-2.0), skeleton-tracing
**LingDong-/skeleton-tracing @ f5dd65e** (MIT), resvg-js **2.6.2**,
scikit-image **0.26.0** (comparison only), shapely **2.1.2**.

### Radius is DERIVED, not native — and the graph JSON says so

This is the known tradeoff, stated up front (report §4.4, §6.6). Morphological
thinning returns a 1-pixel skeleton **and nothing else**. Track 3's
`medial_axis(..., return_distance=True)` hands back the local radius at every
skeleton pixel as part of the same call; this track has to compute
`cv2.distanceTransform(DIST_L2, DIST_MASK_PRECISE)` separately and sample it
bilinearly along the traced polylines.

Every graph this track emits carries:

```json
"radius": { "native": false, "derivedFrom": "cv2.distanceTransform(...) sampled ..." }
```

Track 8 should treat `radius.native` as a first-class field. The *values* are
good (see §6) — the point is that the cost and the failure modes are different,
and a consumer that assumes native radii will be wrong about which stage to
blame.

---

## 3. Vendoring notes

`skeleton-tracing` is **not on npm** (confirmed). Vendored from GitHub under
`experiments/opencv-tracing/vendor/skeleton-tracing/` with its MIT `LICENSE`:

- `py/trace_skeleton.py` — upstream's pure-Python implementation, verbatim.
  Upstream calls it "the super slow ... just for reference" and means it.
- `js/trace_skeleton.vanilla.js` — upstream's vanilla JS, verbatim (plus a
  three-line `package.json` marking it ESM, since this repo is CommonJS).
- `c/trace_skeleton.c` — upstream's SWIG-targeted C, verbatim.
- `c/st_shim.c` — **ours**, ~40 lines. `#include`s the upstream .c untouched and
  adds two entry points: `trace_pre_thinned()` (upstream's `trace()` runs its own
  Zhang-Suen first, which would undo the OpenCV skeleton we want to measure) and
  `pop_polyline()` (drains a whole polyline per ctypes call instead of one point
  at a time). **No SWIG needed** — `build.sh` compiles it to a `.so` and
  `tracers.py` calls it with ctypes. That is a materially easier integration
  path than upstream's `swig/compile.sh`, which is hardcoded to a macOS
  Homebrew Python 3.7.

---

## 4. Findings

### 4.1 Cap extension: march to the boundary and you overshoot by exactly one radius

Thinning stops short of a cap, so a naive fix is "walk the terminal end outward
along its tangent until you leave the mask." That is **wrong for round caps** and
measurably so. For a round cap of radius R the correct centerline endpoint is the
cap circle's *centre*, which is R inside the shape's tip. Marching to the tip
overshoots by R and the re-stroke spills past the original outline:

| case-01 horizontal capsule, Zhang-Suen | IoU | sym% | boundary P95 |
|---|---|---|---|
| no cap extension | 0.9574 | 4.31 | 2.850 |
| extend to boundary | 0.9334 | 7.13 | 4.500 |
| **extend to boundary − R** | **0.9810** | **1.93** | **0.500** |

Same on case-07 (round cap, width 34): 0.9446 → 0.9090 (boundary) →
**0.9883** (boundary − R). Track 1's handoff flags cap extension as a required
post-step for flo-mat; this is the raster equivalent, and the sign of the
correction is easy to get wrong.

Butt and square caps want the boundary target instead, and neither reaches the
round-cap scores because the emitted stroke is round-capped by construction
(case-08 tops out at IoU 0.940, case-09 at 0.950). That is a limitation of the
output model, not of thinning.

### 4.2 `cap artifact` cannot be measured from the distance transform

Worth recording because it is an inviting mistake. The distance transform at a
skeleton endpoint is **not** diagnostic of cap pull-back: along a constant-width
stroke's axis the nearest boundary is the side wall, so `DT ≈ R` everywhere on
the axis, at the true cap centre and a hundred pixels inside it alike.

The rule that does work, and the one used here: march outward from the terminal
end along its tangent and measure the distance to the mask boundary. A correctly
terminated round cap exits at exactly `R`. Anything beyond `1.25 R` is pull-back.
Track 3 should use the same rule so the counts compare.

### 4.3 Corpus case 5 was wrong, and only the render showed it

`_arc(cx, cy, r, 180, 360)` sweeps *upward* in SVG's y-down convention. The
"tight U curve" was therefore an arch whose legs crossed it — the case was
silently testing two accidental T junctions, and scored like it (IoU 0.957, 5
edges, 3 tags). Corrected to sweep `180 → 0`: IoU 0.977, 1 edge, 0 tags.

The numbers alone looked like a backend failure at a tight bend. Common Setup's
"always look at the rendered output" earned its place here.

### 4.4 Radius profile interpolation must follow arc length, not vertex index

After a Douglas-Peucker pass the polyline vertices are wildly unevenly spaced —
on case-19 the five surviving vertices sit at x = 246, 236, 235, 63, 62. Scoring
a variable-width re-stroke by interpolating the radius array over vertex index
therefore reports the wrong width across most of the stroke. Interpolating over
cumulative arc length instead: case-19 IoU **0.785 → 0.936**.

This is a scoring bug, not an extraction bug, but any track emitting `radii`
alongside a simplified `geometry` has it, so it is worth flagging to Track 8:
**a per-vertex radius array is only meaningful with the arc-length positions of
those vertices.**

### 4.5 skeleton-tracing emits a redundant vertex pair at every chunk seam

The algorithm is chunked (`csize`, default 10) and concatenates fragments without
merging collinear runs, so a geometrically straight skeleton comes back as dozens
of collinear points — 256 vertices for one straight 800 px line. Vertex count
scales as `2 x skeleton_length / csize`:

| `csize` | 5 | 10 | 20 | 40 | 80 |
|---|---|---|---|---|---|
| vertices (case-01) | 280 | 256 | 128 | 64 | 32 |

A Douglas-Peucker pass at **0.5 px** — half the raster's own resolution, so it
cannot move the polyline further than the raster can resolve — takes that same
straight line from 256 vertices to 4. That is the default here (`simplify_px:
0.5`). It is cleanup, not smoothing: raising the tolerance into the multi-pixel
range would be pruning, which is Track 8's job.

### 4.6 OpenCV's Zhang-Suen does not return an 8-thin skeleton

The largest finding of the track, and the reason the default here is Guo-Hall.
`cv2.ximgproc.thinning(THINNING_ZHANGSUEN)` leaves hundreds of 8-connected
triangles on curved strokes — up to 547 per kilopixel — while `THINNING_GUOHALL`,
`skimage.skeletonize(zhang)` and `skimage.skeletonize(lee)` leave essentially
none. Reconstruction IoU does not notice; degree-based graph analysis is
destroyed. Full evidence, audit tool and consequences in §6.2.

---

## 5. Failure-tag rules (exact, so Track 3's counts compare)

Also machine-readable in `metrics.json` under `classifierRules`.

| Tag | Rule |
|---|---|
| `cap artifact` | degree-1 end that stops more than `1.25 R_med` short of the shape's tip, measured by marching outward along the terminal tangent (see §4.2) |
| `join artifact` | terminal edge with `L/(2 R_med) < 1.5` whose far end is within `2.5 R_med` of a junction node |
| `outline noise branch` | terminal edge with `L/(2 R_med) < 0.75` **not** near a junction |
| `crossing ambiguity` | node of degree ≥ 4 |
| `disconnected skeleton` | traced components in excess of the mask's own component count |
| `missing narrow segment` | mask component of area > `4 R_global²` containing no skeleton pixel |
| `wrong endpoint` | ground-truth path end with no recovered degree-1 endpoint within one stroke width (synthetic corpus only) |
| `excessive curve complexity` | edge carrying more than 6 vertices per stroke width |
| `raster quantization` | edge longer than `4 R_med` that, after a 0.5 px DP pass, still needs a direction change more often than every 7 px |

---

## 6. Results

Default config: **Guo-Hall** thinning, `st-c` tracer, `csize` 10, 0.5 px
Douglas-Peucker, round cap extension, raster scale 4. Regenerate everything with:

```bash
python3 experiments/opencv-tracing/build.sh          # once, builds the vendored .so
python3 experiments/opencv-tracing/bench.py --save   # metrics.json, graphs, SVGs
python3 experiments/opencv-tracing/speed.py          # runtime + cross-runtime agreement
python3 experiments/opencv-tracing/thinness.py       # the 8-thinness audit
python3 experiments/opencv-tracing/make_sheets.py    # contact sheets
python3 experiments/opencv-tracing/report.py         # these tables
```

### 6.1 Headline: runtime

This is the number the track exists to produce, and it is **smaller than expected**.

### Runtime

Masks: **3.7 Mpx** across 7 elements, best of 3.

| stage | implementation | seconds | Mpx/s | vs OpenCV ZS |
|---|---|---:|---:|---:|
| skeletonize | `cv2.ximgproc.thinning(ZHANGSUEN)` | 0.386 | 9.6 | 1.00x |
| skeletonize | `cv2.ximgproc.thinning(GUOHALL)` | 0.484 | 7.7 | 1.25x |
| skeletonize | `skimage.medial_axis(return_distance=True)` | 0.683 | 5.4 | 1.77x |
| skeletonize | `skimage.skeletonize(method='zhang')` | 0.270 | 13.7 | 0.70x |
| skeletonize | `skimage.skeletonize(method='lee')` | 0.772 | 4.8 | 2.00x |
| skeletonize | `cv2.distanceTransform (radius recovery)` | 0.013 | 284.6 | 0.03x |
| trace | `st-c` | 0.043 | 85.4 | measured on 3.7 Mpx |
| trace | `st-js` | 0.917 | 4.0 | measured on 3.7 Mpx |
| trace | `bespoke` | 0.150 | 24.7 | measured on 3.7 Mpx |
| trace | `st-py` | 5.210 | 0.1 | measured on 0.4 Mpx |

Tracers are compared by throughput (Mpx/s), not by wall time: each is measured on as many masks as its own budget allowed, because the pure-script implementations cannot process the full set in reasonable time.

**cv2.ximgproc.thinning is only 1.8x faster than the primitive it is supposed to
beat.** `skimage.medial_axis(return_distance=True)` runs at 5.4 Mpx/s against
OpenCV Zhang-Suen's 9.6 and Guo-Hall's 7.7 — and medial_axis returns the distance
field *in the same call*, which this track has to buy separately. That extra call
is nearly free (`cv2.distanceTransform` at 285 Mpx/s, 3% of the thinning cost), so
the honest comparison is 7.7+285 vs 5.4 Mpx/s: **about 1.4x for Guo-Hall, 1.8x for
Zhang-Suen.**

Worse for the premise: `skimage.skeletonize(method='zhang')` is *faster than
either OpenCV variant* at 13.7 Mpx/s. If raw skeletonization speed is what you
want in Python, OpenCV is not where you get it.

Two things that are genuinely fast here and worth keeping:

- **`st-c` tracing at 85 Mpx/s** — 2x the incumbent's hand-rolled tracer (24.7)
  and 21x the JS port. Tracing is not the bottleneck in any configuration.
- **The whole extraction pipeline is ~0.15-0.46 s per filled element** on real
  artwork (2.9 s for house-wide's 19 elements, 6.9 s for dinosaur's 33). Nothing
  here is slow in absolute terms.

**Verdict on speed: this track's reason to exist is weaker than the report
assumed.** The report's §16 framing is right that pixel count dominates, but the
constant factor between OpenCV and scikit-image is small, and it does not survive
the fact that scikit-image hands you the distance field for free. Speed alone does
not justify choosing this backend over Track 3.

### 6.2 Zhang-Suen vs Guo-Hall — use Guo-Hall

Nobody had compared these. The answer is not close, but it is **not visible in
reconstruction error** — which is why it needed the dedicated audit in
`thinness.py`.

`cv2.ximgproc.thinning(THINNING_ZHANGSUEN)` **does not return an 8-thin
skeleton on curved strokes.** A "1-pixel skeleton" should have exactly two
8-neighbours per pixel away from endpoints and junctions, and no three mutually
adjacent pixels. OpenCV's Zhang-Suen violates this massively; Guo-Hall and both
scikit-image skeletonizers do not:

| case | skeletonizer | px | deg>=3 px | 8-conn triangles | per kpx |
|---|---|---:|---:|---:|---:|
| circular-arc | **cv2 ZHANGSUEN** | 991 | **432** | **280** | **282.5** |
| circular-arc | cv2 GUOHALL | 851 | 0 | 0 | 0.0 |
| circular-arc | skimage zhang | 850 | 0 | 0 | 0.0 |
| circular-arc | skimage lee | 852 | 0 | 0 | 0.0 |
| y-junction | **cv2 ZHANGSUEN** | 1586 | **1161** | **867** | **546.7** |
| y-junction | cv2 GUOHALL | 1145 | 4 | 2 | 1.7 |
| closed-loop | **cv2 ZHANGSUEN** | 2188 | **850** | **528** | **241.3** |
| closed-loop | cv2 GUOHALL | 1918 | 0 | 0 | 0.0 |
| x-crossing-separate | cv2 ZHANGSUEN | 1440 | 0 | 0 | 0.0 |

Full audit in `thinness.json`. The defect appears on **curved** strokes and is
absent on straight diagonals (case 13), which is why it is easy to miss.

The consequence is severe for anything that reads skeleton topology. Feeding the
incumbent's degree-based tracer the two skeletons:

| case | bespoke tracer on cv2 ZS | on cv2 GH | on skimage |
|---|---:|---:|---:|
| circular-arc | **713 edges** | 1 | 1 |
| closed-loop | **1378 edges** | 1 | 1 |
| y-junction | **2030 edges** | 8 | 6 |
| house-wide | **13 263 edges** | — | — |

Reconstruction IoU barely notices (Zhang-Suen even wins the synthetic IoU count
13-3, by margins of 0.003-0.018), because `skeleton-tracing` is robust to the
residue and dense pixel chains re-stroke fine. **On the real ladder the two are
indistinguishable** — house-wide 0.06% vs 0.07%, dinosaur 0.02% vs 0.01%,
butterfly 0.14% vs 0.14% pixel diff.

So: identical reconstruction, one produces a usable graph and one does not.
**Guo-Hall, and it is not a close call.** The Zhang-Suen IoU edge on synthetic
curves is real but tiny, and buying it with a corrupt skeleton is a bad trade in a
project whose architecture (report §19) is built on a shared graph layer.

**Warning for Track 3 and Track 8:** if anyone feeds `cv2.ximgproc.thinning`
Zhang-Suen output into Skan, or into any degree-based branch analysis, the result
will be garbage and the reconstruction score will not tell them.

### 6.3 Real ladder

### Real ladder

| image | elements | IoU | sym % | pixel diff % | edges | vertices | extract s | s/element | tags |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| house-wide | 19 | 0.9625 | 3.89 | **0.07** | 48 | 2245 | 2.87 | 0.151 | join artifact 9, cap artifact 4, crossing ambiguity 1, excessive curve complexity 22 |
| dinosaur-wide | 33 | 0.9638 | 3.73 | **0.01** | 88 | 4134 | 6.87 | 0.208 | outline noise branch 1, join artifact 12, cap artifact 2, excessive curve complexity 17 |
| butterfly-wide | 13 | 0.9578 | 4.27 | **0.14** | 39 | 2970 | 6.00 | 0.461 | join artifact 8, cap artifact 4, excessive curve complexity 18 |

Pixel-diff % is the incumbent's own `src/compare.js` at 1200 px, so it is directly
comparable with its published numbers. **dinosaur-wide 0.01% beats the incumbent's
best-known 0.02%**; house-wide is 0.07%.

Caveat on the contact sheets: the "preview diff" figure printed on the sheet tiles
is a coarse 900 px alpha-threshold diff computed by `sheets.py`, **not** the
compare.js number, and the two are not comparable. The compare.js numbers are in
`pixel-diff.json` and the table above.

landscape-square and sun-square were measured under the Zhang-Suen default only
(`metrics-thinning-sweep.json`: landscape IoU 0.9498, 175 edges, 103 tags; sun
IoU 0.9262, 32 edges) and were not re-run under the Guo-Hall default before the
session ended. Their numbers should be regenerated before being quoted.

### 6.4 Synthetic corpus

### Synthetic corpus — default config (guohall, st-c, cap=round)

| # | case | IoU | sym % | bound P95 | cl→gt P95 | gt→cl P95 | cov | E | V | tags |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | horizontal-line | 0.9827 | 1.75 | 0.50 | 0.175 | 0.131 | 1.000 | 1 | 6 | — |
| 2 | diagonal-line | 0.9909 | 0.92 | 0.25 | 0.171 | 0.154 | 1.000 | 1 | 46 | — |
| 3 | circular-arc | 0.9782 | 2.20 | 0.56 | 0.368 | 0.361 | 0.996 | 1 | 60 | — |
| 4 | s-curve | 0.9807 | 1.94 | 0.56 | 0.462 | 0.460 | 1.000 | 1 | 81 | — |
| 5 | tight-u-curve | 0.9805 | 1.98 | 0.56 | 0.522 | 0.518 | 1.000 | 1 | 54 | — |
| 6 | closed-loop | 0.9801 | 2.01 | 0.35 | 0.424 | 0.399 | 1.000 | 1 | 176 | cap artifact 2, excessive curve complexity 1 |
| 7 | round-cap | 0.9891 | 1.10 | 0.35 | 0.175 | 0.139 | 1.000 | 1 | 6 | — |
| 8 | butt-cap | 0.9401 | 6.03 | 4.65 | 0.175 | 13.568 | 0.768 | 1 | 6 | — |
| 9 | square-cap | 0.9502 | 5.01 | 4.50 | 0.175 | 0.139 | 1.000 | 1 | 6 | — |
| 10 | round-join | 0.9499 | 5.05 | 4.95 | 2.003 | 7.366 | 0.823 | 1 | 11 | — |
| 11 | bevel-join | 0.9566 | 4.37 | 3.75 | 2.003 | 7.366 | 0.823 | 1 | 11 | — |
| 12 | miter-join | 0.9450 | 5.55 | 4.95 | 2.003 | 7.366 | 0.823 | 1 | 11 | — |
| 13 | x-crossing-separate | 0.9986 | 0.14 | 0.00 | 0.122 | 0.061 | 1.000 | 2 | 10 | — |
| 14 | x-crossing-union | 0.9986 | 0.14 | 0.00 | 0.121 | 0.061 | 1.000 | 5 | 21 | excessive curve complexity 1 |
| 15 | t-junction | 0.9808 | 1.94 | 0.50 | 0.810 | 1.397 | 0.943 | 3 | 17 | wrong endpoint 1 |
| 16 | y-junction | 0.9851 | 1.51 | 0.50 | 0.749 | 0.717 | 0.987 | 3 | 24 | wrong endpoint 3 |
| 17 | near-parallel | 0.9827 | 1.75 | 0.50 | 0.175 | 0.131 | 1.000 | 2 | 12 | — |
| 18 | self-overlap | 0.9464 | 5.57 | 2.75 | 3.527 | 4.459 | 0.726 | 9 | 114 | join artifact 2, excessive curve complexity 5 |
| 19 | variable-width | 0.7078 | 33.93 | 6.25 | 0.153 | 0.139 | 1.000 | 1 | 5 | — |
| 20 | noisy-boundary | 0.8994 | 11.05 | 4.56 | 9.548 | 0.665 | 1.000 | 29 | 188 | join artifact 16, excessive curve complexity 15 |

`cl→gt` and `gt→cl` are the two directed centerline distances in SVG user units
(stroke width is 20, so 0.5 is 2.5% of a stroke width). Reading them:

- **Cases 1-7, 13, 14, 17 are essentially solved** — sub-pixel centerline error,
  one edge per stroke, no tags. The X crossing scores 0.9986 whether the two
  strokes are kept separate (case 13) or boolean-unioned (case 14), which is the
  best single result in the corpus and a genuinely good sign for junctions.
- **Case 8 (butt cap) is the clearest structural failure**: `gt→cl P95` of 13.6
  against 0.175 in the other direction. The recovered centerline is *on* the true
  path but stops short of it, because the pipeline emits round caps and extends
  terminal ends to the round-cap target. Nothing is wrong with the extraction —
  the output model cannot represent a butt cap. Same story, milder, for case 9.
- **Cases 10-12 (joins) lose the corner**: `gt→cl P95` 7.4, coverage 0.82. The
  skeleton rounds off the outside of a 90-degree corner. This is the classic
  thinning join behaviour and it is the largest remaining *geometric* error on
  clean input.
- **Case 19 (variable width) at 0.708 constant-width IoU** is the output model
  again, not extraction — see §6.5, where the derived profile recovers it to 0.94.
- **Case 20 (noisy boundary) is the spurious-branch case**, and it behaves as
  designed: 29 edges and 16 `join artifact` tags from a shape whose true answer is
  one stroke. This is exactly the input Track 8's pruning should consume.

### 6.5 Derived radius — it works, except at junctions

### Derived radius: constant width vs the sampled profile

| case | constant-width IoU | derived-profile IoU | Δ |
|---|---:|---:|---:|
| case-01-horizontal-line | 0.9827 | 0.9827 | +0.0000 |
| case-02-diagonal-line | 0.9909 | 0.9907 | -0.0002 |
| case-03-circular-arc | 0.9782 | 0.9772 | -0.0010 |
| case-04-s-curve | 0.9807 | 0.9803 | -0.0005 |
| case-05-tight-u-curve | 0.9805 | 0.9796 | -0.0009 |
| case-06-closed-loop | 0.9801 | 0.9805 | +0.0004 |
| case-07-round-cap | 0.9891 | 0.9891 | +0.0000 |
| case-08-butt-cap | 0.9401 | 0.9401 | +0.0000 |
| case-09-square-cap | 0.9502 | 0.9502 | +0.0000 |
| case-10-round-join | 0.9499 | 0.9478 | -0.0021 |
| case-11-bevel-join | 0.9566 | 0.9546 | -0.0021 |
| case-12-miter-join | 0.9450 | 0.9429 | -0.0020 |
| case-13-x-crossing-separate | 0.9986 | 0.9988 | +0.0002 |
| case-14-x-crossing-union | 0.9986 | 0.8556 | -0.1430 |
| case-15-t-junction | 0.9808 | 0.9698 | -0.0110 |
| case-16-y-junction | 0.9851 | 0.9702 | -0.0149 |
| case-17-near-parallel | 0.9827 | 0.9827 | +0.0000 |
| case-18-self-overlap | 0.9464 | 0.9287 | -0.0177 |
| case-19-variable-width | 0.7078 | 0.9406 | +0.2328 |
| case-20-noisy-boundary | 0.8994 | 0.9622 | +0.0628 |
| house-wide | 0.9625 | 0.9563 | -0.0061 |
| dinosaur-wide | 0.9638 | 0.9624 | -0.0014 |
| butterfly-wide | 0.9578 | 0.9292 | -0.0287 |

Sampling a separately-computed distance transform along the traced polylines
recovers width well enough to be useful:

- **Case 19 (variable width): 0.708 → 0.941.** The derived profile captures a
  4→17 unit radius ramp that a constant width cannot represent at all. This is the
  main evidence that "derived rather than native" is a real cost but not a
  crippling one.
- **Case 20 (noisy): 0.899 → 0.962.**
- On clean constant-width strokes the two are identical to ±0.002, as they should
  be.

**But it fails at junctions, and predictably**: case 14 (X crossing) drops
0.9986 → 0.8556, case 16 (Y) 0.985 → 0.970, case 18 (self-overlap) 0.946 → 0.929.
The reason is structural: at a crossing the largest inscribed circle is much
bigger than the stroke half-width, so the distance transform reports a radius that
is correct for the *shape* and wrong for the *stroke*. A native MAT has exactly
the same property — this is not a thinning artifact — but it means **per-vertex
radius must not be used raw near a junction**. Track 8 should prefer the
per-edge `medianRadius` (which is robust to it, being a median over the edge) or
mask out a junction neighbourhood of ~R before taking the profile.

### 6.6 skeleton-tracing vs the incumbent's hand-rolled tracer

Same skeletons, three runtimes of the vendored library plus the incumbent's tracer
ported verbatim. Run under the **Zhang-Suen** default, which is what makes the
difference so stark (`metrics-tracer.json`):

| target | tracer | IoU | edges | vertices | trace s |
|---|---|---:|---:|---:|---:|
| circular-arc | st-c | 0.9867 | **1** | 66 | 0.004 |
| circular-arc | st-js | 0.9868 | **1** | 62 | 0.113 |
| circular-arc | bespoke | 0.9877 | **713** | 1500 | 0.015 |
| y-junction | st-c | 0.9886 | **3** | 50 | 0.007 |
| y-junction | bespoke | 0.9878 | **2030** | 4072 | 0.033 |
| house-wide | st-c | 0.9653 | **36** | 2060 | 0.228 |
| house-wide | bespoke | 0.9756 | **13 263** | 30 143 | 0.611 |

Two findings:

1. **The vendored library matches the bespoke tracer on geometry and beats it
   decisively on graph quality.** IoU differs by less than 0.01 in both
   directions, but the incumbent's tracer emits three orders of magnitude more
   edges on a non-8-thin skeleton because it assumes clean pixel degrees. On
   Guo-Hall skeletons the bespoke tracer is fine (1 edge on the arc) — the
   explosion is an interaction, not a straight defect. Still, robustness to
   imperfect skeletons is worth having, and **replacing the bespoke tracer with
   the vendored one simplifies the architecture at no measured cost.**
2. **`bespoke` sometimes scores *higher* IoU while producing 13 263 edges.** That
   is a clean demonstration of report §11's advice to prefer the simpler graph at
   comparable geometry error — IoU alone would have picked the wrong tracer.

### 6.7 Portability — the ports are close, but NOT identical

### Cross-runtime agreement

| runtime | target | bit-identical | same polyline count | max deviation (px) |
|---|---|---|---|---:|
| `st-py` | case-01-horizontal-line | yes | yes | 0.00 |
| `st-py` | case-03-circular-arc | **no** | yes | 0.00 |
| `st-py` | case-04-s-curve | skipped (too slow) | — | — |
| `st-py` | case-06-closed-loop | skipped (too slow) | — | — |
| `st-py` | case-14-x-crossing-union | skipped (too slow) | — | — |
| `st-py` | case-16-y-junction | skipped (too slow) | — | — |
| `st-py` | case-20-noisy-boundary | skipped (too slow) | — | — |
| `st-js` | case-01-horizontal-line | yes | yes | 0.00 |
| `st-js` | case-03-circular-arc | **no** | yes | 5.00 |
| `st-js` | case-04-s-curve | **no** | yes | 2.83 |
| `st-js` | case-06-closed-loop | **no** | yes | 1.41 |
| `st-js` | case-14-x-crossing-union | yes | yes | 0.00 |
| `st-js` | case-16-y-junction | yes | yes | 0.00 |
| `st-js` | case-20-noisy-boundary | **no** | **no** | 4.47 |

This is the claim the track exists to test, and the answer is **qualified**:

- **Topology is preserved** — same polyline count on 6 of 7 targets, and the one
  exception (case 20, the deliberately noisy shape) differs by one polyline out of
  eight.
- **The output is not bit-identical.** The JS port deviates from the C port by up
  to 5.0 px on curved skeletons (1.25 user units at scale 4, ~6% of a stroke
  width). The pure-Python port differs from C in polyline *grouping* on the arc
  while placing every point identically (max deviation 0.00 px).
- Straight lines and junction cases (1, 14, 16) are exactly identical; curves are
  where the ports diverge.

**Practical consequence:** you can move this pipeline to the browser and get the
same drawing, but you cannot cache results across runtimes, diff outputs across
runtimes, or expect a server-side and client-side extraction to agree
byte-for-byte. For a rendering pipeline that is fine. For anything that treats the
centerline as a stable identifier it is not.

`st-js` also costs 21x the C implementation's throughput here (4.0 vs 85 Mpx/s),
though a meaningful part of that is node process startup in this harness rather
than the algorithm.

---

## 7. Verdict

**This track does not earn its place on speed, and it earns a qualified pass on
portability.**

- **Speed (the stated value proposition): does not hold up.** 1.4-1.8x over
  `medial_axis`, and `skimage.skeletonize(zhang)` is faster than either OpenCV
  variant. Since medial_axis returns the distance field in the same call, Track 3
  gets a better-specified result for a comparable price. If the report's §18.6
  ranking rested on OpenCV being "very fast", that premise is not supported by
  measurement on this workload.
- **Portability: real, with an asterisk.** Same topology across C, Python and JS;
  not bit-identical on curves. This remains the only pipeline here that runs
  unchanged in a browser, and that is a genuine architectural option nothing else
  offers.
- **Quality: competitive, and better than expected.** dinosaur-wide 0.01% pixel
  diff beats the incumbent's 0.02%; house-wide 0.07%; the junction cases (13-16),
  which were this track's first target and the place thinning was supposed to look
  worst, are the strongest results in the corpus (0.9986 / 0.9986 / 0.9808 /
  0.9851). Thinning's spurious-branch reputation shows up mainly on genuinely
  noisy boundaries (case 20), where it is the pruning layer's problem, not the
  skeletonizer's.
- **The most valuable thing this track produced is not about speed at all**: it is
  §6.2, the discovery that OpenCV's Zhang-Suen is not 8-thin. That silently
  destroys graph-based analysis while leaving reconstruction scores intact, and it
  would have been very expensive for another track to debug from the far end.

**Recommendation:** keep this backend as the *portability* option and as a fast
second opinion in a hybrid ensemble (report §19), not as the default raster
backend. Track 3 should win on the merits of the retained distance field. If a
client-side or cross-language path is ever needed, this is the candidate, it works,
and the quality cost is small — but configure it with **Guo-Hall**.

### What is not done

- landscape-square and sun-square were not re-measured under the Guo-Hall default
  (§6.3).
- Raster-resolution sensitivity (`--matrix scale`) was not swept; the `scale` and
  `csize` matrices exist in `bench.py` but were not run. Resolution dependence is
  a known structural weakness of any raster backend and remains unquantified here.
- No Bezier fitting — this track emits polylines, so `excessive curve complexity`
  counts are not comparable with a track that fits curves.
- Pruning was deliberately not implemented (Common Setup's working rules). Case 20
  and the `join artifact` counts on real artwork are the inputs Track 8 needs.

---

## 7. Negative results and dead ends

- **`fitTo: {mode: 'width'}` + `cropByBBox` do not compose.** Cropping changes the
  aspect ratio resvg fits to, so a cropped render at `mode: 'width'` silently
  comes out at a different scale than the uncropped one. Use `mode: 'zoom'`.
- **resvg-js `BBox` objects cannot be constructed from JS** (`Failed to recover
  BBox type from napi value`), so crop padding cannot be applied by expanding the
  bbox directly. Workaround: draw an opaque background `<rect>` at the padded
  rectangle — it both supplies the mask background and *defines* the crop.
- **Upstream's SWIG build path is not worth fighting.** `swig/compile.sh` hardcodes
  a macOS Homebrew Python 3.7 prefix. A ~40-line ctypes shim over the same C file
  is less code, has no SWIG dependency, and is faster to call.
