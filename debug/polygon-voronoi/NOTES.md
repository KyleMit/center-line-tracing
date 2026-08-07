# Track 4 — PyGeoOps + fitodic polygon-Voronoi centerlines

**Slug** `polygon-voronoi` · **Branch** `claude/centerline-polygon-voronoi-u6py64`
· Report §6.3, §6.4, §4.2 · Tier 1 rank 4 + Tier 3 rank 9

Versions: `pygeoops 0.6.0`, `centerline 1.1.1` (fitodic), `shapely 2.1.2`,
`svgelements`, `numpy 2.4.6`, Python 3.11.

---

## Verdict up front

**PyGeoOps is a genuinely good centerline backend for this artwork, but only
after turning off its default output simplification. fitodic adds nothing.**

1. `pygeoops.centerline`'s **default `simplifytolerance=-0.25` is the single
   largest error source** on curved strokes — larger than the Voronoi
   approximation and larger than Bézier flattening put together. Setting it to
   `0` cuts median centerline error on the synthetic corpus from **2.27 → 0.000
   units** and lifts real-artwork IoU from **0.828 → 0.960**, at identical edge
   count and identical runtime. Anyone evaluating PyGeoOps at its defaults will
   wrongly conclude the library is inaccurate.
2. **PyGeoOps' width-relative branch filter is competitive with bespoke
   pruning** on these shapes — see the Track 8 section below. It is the reason
   to prefer PyGeoOps over fitodic, and essentially the *only* reason.
3. **fitodic is PyGeoOps' Voronoi minus the pruning.** Bolting PyGeoOps'
   own `_remove_short_branches` onto fitodic's output makes the two
   indistinguishable (IoU within ±0.006, identical edge counts), at 3–5× the
   runtime. There is no case in this corpus for using fitodic.
4. **The residual error on the hardest images is the width model, not the
   centerline.** Re-stroking from the per-edge radius *profile* instead of one
   median radius takes sun-square from 8.10% → 2.18% symmetric difference and
   landscape-square from 5.93% → 2.91%, with the *same* centerline.
5. Against the incumbent (`src/compare.js`, identical settings), this backend
   **beats it on landscape-square and sun-square** and is 3–4× behind on
   dinosaur-wide, at 0.008–0.041 s/element with no rasterization anywhere.

---

## Headline numbers

### Raster pixel-diff vs the incumbent (`node src/compare.js in out N`)

| image | incumbent 700 / 1200 | this track, median-radius | this track, variable-radius |
|---|---|---|---|
| dinosaur-wide | 0.01% / **0.02%** | 0.06% / 0.08% | 0.06% / **0.07%** |
| landscape-square | 0.43% / **0.73%** | 0.26% / 0.45% | 0.24% / **0.25%** |
| sun-square | 5.03% / **6.26%** | 1.46% / 2.46% | 0.94% / **1.46%** |

Two of the three incumbent benchmarks are beaten; sun-square by 4.3×.

### Full ladder — pygeoops, tol 0.15, densify −0.25, min_branch_length −1.0, simplify 0, extend False

| image | IoU | IoU (var-width) | symdiff% | edges | terminals | junctions | bdist P95 | s/element | total s |
|---|---|---|---|---|---|---|---|---|---|
| house-wide | 0.9775 | 0.9752 | 2.27 | 37 | 35 | 11 | 1.32 | 0.0103 | 0.20 |
| butterfly-wide | 0.9649 | 0.9704 | 3.52 | 25 | 13 | 9 | 0.53 | 0.0171 | 0.22 |
| boat-tall | 0.9780 | 0.9735 | 2.22 | 30 | 34 | 4 | 0.32 | 0.0166 | 0.36 |
| island-tall | 0.9726 | 0.9715 | 2.77 | 43 | 42 | 14 | 0.49 | 0.0114 | 0.27 |
| balloon-tall | 0.9740 | 0.9721 | 2.62 | 65 | 54 | 20 | 0.46 | 0.0136 | 0.38 |
| home-wide | 0.9634 | 0.9681 | 3.69 | 50 | 54 | 14 | 1.02 | 0.0080 | 0.22 |
| house-tall | 0.9731 | 0.9706 | 2.71 | 56 | 40 | 20 | 0.98 | 0.0113 | 0.31 |
| dinosaur-wide | 0.9652 | 0.9753 | 3.55 | 70 | 91 | 15 | 1.10 | 0.0115 | 0.48 |
| landscape-square | 0.9422 | 0.9709 | 5.93 | 131 | 79 | 59 | 3.54 | 0.0376 | 0.53 |
| sun-square | 0.9228 | 0.9782 | 8.10 | 30 | 16 | 14 | 3.85 | 0.0406 | 0.08 |

