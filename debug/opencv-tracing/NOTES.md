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

*(filled in as benchmark runs land — see `metrics.json`)*

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
