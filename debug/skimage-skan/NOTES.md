# Track 3 — scikit-image `medial_axis` + Skan + fit-curve

**Slug:** `skimage-skan` · Report §6.5, §6.7, §7.4, §18.3 · Tier 1, rank 3

**Verdict:** this backend works, and it is the most likely production fallback the
brief hoped for. On all three images the incumbent has promoted outputs for it
beats the incumbent on the incumbent's own metric, while emitting a proper
radius-carrying graph and Bézier output instead of dense polylines, with no
per-image tuning — one config for all ten inputs. The honest caveats are in
[Failure modes](#failure-modes),
[What this backend cannot do](#what-this-backend-cannot-do) and
[Negative results](#negative-and-neutral-results).

Head-to-head against the incumbent's own promoted outputs, re-measured on this
machine today (`python3 experiments/skimage-skan/incumbent.py`) so both sides go
through the same scorer:

| image | | pixel diff | IoU | boundary P95 | path commands | bytes |
|---|---|---|---|---|---|---|
| `dinosaur-wide` | incumbent | 0.02% | 0.9220 | 1.27 | 20,034 | 278 K |
| | **this track** | **0.01%** | **0.9566** | **0.79** | **590** | **27 K** |
| `landscape-square` | incumbent | 0.73% | 0.8905 | 5.15 | 46,213 | 652 K |
| | **this track** | **0.13%** | **0.9549** | **1.60** | **1,235** | **58 K** |
| `sun-square` | incumbent | 6.26% | 0.7958 | 9.17 | 308 | 6 K |
| | **this track** | **1.73%** | **0.9524** | **1.60** | **218** | 10 K |

The incumbent's recorded numbers reproduce exactly (0.02% / 0.73%), so this is a
like-for-like comparison, not a re-tuned one. The two scorers disagree on
*magnitude* — `compare.js` at 1200 px with an anti-aliasing tolerance is far more
forgiving than IoU on a 4× mask — but they agree on ranking everywhere.

The complexity column is the Bézier payoff: **34× and 37× fewer path commands**
for the same drawing, because the incumbent emits every skeleton pixel as a
polyline vertex. Nine of ten images land at ≤0.13% pixel diff; the full ladder is
below.

---

## Reproduce

```bash
pip3 install numpy scipy scikit-image shapely pillow svgelements skan
npm install                            # adds @resvg/resvg-js@2.6.2, fit-curve@0.2.0

bash experiments/skimage-skan/runbench.sh     # the whole matrix, ~20 min
python3 experiments/skimage-skan/bench.py report   # re-print stored results
```

Single runs:

```bash
python3 experiments/skimage-skan/corpus.py                     # regenerate the 20 cases
python3 experiments/skimage-skan/bench.py corpus                # ground-truth centerline error
python3 experiments/skimage-skan/bench.py inputs --images house-wide --width-mode piecewise
python3 experiments/skimage-skan/sheets.py comparison --tag 'medial-axis@4+pw'
```

Artifacts land in `debug/skimage-skan/` (`metrics.json`, `graphs/`, `out/`,
`sheets/`, `diffs/`, `corpus/`); promoted SVGs in `outputs/skimage-skan/`.

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
on screen can never fuse in the skeleton. Corpus case 17 (near-touching parallel
lines, 2-unit gap, stroke radius 10) survives intact even at 1 px per SVG unit
purely because of this. A colour-merged pipeline would have fused them, and
"near-touching parallels fuse" is the classic Voronoi/raster failure other tracks
should expect to hit.

| file | what it is |
|---|---|
| `experiments/skimage-skan/svgio.py` | SVG → filled elements (svgelements; transforms/groups resolved) |
| `experiments/skimage-skan/raster.py` + `resvg_render.js` | deterministic resvg rasterization; the one place the pixel↔SVG coordinate mapping is written down |
| `experiments/skimage-skan/corpus.py` | the 20-case synthetic ground-truth corpus, built by Shapely-buffering known centerlines |
| `experiments/skimage-skan/extract.py` | medial axis + Skan → common graph model |
| `experiments/skimage-skan/emit.py` + `fit_curve.js` | Bézier fitting, width runs, stroked-SVG emission |
| `experiments/skimage-skan/metrics.py` | re-stroke scoring, centerline error, failure-tag detectors |
| `experiments/skimage-skan/bench.py` | the one re-runnable bench command (`corpus`/`inputs`/`sweep`/`all`/`report`) |
| `experiments/skimage-skan/sheets.py` | comparison + progress contact sheets (PNG and HTML) |
| `experiments/skimage-skan/runbench.sh` | the full matrix in one command |

---

## The graph JSON — read this if you are Track 8

`debug/skimage-skan/graphs/<image>__<tag>.json`, schema id `centerline-graph/1`.
It is the §13 model plus additive fields; a strict consumer can read only
`id/x/y/radius` and `id/from/to/geometry/length/medianRadius/sourceElementId`
and ignore the rest. The canonical file to start from is
`house-wide__medial-axis@4+pw.json`.

```jsonc
{
  "schema": "centerline-graph/1",
  "image": "house-wide", "backend": "skimage-skan/medial-axis",
  "units": "svg-user-units", "viewBox": [0,0,1662,946],
  "radiusSource": "native",          // Euclidean distance transform, not derived
  "meta": { "scale": 4, "method": "medial-axis", "capExtend": false, ... },
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

- **`radii` is native, not derived.** It is `distance_transform / scale` read
  straight off the medial-axis distance field at each skeleton pixel — the radius
  of the maximal inscribed disk. Verified exact on the synthetic capsule: true
  radius 10.000 → recovered 10.000 at scales 2, 4 and 8. `r_svg = dist_px / scale`
  is correct as written; there is no half-pixel correction to apply.
- `normLength` and `radiusCv` are precomputed because they are the §10.1 pruning
  features. `R_global` is deliberately *not* baked in — that is a document-level
  decision Track 8 should own.
- `degree` is the skeleton degree: terminal branches are
  `deg(from)==1 or deg(to)==1`; `crossing ambiguity` candidates are `degree >= 4`.
- `geometry` is RDP-simplified at 0.15 user units with detected corners forced to
  survive, so `corners` indices are valid in the simplified index space.
- `graphmodel.validate()` checks unknown node refs, degenerate geometry and
  radii/geometry length mismatch. Every run recorded here validates clean;
  `metrics.json` carries a `graphProblems` array per run so a regression is loud.
- Suggested first experiment for Track 8: corpus case 20 at scale 16. It has 289
  edges on a shape whose true answer is one straight line, and the spurious
  branches sit at `medianRadius` 1.2–4.7 against a true radius of 10 — both
  `normLength` and `R_med/R_global` separate them cleanly.

---

## Results

### Real inputs — `medial-axis@4+pw` is the promoted config

| image | IoU | pixel diff | symDiff frac | boundary med / P95 | edges | Béziers | bytes | src bytes | sec |
|---|---|---|---|---|---|---|---|---|---|
| house-wide | 0.9643 | 0.03% | 0.036 | 0.25 / 1.00 | 55 | 206 | 14.8K | 21.0K | 7.3 |
| butterfly-wide | 0.9653 | 0.03% | 0.035 | 0.25 / 0.90 | 44 | 201 | 13.3K | 22.2K | 6.1 |
| boat-tall | 0.9618 | **0.02%** | 0.039 | 0.25 / 0.71 | 75 | 310 | 20.3K | 29.4K | 5.8 |
| island-tall | 0.9610 | 0.04% | 0.040 | 0.25 / 0.75 | 90 | 336 | 24.2K | 35.4K | 3.3 |
| balloon-tall | 0.9614 | **0.02%** | 0.039 | 0.25 / 0.71 | 143 | 387 | 27.9K | 31.0K | 4.3 |
| home-wide | 0.9483 | 0.07% | 0.053 | 0.25 / 1.00 | 81 | 274 | 19.5K | 31.3K | 3.4 |
| house-tall | 0.9611 | 0.04% | 0.040 | 0.25 / 0.79 | 108 | 340 | 24.8K | 52.3K | 4.3 |
| dinosaur-wide | 0.9566 | **0.01%** | 0.044 | 0.25 / 0.79 | 107 | 382 | 27.5K | 43.3K | 10.0 |
| landscape-square | 0.9549 | **0.13%** | 0.046 | 0.25 / 1.60 | 225 | 725 | 57.6K | 55.7K | 18.3 |
| sun-square | 0.9524 | **1.73%** | 0.049 | 0.25 / 1.60 | 35 | 119 | 9.8K | 17.8K | 1.6 |

Boundary median is 0.25 user units on every image — exactly half a pixel at the
scoring resolution, i.e. the reconstruction is at the measurement floor
everywhere except at the specific defects P95 picks up.

**On file size, be careful what you compare against.** Béziers are a huge win
against *dense* polylines (the 34–37× command-count advantage over the incumbent
above) and roughly a wash against an *already simplified* one: `metrics.json`
records `polylineBytes` — the same graph emitted as RDP-simplified polylines at
0.15 units — next to `fileBytes`, and summed over the ladder the polyline version
is only 9% larger (262 K vs 240 K). The Bézier version's real advantage over a
coarse polyline is that it stays smooth when scaled, not that it is smaller.
Output is smaller than the *source* SVG on 9 of 10 images.

Byte counts also turn out to depend more on emission hygiene than on geometry:
grouping paths by colour so `fill`/`stroke`/`linecap`/`linejoin` are written once
per group rather than once per path cut every output by ~35–40%
(`sun-square` 17.1 K → 9.8 K) with identical geometry and unchanged IoU. Worth
doing before quoting any file-size comparison.

### Runtime (§16)

0.02–0.14 s per filled element at scale 4, dominated by rasterization for large
elements and by the Python polyline stages for long skeletons. Whole-image:
1.6 s (sun-square, 4 elements) to 14.5 s (landscape-square, 44 elements).
Scale 8 roughly doubles it (house-wide 8.3 s → 17.0 s).

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

The pixel *count* is stable, so this hides easily: it shows up as scores that
wobble by ~±0.01 IoU between otherwise identical runs, which is more than enough
to make a real regression invisible or to invent one. Report §15 calls out
determinism for rasterization; it needs calling out for the skeletonizer too.
`skeletonize()` has no such parameter and is deterministic.

**Track 6 should check `cv2.ximgproc.thinning` for the same property.** Fixed
here by `ExtractConfig.rng_seed = 0`, passed on every call.

### 2. Euclidean medial axis vs morphological thinning

Same masks, same rasterization, same downstream stages; only the skeletonizer
differs (`--methods medial-axis,skeletonize`). Corpus at scale 4, centerline
error against the known source path, in user units with stroke radius 10:

| case | medial-axis med / P95 / Hausdorff | skeletonize med / P95 / Hausdorff |
|---|---|---|
| 01 horizontal line | **0.092** / **0.150** / **0.18** | 0.177 / 0.196 / 1.63 |
| 02 diagonal line | **0.139** / **0.188** / **0.19** | 0.178 / 0.236 / 0.64 |
| 03 circular arc | **0.075** / **0.129** / **0.14** | 0.225 / 0.324 / 1.01 |
| 04 S curve | **0.117** / **0.177** / **0.19** | 0.243 / 0.479 / 0.64 |
| 05 tight U | **0.094** / **0.160** / **0.40** | 0.304 / 0.786 / 1.63 |
| 06 closed loop | **0.129** / **0.154** / **0.18** | 0.236 / 0.543 / 0.62 |
| 11 bevel join | **0.118** / **0.395** / 3.37 | 0.173 / 1.256 / 3.46 |
| 16 Y junction | **0.137** / **0.177** / **1.20** | 0.158 / 0.726 / 2.76 |
| 08 butt cap | 0.233 / 7.158 / 9.88 | **0.171** / **3.354** / 9.88 |
| 09 square cap | **0.094** / 9.701 / 13.97 | 0.169 / **0.176** / **0.40** |
| 12 miter join | **0.131** / 1.148 / 14.14 | 0.228 / **0.277** / **1.63** |

**medial-axis wins median centerline error on 18 of 20 cases**, and the margin is
largest exactly where theory says it should be: on *curved* geometry it is 2–3×
more accurate, because morphological thinning follows the 8-connected pixel
lattice and staircases around a curve while the distance-transform ridge does
not. Hausdorff is where the gap is starkest (0.14–0.40 vs 0.62–1.63) — thinning's
worst-case placement error is several times worse even when its median is close.

Thinning wins on **butt caps, square caps and miter joins (08, 09, 12)**, where
`medial_axis` fans out into 5 branches and thinning produces one clean branch.
That is not thinning being more correct — the corner-bisector spurs are genuine
medial-axis structure — it is thinning being *lossy in a convenient way*. Prune
the spurs and the medial axis is ahead there too.

**But on the real ladder the pixel metric cannot tell them apart:**

| image | medial-axis@4+pw | skeletonize@4+pw |
|---|---|---|
| house-wide | 0.03% (55 edges) | 0.03% (45 edges) |
| dinosaur-wide | 0.01% (107 edges) | 0.01% (90 edges) |
| landscape-square | 0.13% (225 edges) | **0.09%** (195 edges) |
| sun-square | 1.73% (35 edges) | **1.64%** (32 edges) |

This is worth stating plainly because it cuts against the track's premise:
**on real artwork, scored by pixels, plain thinning is as good or marginally
better, and it produces a smaller graph and runs ~15% faster.** Sub-pixel
centerline placement barely moves a pixel score dominated by width and coverage,
and thinning's fewer branches mean fewer spurious spurs to render. The case for
the Euclidean medial axis rests on (a) the ground-truth accuracy above, which is
what matters if the centerline is the deliverable rather than the re-render, and
(b) the distance field, below. If Track 6 finds thinning materially faster at
scale, that is a real argument in its favour and this track should not pretend
otherwise.

One nuance for Track 6's comparison: "thinning gives you no distance field" is
only half true — you can always compute the EDT separately, which is what
`skeletonize_mask()` does here so both methods emit populated `radii`. The real
difference is that `medial_axis` *guarantees* its skeleton lies on the distance
ridge, so its radii are the true maximal-inscribed-disk radii; a thinned skeleton
can sit slightly off-ridge and under-reports. Small on this corpus (case 05:
9.98 vs 9.90 against a true 10.00) but systematic, and it is always a
one-directional error.

### 3. Resolution sensitivity — better geometry and more noise, at the same time

Corpus swept at 1, 2, 4, 8, 16 px per SVG unit (stroke radius 10 units):

| | scale 1 | 2 | 4 | 8 | 16 |
|---|---|---|---|---|---|
| case 03 arc, centerline median | 0.197 | 0.212 | 0.075 | **0.053** | 0.054 |
| case 02 diagonal, Hausdorff | 0.71 | 0.35 | 0.19 | 0.25 | **0.04** |
| case 13 X (separate), Hausdorff | 0.71 | 0.36 | 0.25 | 0.09 | **0.05** |
| **case 20 noisy boundary, edge count** | **22** | 31 | 61 | 118 | **289** |

Two opposite trends, both structural:

- Geometry converges; beyond ~8 px per unit the residual is fitting and
  simplification error, not quantization.
- **Spurious branch count grows roughly linearly with resolution.** Every
  boundary wiggle that is sub-pixel at scale 1 becomes resolvable — and therefore
  a medial-axis branch — at scale 16. Case 20 goes from 22 to 289 branches on the
  *same shape*.

Direct consequence for Track 8: **any pruning rule with an absolute length
threshold needs retuning per resolution.** `L / (2·R_med)` does not, because the
spurs have small `R_med` too.

On real art the same tension shows up as a shallow optimum. `house-wide` and
`sun-square` swept at 1/2/4/8 px per unit:

| | scale 1 | 2 | 4 | 8 |
|---|---|---|---|---|
| house-wide pixel diff | 0.06% | 0.04% | 0.03% | **0.02%** |
| house-wide edges | 52 | 54 | **55** | 88 |
| sun-square pixel diff | 1.93% | 1.97% | 1.73% | **1.55%** |
| sun-square edges | 97 | 56 | **35** | 33 |
| avoidable defect tags, both images | 87 | 33 | **15** | 71 |

Scale 1–2 is bad in a different way from scale 8: `sun-square` fragments (97
edges at scale 1 vs 35 at scale 4) because thin taper tails quantize away and the
skeleton breaks up — the `raster quantization` regime. Scale 8 buys ~30% on
smooth-curve centerline error and a little pixel accuracy, at 60% more branches
on house-wide and double the runtime. **Scale 4 is the default here**; scale 8 is
the right choice if a pruning stage will clean up after it.

### 4. The distance field pays for itself twice

The report frames `return_distance=True` as a *pruning* signal (§10). It is, but
it also fixes the single largest reconstruction error on the real corpus, at the
*emission* stage, which the brief did not anticipate.

SVG cannot vary `stroke-width` along one path, so a tapered pen stroke rendered
at one median width is too fat at the ends and too thin in the middle. Because
the graph carries a per-vertex radius, an edge can be split into contiguous runs
of near-constant radius (±18%) and each run emitted as its own constant-width
sub-path — `emit.width_runs`, `--width-mode piecewise`:

| | constant width | piecewise width |
|---|---|---|
| corpus 19 variable-width, IoU | 0.748 | **0.954** |
| `sun-square`, IoU | 0.894 | **0.952** |
| `sun-square`, pixel diff | 3.59% | **1.73%** |
| `landscape-square`, pixel diff | 0.44% | **0.13%** |
| `butterfly-wide`, pixel diff | 0.14% | **0.03%** |
| `house-wide`, pixel diff | 0.09% | **0.03%** |

It improved *every* image on the ladder, and by far the most on `sun-square` —
the pressure-tapered scribble the incumbent struggles with (~4.2% raster, ~6.3%
vector) for exactly this reason. This needed no new geometry, no tuning and no
extra extraction work, only the radius data `medial_axis` already returned. The
progress sheet (`sheets/progress-sun-square.png`) shows it clearly: the taper is
visibly reproduced.

Costs, stated honestly: file size and segment count go up (sun-square 7.2 KB →
17.1 KB, landscape-square 51 KB → 96 KB), and the `excessive curve complexity`
tag count goes from 0 to 10 on the two-image comparison set. §11 says prefer the
simpler graph *when geometry error is comparable* — here it is not comparable, so
the complexity is earned. On a genuinely constant-width shape the splitter mostly
no-ops (corpus case 01 is unchanged at 0.9654). The split threshold (±18%) is the
one hand-chosen constant in the pipeline; it is scale-free (a ratio), and no
image was tuned individually against it.

### 5. Skan is the right graph layer

No reservations. `Skeleton` + `summarize()` gave branch decomposition, ordered
per-branch coordinates, node degrees and branch types with no pixel-neighbour
traversal written by hand, and handled cycles (case 06, `branch_type == 3`) and
multi-junction elements without special-casing. Mapping it into the §13 model is
about 40 lines. Against the incumbent's ~600-line hand-rolled tracer that is a
large architectural simplification, and it is the part of this track that would
transfer to Track 6 unchanged.

API note for whoever follows: `Skeleton(skel, source_image=dist)` +
`path_means()` did *not* return useful radii here (all 1.0). Sample the distance
field directly at `path_coordinates(i)` instead — that is what `extract.py` does.

---

## Failure modes

Tagged with the §13 Experiment 2 taxonomy. Per-run counts are in `metrics.json`
under `tags`, from mechanical detectors (in `metrics.failure_tags` and
`extract._cap_deltas`) so they are comparable with other tracks rather than
hand-curated. `bench.py report` prints them restricted to the image set common to
every row, because a config that ran on 3 images otherwise looks "cleaner" than
one that ran on 10.

| tag | where it shows up here | severity |
|---|---|---|
| `join artifact` | **the main visible defect.** At a T junction the medial axis forks into a Y before the stem reaches the bar; the two short Y arms get round caps and render as a blob past the bar's edge. Clearly visible in the `house-wide` worst-region crops on the comparison sheet. Detected as a non-terminal edge with `normLength < 1.0`. | needs Track 8 |
| `cap artifact` | measured directly: at each degree-1 end, march along the tangent to the outline and compare the reach with the local radius. Round caps give ~0 (corpus case 07: 0 of 2 ends flagged); butt caps give 4 of 4; real art gives 16 of 45 on `house-wide`, i.e. a third of stroke ends genuinely taper rather than being round-capped. | informative |
| `outline noise branch` | terminal branches with `0.2 ≤ normLength < 0.6`. Case 20 by construction; on real art mostly at the outside of pen corners. | Track 8's job |
| `raster quantization` | branches with `normLength < 0.2`. Grows with scale (finding 3): 1 → 27 on the two-image set going from scale 4 to scale 8. | Track 8's job |
| `crossing ambiguity` | degree-4 nodes. Case 14 (unioned X) produces one; 9 across the real ladder. Left undecided in the graph, as instructed. | by design |
| `excessive curve complexity` | > 1.5 Béziers per stroke-width of arc length, counted only on edges at least one stroke width long. 0 in constant-width mode, 10 in piecewise — the measured cost of finding 4. | acceptable |
| `disconnected skeleton` | **not observed** on any real input at any scale tested. The detector compares skeleton component count against mask component count, so an element that legitimately holds several blobs is not counted. | absent |
| `missing narrow segment` | **not observed.** No element with a real mask failed to produce a skeleton. 7 elements in `home-wide` and 1 in `balloon-tall` are sub-pixel specks in the *source* (bboxes of 0.4–0.9 user units) and are reported separately as `subpixelElementsDropped`, not as a failure. | absent |
| `wrong endpoint` | round-cap terminals sit ~0.3–0.4 units inside the true endpoint at scale 4 (3–4% of R). `--cap-extend` removes most of it. | minor, fixable |

### What this backend cannot do

- **Butt and square caps cannot be reconstructed with `stroke-linecap="round"`.**
  This is a *stroke-model* mismatch, not an extraction failure, and the numbers
  separate the two cleanly. Corpus case 08, same geometry, only the linecap
  attribute changed: `round` IoU 0.812 → `butt` IoU **0.915**. The centerline was
  fine all along. Recovering cap *style* is a semantic decision that belongs with
  Track 8 — and the raw material is in the graph: a butt cap leaves a
  characteristic 5-branch fan whose spur lengths are ≈R and ≈R·√2 (measured
  Hausdorff 9.88 ≈ R and 13.97 ≈ R·√2 for radius 10).
- **Variable-width strokes** are only approximated, by piecewise-constant runs.
  A real answer needs a variable-width stroke representation, which SVG 1.1 does
  not have short of emitting an outline — which defeats the purpose.
- **Crossings stay ambiguous by design** (case 14), per the brief.
- **Miter joins** leave a spur along the miter spike (case 12, Hausdorff 14.14).
  Genuine medial-axis structure; another pruning candidate.

---

## Negative and neutral results

Recorded for the other tracks — several of these cost real time here.

- **Feeding fit-curve an RDP-simplified polyline produces garbage.** A
  near-collinear 3-point run makes Schneider's tangent/α solve ill-conditioned
  and it returns control points flung across the canvas — a visible loop that
  still passes the algorithm's own error test. Corpus case 02 scored IoU 0.771
  for exactly this reason while its centerline error was 0.065, i.e. the geometry
  was fine and the fit was not. Fix: fit on a *uniformly arc-length resampled*
  chain (`extract.resample_uniform`, step `R_med/8`) and keep a sanity check that
  rejects control points outside the run's bbox + 35% of its diagonal and
  subdivides instead (`fit_curve.js: sane()`). **Anyone else using fit-curve
  should copy both.**
- **IoU is a weak discriminator for centerline quality and can be
  anti-correlated with it.** Same case: IoU ranked skeletonize (0.858) above
  medial-axis (0.771) while ground truth said medial-axis was 2.7× more accurate.
  If you have ground truth, score against it; IoU is for the real inputs where
  you do not.
- **`--cap-extend` is a wash on real art and a clear win on the corpus.** Marching
  the terminal end to the outline and backing off one local radius (the
  incumbent's `--calibrate-caps` trick) improves corpus centerline error
  consistently — case 05 median 0.094 → 0.032, case 04 0.117 → 0.059, case 13
  0.144 → 0.078 — but on the ladder it changes nothing measurable
  (`house-wide`, `dinosaur-wide` and `sun-square` are 0.03% / 0.01% / 1.73%
  with it and without it). Round-cap retraction is only 3–4% of R to begin with. It is **off** in
  the promoted config and **recommended on** if the centerline itself is the
  deliverable.
- **The first version of cap extension made things worse, and the reason
  generalises.** It extended *both* ends of every skeleton branch, including ends
  that sit at a junction — marching outward from a junction node runs down the
  middle of the crossing stroke and hits the far boundary, so branches were being
  pushed across junctions. Restricting it to degree-1 ends fixed it. The same
  bug in a cap-artifact *detector* had every junction reported as a cap artifact
  (73 of 90 edges, versus 22 after the fix). If your backend marches outward from
  a skeleton end, check the degree first.
- **`corner_window` scaled by local radius, not absolute arc length.** An absolute
  corner window mis-fires between fat and thin strokes in the same drawing;
  `window = 0.9 × R_local` behaves the same on both. No image regressed and the
  sun's hairpins survive fitting, which was the stated risk for this stage.
- **`min_object_px` removal is load-bearing but must not be reported as a
  failure.** Several source files contain sub-pixel path fragments (0.4–0.9 user
  units across). They are correctly dropped; conflating them with lost strokes
  inflates `missing narrow segment` and hides real regressions.

---

## Coordination

- **Track 6 (thinning):** rasterization settings to match are resvg via
  `@resvg/resvg-js@2.6.2`, `fitTo: {mode:'width'}`, `shapeRendering: 2`
  (geometricPrecision), black background, alpha threshold 128 on the red channel,
  scale 4 px per SVG user unit, per-element crop to the element bbox + 2 units,
  `remove_small_objects(12)`. That is `raster.py` + `resvg_render.js`; import them
  directly rather than reimplementing. `extract.skeletonize_mask(mask,
  "skeletonize")` is already the head-to-head harness — adding
  `cv2.ximgproc.thinning` is a two-line change there. Please also check whether
  OpenCV's thinning is deterministic (finding 1).
- **Track 8:** the graph section above is written for you. `normLength`,
  `radiusCv` and `degree` are precomputed; `radiusSource: "native"` distinguishes
  these graphs from tracks that derive radius by sampling. Corpus case 20 at
  scale 16 is a purpose-built pruning stress test with a known answer.
- **Track 5 (Tegaki):** its width-estimation logic is the one thing that could
  improve on finding 4's piecewise-constant hack. If it has a variable-width
  stroke representation, that is directly applicable here.