`metrics-pygeoops.json`, `metrics-fitodic.json`, `metrics-fitodic-filtered.json`.

### Three-way, same inputs and same downstream code

| image | pygeoops IoU / edges / s | fitodic IoU / edges / s | fitodic+filter IoU / edges / s |
|---|---|---|---|
| house-wide | 0.9775 / 37 / 0.20 | 0.9813 / **239** / 0.75 | 0.9774 / 37 / 0.89 |
| dinosaur-wide | 0.9652 / 70 / 0.48 | 0.9675 / **253** / 1.32 | 0.9662 / 70 / 1.36 |
| landscape-square | 0.9422 / 131 / 0.53 | 0.9535 / **865** / 2.42 | 0.9416 / 129 / 2.77 |
| sun-square | 0.9228 / 30 / 0.08 | 0.9252 / **167** / 0.37 | 0.9232 / 30 / 0.38 |

Raw fitodic scores *higher* IoU everywhere while producing 5–7× more edges.
That is report §11's warning in one table: **IoU rewards the hairball**, because
hundreds of spurious branches still cover real ink. Weigh complexity against it
or you will pick the wrong backend.

---

## The 2-D result surface (flattening tolerance × library knob)

Synthetic corpus, all 20 cases, median centerline Hausdorff **P95** in user units
(stroke width 24 unless noted). Full grids in `sweep-synthetic.json`,
`sweep-synth-branch0.json`, `sweep-real.json`.

### pygeoops `simplifytolerance` × flattening tolerance — the dominant axis

| simplifytolerance ↓ / tol → | 0.05 | 0.15 | 0.5 | 1.5 | 4.0 |
|---|---|---|---|---|---|
| **−0.25 (library default)** | 2.273 | 2.273 | 2.275 | 2.266 | 2.262 |
| −0.10 | 0.314 | 0.350 | 0.319 | 0.370 | 0.376 |
| −0.05 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| −0.02 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| **0 (off)** | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

Same, median IoU: 0.928 at the default vs 0.997 with it off. Edge count is **1**
in every cell — simplification buys no simplicity here, it only loses geometry.
Douglas–Peucker at 0.25 × average width (= 6 units on a 24-unit stroke) turns a
circular arc into chords.

### pygeoops `min_branch_length` × flattening tolerance (with simplify = 0)

Median edges across 20 cases:

| min_branch_length ↓ / tol → | 0.05 | 0.15 | 0.5 | 1.5 | 4.0 |
|---|---|---|---|---|---|
| −2.0 | 1 | 1 | 1 | 1 | 1 |
| **−1.0** | 1 | 1 | 1 | 1 | 1 |
| −0.5 | 1 | 1 | 1 | 1 | 1 |
| −0.25 | 2 | 2 | 2 | 2 | 2 |
| 0 (off) | 3 | 3 | 3 | 3 | 4 |

and median centerline P95: 0.000 for every negative value, 0.081–0.142 at 0.

### fitodic `interpolation_distance` × flattening tolerance

Median P95 / median edges:

| interp ↓ / tol → | 0.05 | 0.15 | 0.5 | 1.5 | 4.0 |
|---|---|---|---|---|---|
| 0.25 | 7.25 / 134 | 7.92 / 116 | 7.89 / 67 | 7.14 / 40 | 6.38 / 23 |
| 0.5 | 3.94 / 130 | 6.34 / 82 | 6.39 / 67 | 6.24 / 40 | 5.61 / 23 |
| 1.0 | 0.10 / 55 | 2.78 / 67 | 4.43 / 41 | 4.28 / 40 | 4.15 / 23 |
| 2.0 | 0.04 / 17 | 0.09 / 17 | 1.08 / 27 | 1.79 / 20 | 2.33 / 19 |
| 4.0 | 0.09 / 9 | 0.10 / 7 | 0.20 / 12 | 0.61 / 15 | 1.95 / 15 |

