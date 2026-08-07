# Track 3 — scikit-image `medial_axis` + Skan + fit-curve

**Slug:** `skimage-skan` · Report §6.5, §6.7, §7.4, §18.3 · Tier 1, rank 3

Verdict up front: **this backend works, and it works well.** On the pixel metric
the incumbent is measured by it ties or beats the incumbent everywhere it was
run, while emitting a proper radius-carrying graph and Bézier output instead of
dense polylines. Full numbers below; the honest caveats are in
[Failure modes](#failure-modes) and [What this backend cannot do](#what-this-backend-cannot-do).

---

## How to reproduce

```bash
pip3 install numpy scipy scikit-image shapely pillow svgelements skan
npm install                       # adds @resvg/resvg-js@2.6.2, fit-curve@0.2.0

python3 experiments/skimage-skan/corpus.py            # regenerate the 20 synthetic cases
python3 experiments/skimage-skan/bench.py corpus      # ground-truth centerline error
python3 experiments/skimage-skan/bench.py inputs \
    --images house-wide,dinosaur-wide,landscape-square,sun-square \
    --width-mode piecewise --promote
python3 experiments/skimage-skan/sheets.py comparison --tag 'medial-axis@4+pw'
```

Everything lands in `debug/skimage-skan/` (`metrics.json`, `graphs/`, `out/`,
`sheets/`, `diffs/`) and promoted SVGs in `outputs/skimage-skan/`.

## Pipeline

```
SVG ──svgelements──► filled elements (transforms resolved, one element = one job)
    ──resvg────────► binary mask, cropped to the element bbox, at `scale` px/unit
    ──medial_axis(return_distance=True)──► skeleton + Euclidean distance field
    ──Skan Skeleton/summarize────────────► nodes, branches, ordered coordinates
    ──smooth ▸ resample ▸ corner-detect ▸ RDP──► common graph model + radii
    ──fit-curve (Schneider)──────────────► cubic Béziers, C0 breaks at corners
    ──stroke emission────────────────────► <path fill=none stroke-linecap=round>
```

Element-mode processing is inherited from the incumbent
(`docs/current-attempt-handoff.md`) and it matters for more than landscape:
because every filled element gets its own mask, two strokes that merely *touch*
on screen can never fuse in the skeleton. Corpus case 17 (near-touching
parallel lines, 2-unit gap) survives even at scale 1 px/unit purely because of
this. A colour-merged pipeline would have fused them.

---

## Files

| file | what it is |
|---|---|
| `experiments/skimage-skan/svgio.py` | SVG → filled elements (svgelements; transforms/groups resolved) |
| `experiments/skimage-skan/raster.py` + `resvg_render.js` | deterministic resvg rasterization, and the one place the pixel↔SVG coordinate mapping is written down |
| `experiments/skimage-skan/corpus.py` | the 20-case synthetic ground-truth corpus, built by Shapely-buffering known centerlines |
| `experiments/skimage-skan/extract.py` | medial axis + Skan → common graph model |
| `experiments/skimage-skan/emit.py` + `fit_curve.js` | Bézier fitting and stroked-SVG emission |
| `experiments/skimage-skan/metrics.py` | re-stroke scoring, centerline error, failure-tag counters |
| `experiments/skimage-skan/bench.py` | the one re-runnable bench command |
| `experiments/skimage-skan/sheets.py` | comparison + progress contact sheets (PNG and HTML) |

---

## The graph JSON (for Track 8)

`debug/skimage-skan/graphs/<image>__<tag>.json`, schema id
`centerline-graph/1`. It is the §13 model plus additive fields; a strict
consumer can read only `id/x/y/radius` and `id/from/to/geometry/length/
medianRadius/sourceElementId` and ignore the rest.

```jsonc
{
  "schema": "centerline-graph/1",
  "image": "house-wide", "backend": "skimage-skan/medial-axis",
  "units": "svg-user-units", "viewBox": [0,0,1662,946],
  "radiusSource": "native",          // Euclidean distance transform, not derived
  "meta": { "scale": 4, "method": "medial-axis", ... },
  "nodes": [ { "id": "e1n0", "x": 1385.0, "y": 106.7, "radius": 12.95, "degree": 1 } ],
  "edges": [ {
    "id": "e1b2", "from": "e1n0", "to": "e1n7",
    "geometry": [[x,y], ...],        // Point[] polyline, SVG user units
    "radii":    [r, ...],            // SAME LENGTH as geometry — per-vertex local radius
    "length": 601.1, "medianRadius": 10.43, "sourceElementId": "e1",
    "meanRadius": 10.4, "minRadius": 9.8, "maxRadius": 12.9,
    "radiusCv": 0.031,               // std(R)/mean(R)      — §10.1 width consistency
    "normLength": 28.8,              // length / (2*R_med)  — §10.1 scale-free length
    "branchType": 2,                 // Skan: 0 end-end, 1 junction-end, 2 junction-junction, 3 cycle
    "corners": [17, 43],             // indices into geometry kept as C0 breaks
    "beziers": [[[p0],[c1],[c2],[p3]], ...],
    "widthRuns": [ {"bezierStart":0,"bezierCount":3,"radius":10.4}, ... ],
    "closed": false
  } ]
}
```

Notes for consumers:

- **`radii` is native, not derived.** It is `distance_transform / scale` read
  straight off the medial-axis distance field at each skeleton pixel, i.e. the
  radius of the maximal inscribed disk. Verified exact on the synthetic capsule:
  true radius 10.000 → recovered 10.000 at scales 2, 4 and 8. No fudge factor,
  no `-0.5` pixel correction; `r_svg = dist_px / scale` is correct as written.
- `normLength` and `radiusCv` are precomputed because they are the §10.1
  pruning features. `R_global` is deliberately *not* baked in — that is a
  document-level decision Track 8 should make.
- `degree` is the skeleton degree, so terminal branches are
  `deg(from)==1 or deg(to)==1` and `crossing ambiguity` candidates are
  `degree >= 4`.
- `geometry` is RDP-simplified at 0.15 user units, with detected corners forced
  to survive, so corner indices are valid in the simplified index space.
- `graphmodel.validate()` is a structural validator (unknown node refs,
  degenerate geometry, radii/geometry length mismatch). All runs recorded here
  validate clean; `metrics.json` carries a `graphProblems` array per run.

---

## Findings

### 1. `medial_axis` is non-deterministic by default — this is a trap

`skimage.morphology.medial_axis(image, mask=None, return_distance=False, *, rng=None)`
randomises the pixel ordering used to break thinning ties. With the default
`rng=None`, **two calls on the same mask return different skeletons.** Verified
on scikit-image 0.26.0:

```
identical across 4 calls: False     # rng=None  (default)
identical across 4 calls: True      # rng=0
```

The pixel *count* is stable, so this hides easily — it shows up as scores that
wobble by ±0.01 IoU between otherwise identical runs, which is enough to make a
real regression invisible. Report §15 calls out determinism for rasterization;
it needs to be called out for the skeletonizer too. `skeletonize()` has no such
parameter and is deterministic. **Track 6 should check `cv2.ximgproc.thinning`
for the same property.**

Fixed here by `ExtractConfig.rng_seed = 0`, passed on every call.

### 2. Euclidean medial axis vs plain thinning — what the Euclidean version buys

Same masks, same rasterization, same downstream stages; only the skeletonizer
differs. Corpus, scale 4, centerline error against the known source path
(user units, stroke radius 10):

| case | medial-axis median / P95 / Hausdorff | skeletonize median / P95 / Hausdorff |
|---|---|---|
| 02 diagonal line | **0.071** / **0.169** / **0.18** | 0.178 / 0.236 / 0.64 |
| 03 circular arc | **0.077** / **0.137** / **0.17** | 0.225 / 0.324 / 1.01 |
| 04 S curve | **0.170** / **0.193** / **0.24** | 0.243 / 0.479 / 0.64 |
| 05 tight U | **0.136** / **0.182** / **0.64** | 0.304 / 0.786 / 1.63 |
| 06 closed loop | **0.133** / **0.159** / **0.20** | 0.236 / 0.543 / 0.62 |
| 11 bevel join | **0.115** / **0.395** / 3.38 | 0.173 / 1.256 / 3.46 |

The pattern is consistent and it is exactly where theory says it should be: on
**curved** geometry the Euclidean medial axis is 2–3× more accurate, because
morphological thinning follows the 8-connected pixel lattice and staircases
around a curve while the distance-transform ridge does not. On straight
segments the two are close.

Where `skeletonize()` wins is the **butt and square cap cases (08, 09)**: it
produces one clean branch where `medial_axis` fans out into 5 (the corner
bisector spurs are genuine medial-axis structure). That is not thinning being
better, it is thinning being *lossy in a way that happens to be convenient*, and
it costs you the distance field. Prune the spurs and the medial axis is strictly
ahead.

And the decisive point: **`skeletonize()` gives no radius at all.** Everything
in [finding 4](#4-the-distance-field-pays-for-itself-twice) is unavailable to it.

### 3. Resolution sensitivity — better geometry, more noise, at the same time

Corpus swept at 1, 2, 4, 8, 16 px per SVG unit (stroke radius 10 units):

| | scale 1 | 2 | 4 | 8 | 16 |
|---|---|---|---|---|---|
| case 03 arc, centerline median | 0.197 | 0.212 | 0.077 | **0.053** | 0.054 |
| case 02 diagonal, Hausdorff | 0.71 | 0.35 | 0.18 | 0.25 | **0.04** |
| case 13 X (separate), Hausdorff | 0.71 | 0.36 | 0.25 | 0.09 | **0.05** |
| **case 20 noisy boundary, edge count** | **22** | 31 | 58 | 118 | **289** |

Two opposite trends, and both are structural:

- Geometry converges. Beyond ~8 px per unit (≈0.8 px per stroke radius unit)
  the remaining error is fitting/simplification, not quantization.
- **Spurious branch count grows roughly linearly with resolution.** Every
  boundary wiggle that is sub-pixel at scale 1 becomes a resolvable bump — and
  therefore a medial-axis branch — at scale 16. Case 20 goes from 22 to 289
  branches on the *same shape*.

This is the report's §10 warning made quantitative, and it has a direct
consequence for Track 8: **any pruning rule with an absolute length threshold
will need retuning per resolution.** `L / (2·R_med)` does not, because the spurs
also have small `R_med`. On case 20 the spurious branches sit at
`medianRadius ≈ 1.2–4.7` against a true stroke radius of 10, so
`R_med / R_global` separates them cleanly too.

Scale 4 is the default here: it is where the real-image scores plateau and it
keeps runtimes reasonable. Scale 8 buys ~30% on smooth-curve centerline error
and roughly doubles the branch count.

### 4. The distance field pays for itself twice

The report frames `return_distance=True` as a *pruning* signal (§10). It is, but
it also fixes the single largest reconstruction error on the real corpus, at the
emission stage, which was not anticipated:

SVG cannot vary `stroke-width` along one path. A tapered pen stroke rendered at
one median width is too fat at the ends and too thin in the middle. Because the
graph carries a per-vertex radius, an edge can be split into contiguous runs of
near-constant radius (±18%) and each run emitted as its own constant-width
sub-path (`--width-mode piecewise`, `emit.width_runs`):

| | constant width | piecewise width |
|---|---|---|
| corpus 19 variable-width, IoU | 0.736 | **0.954** |
| `sun-square`, IoU | 0.894 | **0.952** |
| `sun-square`, pixel diff | 3.59% | **1.73%** |
| `house-wide`, pixel diff | 0.08% | **0.02%** |

`sun-square` is the scribble the incumbent struggles with (~4.2% raster, ~6.3%
vector) precisely because it is a pressure-tapered stroke. Halving the error
required no new geometry, no tuning and no extra extraction work — only the
radius data that `medial_axis` already returned.

Cost: file size and segment count go up (sun-square 7.2 KB → 17.1 KB). §11 says
prefer the simpler graph *when geometry error is comparable* — here it is not
comparable, so the complexity is earned. On a genuinely constant-width shape the
splitter mostly no-ops (corpus case 01 drops 0.982 → 0.965 IoU, a small loss
from splitting where it should not have).

### 5. Skan is the right graph layer

No reservations. `Skeleton` + `summarize()` gave branch decomposition, ordered
per-branch coordinates, node degrees and branch types with no pixel-neighbour
traversal written by hand, and it handled cycles (case 06, `branch_type == 3`)
and multi-junction elements without special-casing. Mapping it into the §13
model is ~40 lines. Compared with the incumbent's ~600-line hand-rolled tracer
this is a large architectural simplification, and it is the part of this track
that would transfer unchanged to Track 6.

One API note for whoever follows: `Skeleton(skel, source_image=dist)` and
`path_means()` did *not* return useful radii here (all 1.0). Sample the distance
field directly at `path_coordinates(i)` instead — that is what `extract.py` does.

---

## Failure modes

Tagged with the §13 Experiment 2 taxonomy. Counts per run are in
`metrics.json` under `tags` (mechanical detectors, so they are comparable with
other tracks rather than hand-curated).

| tag | where it shows up here | severity |
|---|---|---|
| `cap artifact` | butt (08) and square (09) caps: the medial axis retracts by ~R and fans into corner spurs. Hausdorff 9.9 and 14.0 = exactly R and R·√2. | structural, see below |
| `join artifact` | every T junction: the medial axis forks into a Y before the stem meets the bar, and round caps on the two short Y arms render a visible blob. Clearly seen in the `house-wide` worst-region crops. | the main visible defect |
| `outline noise branch` | case 20 by construction; on real art mostly at pen-corner outsides. Terminal branches with `normLength < 0.6`. | Track 8's job |
| `crossing ambiguity` | case 14 (unioned X) produces a degree-4 node. Left undecided in the graph, as instructed. | by design |
| `raster quantization` | branches with `normLength < 0.2`; grows with scale (finding 3). | Track 8's job |
| `disconnected skeleton` | **not observed** at scale ≥ 2 on any real input; detector compares skeleton component count against mask component count. | absent |
| `missing narrow segment` | not observed; no element produced an empty or degenerate skeleton on the real ladder. | absent |
| `wrong endpoint` | round-cap terminals sit ~0.3–0.4 units inside the true endpoint at scale 4 (3–4% of R). `--cap-extend` removes most of it (case 01 centerline median 0.117 → 0.066, Hausdorff 0.64 → 0.13). | minor, fixable |
| `excessive curve complexity` | rare; `> 1.5` Béziers per stroke-width of arc length. | rare |

### What this backend cannot do

- **Butt and square caps cannot be reconstructed with `stroke-linecap="round"`.**
  This is a *stroke-model* mismatch, not an extraction failure, and the numbers
  separate the two cleanly. Case 08 at the same geometry:
  `linecap=round` IoU 0.812 → `linecap=butt` IoU **0.915** (with cap extension,
  0.818 → **0.915**). The centerline was fine all along. Recovering the cap
  *style* is a semantic decision that belongs with Track 8, not here — but note
  that the raw material for it is in the graph: a butt cap leaves a
  characteristic 5-branch fan whose spur lengths are ≈R and ≈R·√2.
- **Variable-width strokes** are only approximated, by piecewise-constant runs.
  A real answer needs a variable-width stroke representation, which SVG 1.1
  simply does not have (short of emitting an outline, which defeats the point).
- **Crossings** stay ambiguous by design (case 14), per the brief.

---

## Negative / neutral results worth recording

- **`--cap-extend` (march the terminal end to the outline, back off one local
  radius — the incumbent's `--calibrate-caps` trick) helps centerline accuracy
  but not IoU on real art.** Corpus case 01: centerline median 0.117 → 0.066,
  Hausdorff 0.64 → 0.13, and IoU 0.958 → 0.986 in a controlled A/B. On the real
  ladder the change is within noise, because round-cap retraction is only ~3% of
  R to begin with. It is off by default; turn it on when centerline fidelity
  matters more than pixels (i.e. for the synthetic corpus, or for Track 8).
- **Feeding fit-curve an RDP-simplified polyline produces garbage.** A
  near-collinear 3-point run makes Schneider's tangent/α solve ill-conditioned
  and it returns control points flung across the canvas — a visible loop that
  still passes the algorithm's own error test. First run of corpus case 02
  scored IoU 0.771 for exactly this reason while its centerline error was
  0.065. Fix: fit on a *uniformly arc-length resampled* chain
  (`extract.resample_uniform`, step `R_med/8`), and keep a sanity check that
  rejects control points outside the run's bbox + 35% of its diagonal and
  subdivides instead (`fit_curve.js: sane()`). Anyone else using fit-curve
  should copy both.
- **IoU is a weak discriminator for centerline quality and is sometimes
  anti-correlated with it.** Case 02 before the fitting fix: IoU said skeletonize
  (0.858) beat medial-axis (0.771); centerline error said medial-axis was 2.7×
  more accurate (0.065 vs 0.175). The IoU gap was entirely a bad Bézier fit. If
  you have ground truth, score against it; IoU is for the real inputs where you
  do not.
- **`corner_window` scaled by local radius, not by arc length.** Absolute-arc
  corner windows mis-fire between fat and thin strokes in the same drawing;
  `window = 0.9 × R_local` behaves the same on both. No image regressed from
  this and the sun's hairpins survive fitting, which was the stated risk.