fitodic gets *better* as its sampling gets **coarser** — the opposite of the
usual intuition, and a direct demonstration of the report's §4.2 warning that
Voronoi quality is driven by boundary sampling. Fine sampling means more
boundary points, which means more spurious Voronoi branches. On real artwork at
`interpolation_distance=0.25` it produces a **median 3178 edges per drawing**.

### The flattening-tolerance finding, which is not what the handoff predicted

The handoff expected flattening tolerance to be a first-class trade-off. It is
first-class for *shape fidelity* but nearly irrelevant for *centerline accuracy*
with PyGeoOps, because **PyGeoOps re-densifies the boundary itself** before
building the Voronoi (`densify_distance`, default −1 = one average width). Our
flattening only matters once it is coarser than that re-densification.

Shape cost of flattening alone, `flatten_iou` vs a 0.02-unit reference:

| case | 0.05 | 0.15 | 0.5 | 1.5 | 4.0 |
|---|---|---|---|---|---|
| 03-arc | 0.9985 | 0.9958 | 0.9918 | 0.9660 | 0.8696 |
| 06-loop | 0.9991 | 0.9979 | 0.9893 | 0.9559 | 0.8322 |
| 01-line | 1.0000 | 0.9998 | 0.9989 | 0.9956 | 0.9837 |

Practical rule for this corpus: **tolerance ≤ 1% of stroke width** (0.15–0.25 on
24-unit strokes) costs < 0.5% IoU and nothing measurable in centerline error.
Above ~6% of stroke width the polygon itself is wrong and everything degrades.
Real-artwork sweep agrees: IoU 0.960 at tol 0.1, 0.958 at 0.25, 0.946 at 0.75,
0.920 at 2.0.

`densify_distance` is the knob that actually controls Voronoi quality: −0.5 and
−0.25 both give 0.000 median error; −1.0 (the library default) gives 0.53–0.62;
`0` (use our flattened points as-is) gives 0.23–0.27 but the worst IoU (0.958),
because our flattening spaces points by curvature rather than uniformly.

---

## Per-case synthetic results at the chosen settings

tol 0.15, densify −0.25, min_branch_length −1.0, simplify 0, extend False.
`clP50`/`clP95`/`clMAX` = predicted-vs-true centerline distance, user units.

| case | edges | term | clP50 | clP95 | clMAX | IoU | width bias |
|---|---|---|---|---|---|---|---|
| 01-line | 1 | 2 | 0.000 | 0.000 | 0.000 | 1.0000 | 0.0% |
| 02-diagonal | 1 | 2 | 0.000 | 0.000 | 0.002 | 1.0000 | 0.0% |
| 03-arc | 1 | 2 | 0.033 | 0.068 | 0.068 | 0.9974 | −0.2% |
| 04-s-curve | 1 | 2 | 0.031 | **0.574** | 0.644 | 0.9856 | −0.5% |
| 05-u-tight | 1 | 2 | 0.000 | 0.034 | 0.056 | 0.9995 | 0.0% |
| 06-loop | 1 | **0** | 0.013 | 0.047 | 0.052 | 0.9955 | −0.5% |
| 07-cap-round | 1 | 2 | 0.000 | 0.000 | 0.000 | 0.9999 | 0.0% |
| 08-cap-butt | 1 | 2 | 0.000 | **4.000** | **20.000** | 0.9730 | 0.0% |
| 09-cap-square | 1 | 2 | 0.000 | 0.000 | 0.000 | 0.9760 | 0.0% |
| 10-join-round | 1 | 2 | 0.000 | 0.000 | 4.457 | 0.9946 | 0.0% |
| 11-join-bevel | 1 | 2 | 0.000 | 0.000 | 6.806 | 0.9978 | 0.0% |
| 12-join-miter | 1 | 2 | 0.000 | 0.000 | 4.457 | 0.9912 | 0.0% |
| 13-x-separate | 2 | 4 | 0.000 | 0.000 | 0.004 | 1.0000 | 0.0% |
| 14-x-union | 4 | 4 | 0.000 | 0.000 | 0.000 | 0.9999 | 0.0% |
| 15-t-junction | 3 | 3 | 0.000 | 0.000 | 2.683 | 0.9995 | 0.0% |
| 16-y-junction | 3 | 3 | 0.000 | 0.000 | 2.430 | 0.9995 | 0.0% |
| 17-parallel-near | 2 | 4 | 0.000 | 0.000 | 0.000 | 0.9999 | 0.0% |
| 18-self-overlap | 3 | 2 | 0.001 | 0.342 | 2.627 | 0.9940 | 0.0% |
| 19-variable-width | 1 | 2 | 0.000 | 0.000 | **19.238** | **0.7206** | −2.9% |
| 20-noisy-boundary | 1 | 2 | 0.018 | 0.066 | 0.819 | 0.9948 | −0.2% |

**Topology is exactly right on every junction case**: X-union → 4 edges,
T → 3, Y → 3, X-separate → 2, near-parallel → 2 in 2 components, loop → 1 edge
and 0 terminals. Derived radius is accurate to ±0.5% of true width everywhere
except the deliberately tapered case.

### What the handoff asked us to quantify rather than assert

*"Voronoi centerlines are approximations built from boundary sample points, so
expect systematic deviation on curved strokes. Quantify it on the synthetic
arcs."*

Measured, at tol 0.15 and densify −0.25, on 24-unit-wide strokes:

- **circular arc (03)** — median 0.033 u = **0.14% of stroke width**, P95 0.068 u
  = 0.28%. Effectively exact.
- **tight U (05)**, **closed loop (06)**, **noisy boundary (20)** — P95 0.034 /
  0.047 / 0.066 u, all under 0.3% of width.
- **S curve (04)** — median 0.031 u but **P95 0.574 u (2.4% of width)**. The
  deviation is *localised*: the axis is exact along both arcs and wanders at the
  **inflection point**, where the maximum deviation is 0.647 u at (312, 249) and
  the measured inscribed radius drops to 11.48 against a true 12.0.

So curvature itself costs almost nothing; **curvature reversal costs ~10×**, and
even then under 3% of a stroke width. The report's predicted systematic
curve deviation is real but an order of magnitude smaller than the errors that
actually matter here (caps, width model). Case 03 and 04 are also the only two
single-stroke cases flagged `excessive curve complexity` — the polyline carries
more vertices per stroke width than the geometry needs, because PyGeoOps'
densification sets the vertex spacing.

### Caps — a clean, quotable result

`extend` pushes the axis out to the polygon edge. Max centerline error:

| case | extend=False | extend=True |
|---|---|---|
| 07-cap-round | **0.000** (IoU 0.9999) | 20.000 (IoU 0.8979) |
| 08-cap-butt | 20.000 (IoU 0.9730) | **0.000** (IoU 0.9107) |
| 09-cap-square | **0.000** (IoU 0.9760) | 20.000 (IoU 0.9199) |

`extend` is exactly right for butt caps and exactly wrong for round and square
ones, always by one full radius, and PyGeoOps gives no way to choose per stroke.
Our target output is `stroke-linecap="round"` (Common Setup), so `extend=False`
is correct and **round-cap error is zero** — this backend does *not* need the
cap-extension post-step Track 1 needs for flo-mat. Confirmed on real artwork:
IoU 0.960 (False) vs 0.940 (True).

Note that even where `extend=True` fixes the *centerline* on butt caps, IoU
falls, because re-stroking the extended axis with a round cap overshoots a
square-ended region. Cap style has to be recovered, not assumed.

### The one real geometric failure: variable width (case 19)

Centerline error is **0.000** — the axis of the tapered stroke is exact — but
IoU is 0.7206, because a single `medianRadius` per edge cannot describe a stroke
that tapers 40 → 12. This is a *graph-model* limit, not an extraction limit, and
it generalises: see the width-model section below.

---

## Failure taxonomy (Common Setup vocabulary)

Counts are computed automatically in `failures.py`, not eyeballed, so they are
comparable with other tracks. Real ladder, best settings:

| image | cap | join | outline noise | crossing amb. | disconnected | missing narrow | wrong endpoint | excess complexity | raster quant. |
|---|---|---|---|---|---|---|---|---|---|
| house-wide | 6 | 5 | 0 | 0 | 0 | 0 | 0 | 29 | 0 |
| butterfly-wide | 6 | 3 | 0 | 0 | 0 | 2 | 2 | 25 | 0 |
| boat-tall | 5 | 3 | 0 | 0 | 0 | 0 | 0 | 23 | 0 |
| island-tall | 8 | 3 | 1 | 0 | 0 | 2 | 0 | 38 | 0 |
| balloon-tall | 6 | 4 | 0 | 0 | 1 | 0 | 0 | 53 | 0 |
| home-wide | 4 | 2 | 2 | 0 | 0 | 0 | 0 | 38 | 0 |
| house-tall | 7 | 2 | 1 | 0 | 0 | 0 | 0 | 51 | 0 |
| dinosaur-wide | 5 | 8 | 1 | 0 | 0 | 0 | 2 | 64 | 0 |
| landscape-square | 9 | **91** | 2 | 0 | 0 | 0 | 0 | 129 | 0 |
| sun-square | 0 | **29** | 0 | 0 | 0 | 0 | 0 | 29 | 0 |
| **total** | 56 | 150 | 7 | 0 | 1 | 4 | 4 | 479 | 0 |

Reading the table:

- **`raster quantization` is structurally 0** — this backend never rasterizes.
  That is its main advantage over Tracks 2, 3 and 6 and it is worth stating as a
  zero rather than an omission.
- **`outline noise branch` is nearly 0** (7 across ten drawings). With the branch
  filter off it is 192 on landscape-square alone. This is the width-relative
  filter doing its job.
- **`join artifact` dominates the two hardest images** (91 on landscape, 29 on
  sun) and accounts for 1.21% and 2.93% of total ink respectively.
- **`missing narrow segment` = 4**, all on butterfly-wide and island-tall: small
  solid discs (the butterfly's eyes). The medial axis of a filled disc is a
  single *point*, which has no length, so nothing survives. Solid blobs are a
  degenerate input for every medial-axis method and need to be detected and
  passed through as fills.
- **`excessive curve complexity` = 479** is the largest count and is a real
  weakness: output is dense polylines, roughly one vertex per PyGeoOps
  densification step, with no Bézier fitting anywhere in this track.
- **`crossing ambiguity` = 0 on real artwork** — no degree-≥4 nodes appeared.
  Synthetically it fires on 14-x-union and 18-self-overlap, exactly as expected.

### The sun-square failure, looked at rather than inferred

`diag-sun-crop.png` renders the source fill in grey with the recovered axis in
red and nodes coloured by degree (blue = terminal, magenta = degree ≥ 3). At each
**hairpin turn** of the scribble, the axis does not follow the pen around the
bend: it forms a Y, with two arms running along the legs and a short arm
terminating inside the turn. Re-stroking those arms at their own median radii
underfills the outer part of the bend. The scribble is one continuous stroke, but
the recovered graph reports 30 edges, 16 terminals and 14 degree-3 nodes.

The *geometry* is right — this is the true medial axis of that region. The
failure is semantic (which arms belong to one pen stroke) plus width-model, and
both belong to Track 8, not to the extractor.

---

## The width model is the real bottleneck, not the centerline

Same graph, two re-strokes: one median radius per edge vs the per-edge radius
profile. Symmetric difference as a fraction of ink:

| image | median radius | variable radius |
|---|---|---|
| sun-square | 8.10% | **2.18%** |
| landscape-square | 5.93% | **2.91%** |
| dinosaur-wide | 3.55% | **2.47%** |
| butterfly-wide | 3.52% | **2.96%** |
| house-wide | 2.27% | 2.49% |
| boat-tall | 2.22% | 2.66% |

On the two hardest images most of the error disappears without touching the
centerline. On the easy near-constant-width drawings the variable version is
marginally worse (discretisation of the swept disc). **Conclusion for Track 8:
score a backend with a variable-radius re-stroke, or you will attribute a
width-model artifact to the extractor.** Every graph JSON here therefore exports
a `radiusProfile` alongside `medianRadius`.

---

## Answer to the Track 8 question

> Is PyGeoOps' automatic width-relative filtering competitive with bespoke
> pruning?

**Yes on these shapes, and it is worth studying rather than reimplementing —
but its normalisation is coarser than the one Track 8 is planning, and that
difference has teeth.**

What it does: `min_branch_length < 0` resolves to `|value| × average_width`,
where `average_width` is the width of the rectangle with the same area and
perimeter as the polygon:

```python
average_width = P/4 - sqrt((P/4)**2 - A)      # pygeoops/_centerline.py
```

Effect at `min_branch_length = −1.0` (one average width), simplify off, tol 0.15:

| synthetic case | edges, filter off | edges, filter on | clP95 off → on |
|---|---|---|---|
| 14-x-union | 404 | **4** | 0.123 → **0.000** |
| 15-t-junction | 303 | **3** | 0.155 → **0.000** |
| 16-y-junction | 263 | **3** | 0.129 → **0.000** |
| 17-parallel-near | 402 | **2** | 0.123 → **0.000** |
| 18-self-overlap | 254 | **3** | 0.259 → 0.342 |
| 20-noisy-boundary | 87 | **1** | 9.875 → **0.066** |

That is a 100× reduction in graph size to the *exactly correct* topology, with
centerline error going to zero, from one scale-free parameter.

Where it is weaker than the plan in Track 8's brief:

1. **It normalises by the polygon's global average width, not local radius.**
   `L / (2 × R_med)` with a *local* `R_med` is strictly better when one element
   contains strokes of different widths, or a stroke that tapers. Synthetic case
   19 shows the symptom: the tapered stroke needs `min_branch_length ≤ −1.0` to
   clean up, while case 18 is already over-pruned at `−2.0` (IoU 0.9940 → 0.9551).
   There is no single global setting that is right for both; a local
   normalisation would separate them.
2. **It uses only feature (a): length.** None of `R_med / R_global`,
   `std(R)/mean(R)`, or the tangent relationship `θ` to the parent path is
   available. On sun-square the surviving spurious arms are *long enough* to
   pass a length test but point into a hairpin at ~180° to their parent — a
   tangent-continuity feature would kill them and a length feature cannot.
3. **It is all-or-nothing, with no candidate generation.** §10.2's
   prune/reconstruct model selection is exactly what is missing: on real artwork
   `min_branch_length = 0` scores IoU 0.963 against 0.960 at −1.0, but with
   **227 edges instead of 37**. Choosing between those needs the Pareto step,
   which the library has no notion of.

**Recommended stance for Track 8:** treat PyGeoOps' filter as the *baseline to
beat*, not as a component. It is one line of configuration, is scale-free, and
already reaches exact topology on every clean junction case in the corpus — so a
bespoke pruner that only prunes on length has no reason to exist. The wins
available are local-radius normalisation, the tangent feature, and Pareto model
selection. All three graph JSONs here are ready to test that on:
`debug/polygon-voronoi/graphs/*.json`.

`backends.run_fitodic_filtered` is a working example of pointing PyGeoOps'
pruner at another backend's output — Track 8 can reuse the same trick to compare
against flo-mat's and skimage's graphs.

---

## What was built

```
experiments/polygon-voronoi/
  svgpoly.py     SVG -> validated Shapely polygons (svgelements, adaptive
                 flattening at a configurable tolerance, ring nesting by
                 containment depth, is_valid / buffer(0) repair with the repair
                 recorded rather than silent)
  synth.py       20-case synthetic corpus generated FROM known centerlines
  backends.py    one interface over pygeoops / fitodic / fitodic+filter
  graphmodel.py  common graph model, derived radius, re-stroke (median + variable)
  metrics.py     IoU, symdiff, boundary distance (median + P95), centerline
                 error vs ground truth, width error, complexity
  failures.py    automatic failure-taxonomy counts
  bench.py       re-runnable sweeps and ladder bench
  report.py      contact sheets
  sheets.py      rendering helpers
```

Re-run everything:

```bash
pip3 install numpy scipy shapely pillow cairosvg svgelements pygeoops centerline
python3 experiments/polygon-voronoi/synth.py debug/polygon-voronoi/synthetic
python3 experiments/polygon-voronoi/bench.py sweep-synthetic --out sweep-synthetic.json
python3 experiments/polygon-voronoi/bench.py sweep-synthetic --grids branch0 --out sweep-synth-branch0.json
python3 experiments/polygon-voronoi/bench.py sweep-real --grids branch0 simplify extend interp
python3 experiments/polygon-voronoi/bench.py bench --backend pygeoops \
        --tolerance 0.15 --densify -0.25 --branch -1.0 --simplify 0 --out metrics-pygeoops.json
python3 experiments/polygon-voronoi/report.py comparison --inputs inputs/*.svg \
        --backend pygeoops --tolerance 0.15 --densify -0.25 --branch -1.0 --simplify 0 \
        --stem contact-comparison-pygeoops
python3 experiments/polygon-voronoi/report.py progress --image inputs/house-wide.svg \
        --stem contact-progress-house-wide
```

### The synthetic corpus is reusable by other tracks

Cases 1–12 and 19 emit **exact stroke outlines built from real SVG line and arc
commands**, not pre-flattened polygons — otherwise a flattening sweep would be a
no-op. Cases 13–18 and 20 are genuine boolean unions and are marked
`curve_native: false` in `synthetic/manifest.json`, which also carries the
ground-truth centerline polylines and stroke widths for every case. All 20 load
as valid Shapely polygons with area within 0.1% of an independent buffer
reference and zero `buffer(0)` repairs.

### Graph JSON

`debug/polygon-voronoi/graphs/<image>-<backend>.json`, exactly the §13 model:

```json
{"nodes":[{"id":"g0_n0","x":..,"y":..,"radius":..}],
 "edges":[{"id":"g0_e0","from":"g0_n0","to":"g0_n1",
           "geometry":[{"x":..,"y":..}],
           "length":..,"medianRadius":..,
           "radiusProfile":[..],"sourceElementId":"el3","sourceFill":"#288afe"}],
 "meta":{"backend":"pygeoops","flatten_tolerance":0.15,"params":{...},
         "radiusSource":"derived-distance-to-boundary"}}
```

Three deliberate departures, all additive:

- **`radius` is DERIVED, not native.** Polygon-Voronoi carries no medial-axis
  radius. We measure distance-to-boundary from the source Shapely polygon at
  points along the centerline. Every file says so in `meta.radiusSource`. It
  measured within ±0.5% of true stroke width on every synthetic case except the
  deliberately tapered one, so it is trustworthy — but it inherits the axis's
  positional error, since an off-axis point reports a smaller inscribed circle.
- **`radiusProfile`** — the radius sampled along the edge. Added because one
  median radius costs 3–6 points of IoU on the hard images (above).
- **`sourceFill`** — the source element's ink colour.

`geometry` is `Point[]`, never `Bezier[]`: **this track does no curve fitting**,
so its `excessive curve complexity` counts are the worst of any vector backend
and should be read as "before fitting". Track 3's fit-curve stage would apply
here unchanged.

---

## Iteration log

house-wide, one change per step (`contact-progress-house-wide.png`):

| # | change | IoU | edges |
|---|---|---|---|
| 0 | pygeoops library defaults | 0.8057 | 37 |
| 1 | branch filter off (mbl = 0) | 0.8196 | 150 |
| 2 | **simplify off** | 0.9680 | 37 |
| 3 | flattening tol 0.5 → 0.15 | 0.9722 | 37 |
| 4 | extend = True | 0.9541 | 37 |
| 5 | densify −0.5 → −0.25 | **0.9774** | 37 |
| 6 | fitodic raw (interp 2.0) | 0.9813 | **239** |
| 7 | fitodic + pygeoops filter | 0.9774 | 37 |

Step 4 made things worse and is left in the sheet on purpose.

### Negative results and things that cost time — recorded for the other tracks

- **Evaluating PyGeoOps at its defaults is misleading.** IoU 0.806 vs 0.977 on
  the same image and the same library. If any other track cites a PyGeoOps
  number, check `simplifytolerance` first.
- **Scoring against the swept flattening hides flattening error.** Early runs
  showed IoU *improving* as tolerance got coarser, because a coarser polygon is
  easier to reconstruct. All region metrics are now scored against a fixed
  0.02-unit reference (`bench.reference_geometry`). Any track sweeping a
  discretisation parameter has this bug available to it.
- **Vector and raster scoring disagreed by two orders of magnitude, and the
  raster score was right to complain.** `src/compare.js` reported 6–32%
  differing pixels on drawings whose vector IoU was 0.92–0.98. Cause: our
  re-stroke emitted black strokes while the inputs are coloured fills, so every
  stroke pixel differed by colour. Edges now carry `sourceFill`. Cross-checking
  the two scorers found a real bug the vector metric could not see.
- **`extend=True` looks like the obvious cap fix and is not** — it is only right
  for butt caps and is wrong by a full radius for round and square ones.
- **fitodic improves as its sampling gets coarser.** Anyone reaching for
  "sample the boundary more finely to get a better centerline" should read the
  interp table first.
- **Case 17 (near-touching parallels) did not produce the spurious connecting
  branch the handoff expected** — but that is partly our pipeline, not the
  library: a 2-unit gap keeps the two strokes as separate Shapely polygons and we
  run the backend **per polygon**, so no bridge can form. The failure mode is
  real for anyone who unions elements first. The incumbent's recorded lesson
  about not merging same-colour elements applies here for the same reason.
- **Solid discs vanish.** Their medial axis is a point of zero length. Detect and
  pass through as fills.

---

## Where polygon-Voronoi centerlines ARE and ARE NOT adequate for artistic strokes

**Adequate, with evidence:**

- Straight, diagonal, arc, tight-U, closed-loop and noisy-boundary strokes —
  centerline P95 ≤ 0.07 units on 24-unit strokes (≤ 0.3% of width).
- Round and square caps — zero error, no cap-extension post-step needed.
- Round, bevel and miter joins — zero centerline error.
- X crossings (both merged and separate), T and Y junctions — exactly correct
  topology and zero centerline error, purely from the built-in width-relative
  branch filter.
- Line-art drawings with distinct, non-merging strokes — IoU 0.963–0.978 across
  eight of the ten real inputs, 0.008–0.017 s/element.
- Radius recovery by distance sampling — within ±0.5% of true width.

**Not adequate:**

- **Butt-capped strokes** — one full radius short at each end, and the library's
  only fix breaks round caps.
- **Variable-width strokes** — the axis is exact but a single median radius
  re-strokes at IoU 0.72. Needs the radius profile (exported) or per-vertex
  width.
- **Hairpin turns in a merged scribble** — the axis Y-branches instead of
  turning; sun-square 8.10% symmetric difference, 29 join artifacts. Fixing this
  is branch pairing, i.e. Track 8.
- **Dense merged hatching** — landscape-square, 91 join artifacts, 131 edges,
  IoU 0.9422, and the worst seconds-per-element on the ladder (0.038).
- **Solid blobs** — degenerate, produce nothing.
- **Compact output** — dense polylines only. 479 `excessive curve complexity`
  flags across the ladder; a Bézier-fitting stage is mandatory before this could
  ship.

**Runtime** (§16) is not a problem at this scale: 0.008–0.041 s/element,
every drawing under 0.6 s end to end, no rasterization. fitodic is 3–5× slower
for no quality gain, and its cost grows sharply as `interpolation_distance`
shrinks (0.63 s/element at 0.25 on real artwork, for 3178 edges of garbage).

---

## Artifacts

| file | what |
|---|---|
| `metrics-pygeoops.json` / `-fitodic.json` / `-fitodic-filtered.json` | ladder metrics, all three backends |
| `sweep-synthetic.json`, `sweep-synth-branch0.json`, `sweep-synth-1-6.json` | 2-D surfaces, synthetic |
| `sweep-real.json` | 2-D surfaces, real artwork |
| `graphs/*.json` | common graph model |
| `contact-comparison-pygeoops.png` / `.html` | comparison sheet, all 10 real inputs, with worst-region crops |
| `contact-comparison-synthetic.png` / `.html` | comparison sheet, all 20 synthetic cases |
| `contact-progress-house-wide.png` / `.html` | progress sheet |
| `diag-sun-crop.png` | node-degree diagnostic of the sun hairpin failure |
| `synthetic/*.svg` + `manifest.json` | the corpus, reusable by any track |
| `../../outputs/polygon-voronoi/*.svg` | promoted results (median-radius) and `*-varwidth.svg` |
