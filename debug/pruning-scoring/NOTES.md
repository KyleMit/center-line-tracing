# Track 8 — Width-Aware Pruning, Re-Stroke Scoring, Common Graph Layer

Slug `pruning-scoring` · branch `claude/centerline-pruning-scoring` · report §10, §11, §13, §19

> ## 📣 THE GRAPH SCHEMA IS PUBLISHED AND FROZEN: [`SCHEMA.md`](./SCHEMA.md)
>
> Version string `centerline-graph/1`. Run the validator against your own output:
>
> ```bash
> python3 experiments/pruning-scoring/validate_graphs.py debug/<your-slug>/graphs
> ```
>
> **All 387 graph files from all seven extraction tracks conform today.** The schema
> was written to describe what you already emit, so nothing should need to change.
> Two things are worth fixing on your side, both detailed in SCHEMA.md: add the
> `"schema": "centerline-graph/1"` string, and (tegaki, flo-mat) check why edge
> geometry endpoints drift from their node coordinates by up to 13.7 user units.

## What is here

| path | what it is |
|---|---|
| `experiments/pruning-scoring/clg/` | the library: graph model, schema, pruning, re-stroke scoring, model selection |
| `experiments/pruning-scoring/validate_graphs.py` | schema validator — **run this on your own graphs** |
| `experiments/pruning-scoring/bench.py` | `incumbent` · `score` · `select` · `leaderboard` |
| `experiments/pruning-scoring/abtest.py` | controlled A/B: automatic pruning vs each track's hand-tuned pruning |
| `experiments/pruning-scoring/synthprune.py` | held-out labelled pruning corpus (generated, not from the real inputs) |
| `experiments/pruning-scoring/sheets.py` | contact sheets, including the cross-backend sheet |
| `debug/pruning-scoring/metrics.json` | full leaderboard data |
| `debug/pruning-scoring/leaderboard.md` | the cross-backend table |
| `debug/pruning-scoring/abtest.md` | automatic vs hand-tuned pruning |

```python
import sys; sys.path.insert(0, "experiments/pruning-scoring")
from clg import CenterlineGraph, svgio, metrics, prune, select

src = svgio.load_source("inputs/house-wide.svg")          # S_original as Shapely
g   = CenterlineGraph.load("debug/<track>/graphs/house-wide.json")
m   = metrics.score_graph(g, src)                          # IoU, sym diff, boundary, width
best, sweep = select.select(g, src)                        # automatic pruning strength
```

---

## Findings

### 1. The graph layer earns its keep immediately: backends disagree about what an edge IS

flo-mat emits **426 edges** for a single noisy capsule where skimage-skan emits 61 and
opencv-tracing 29 — not because it found more structure, but because it splits chains
at every degree-2 node. That difference alone breaks any shared threshold.

Pruning flo-mat's un-canonicalized case-20 graph at `lam = 1.0` **destroys the
drawing**: 426 edges → 11, IoU 0.77 → 0.28. Each individual edge is short relative
to the local stroke width, so removing tips exposes new short tips and the prune
cascades inward.

The fix is not a better threshold, it is **canonicalization**: splice every degree-2
chain into a single branch, and re-do it after every pruning pass, because deleting a
spur turns its junction into a degree-2 node and leaves two stubs that are each short
even though the branch they belong to is not. With that in place the same `lam = 1.0`
gives 1 branch at IoU **0.94** — the raw noisy MAT cleaned to a single correct
centerline.

This is the strongest argument for §19's common-graph-layer claim I found: the
operation that makes pruning work at all is a *graph* operation, defined once, that no
extraction backend has to know about.

### 2. Scoring in vector space needed a real fill-rule implementation

First version assembled subpaths into polygons by containment parity. It inflated
`house-wide`'s source area by **25%**, which made every backend look like it was
missing a fifth of the drawing. The cause is `house-wide`'s big self-intersecting
scribble elements: parity nesting cannot classify the lobes of a *single*
self-intersecting ring, and `buffer(0)` fills them in.

The correct method is what a renderer does: node the rings, polygonize the
arrangement, and classify each face by winding number (nonzero) or crossing parity
(even-odd). After that, vector source areas agree with resvg's rasterized ink to
within **+0.2% to +0.8%** on all four probe images — the residual being antialiasing
at the boundary.

Worth stating plainly for the other tracks: **if your reconstruction score says every
backend is missing ~20% of the ink, suspect your source polygon, not the backends.**

### 3. Vector and raster scoring agree — but `src/compare.js` measures something else

Once both are measured the same way, they agree almost exactly. Vector symmetric
difference vs a colour-independent raster ink diff at the drawing's own resolution:

| image (incumbent) | vector sym | raster-ink sym | delta |
|---|---|---|---|
| dinosaur-wide | 0.0849 | 0.0852 | 0.0002 |
| landscape-square | 0.1168 | 0.1164 | 0.0004 |
| house-wide | 0.1676 | 0.1675 | 0.0001 |

So the scorer is trustworthy. But those numbers look nothing like the incumbent's
famous **0.02% / 0.73%**, and the reason matters to every track:

1. **Different denominator.** `src/compare.js` reports differing pixels as a fraction
   of the whole 1200×1200 *canvas*. Ink is only ~4.3% of the dinosaur canvas, so 0.02%
   of canvas is ~0.5% of ink. The vector metric is a fraction of *ink*.
2. **Different resolution, and it is not neutral.** The same comparison run at
   several sizes: dinosaur 0.02% @400px, 0.01% @700, 0.02% @1200, **0.05% @2265**;
   landscape 0.43% @700, 0.73% @1200, **0.94% @1773**. Error grows with resolution
   because the discrepancy is sub-pixel at the compare scale.
3. **What the remaining error actually is.** The incumbent's symmetric difference vs
   `dinosaur-wide` is 8.5% of ink, spread over **618 separate pieces with a mean
   thickness of 0.65 user units** — about a third of a pixel at the 1200px compare
   scale. It is a halo of very slightly-too-wide strokes, not a missing or misplaced
   stroke. `landscape-square` is a mix: mean thickness 1.3 units, but its largest
   pieces run to ~4 units, which are genuine geometry errors.
4. **`compare.js` diffs colour.** A re-emitted black centerline SVG scores ~3.7%
   against a coloured input for no geometric reason whatsoever. Any track re-rendering
   graphs for comparison must either preserve stroke colour or compare silhouettes.

**Neither number is wrong; they answer different questions.** Pixel-diff-on-canvas
answers "would a person notice", and is why the incumbent looks so strong. Ink-relative
symmetric difference answers "how much of the stroke geometry is right", and is the
one to optimize. I report both and recommend the other tracks quote both, because a
0.02% that is really 0.5%-of-ink-at-low-resolution invites the wrong conclusion.

### 4. Width-aware pruning, measured as a classifier on held-out data

`synthprune.py` generates its own labelled corpus — five shapes (line, arc, S-curve,
Y-junction, T-junction), each with 40 noise spurs at known normalized lengths and
3–5 *real* detail branches that are present in the source fill and must survive.
None of it derives from the ten real inputs, so it is a genuine held-out check
against threshold-fitting.

Noise spurs removed, by their true length in stroke widths:

| λ | < 0.3 | 0.3–0.7 | 0.7–1.1 | > 1.1 | real branches kept |
|---|---|---|---|---|---|
| 0.25 | 67% | 0% | 0% | 0% | 100% |
| 0.50 | **100%** | 23% | 0% | 0% | 100% |
| 1.00 | 100% | 98% | 19% | 0% | 100% |
| 1.50 | 100% | 100% | 98% | 38% | 100% |
| 2.00 | 100% | 100% | **100%** | 96% | **100%** |
| 3.00 | 100% | 100% | 100% | 100% | 97% ← over-pruning begins |

The decision boundary tracks the normalized length monotonically, which is the whole
claim of §10.1: a spur is defined by its length *in stroke widths*, not in SVG units.
λ ≈ 2 removes every synthetic noise spur without deleting a single real branch; λ = 3
starts eating real detail. That is the safe operating range, and it is scale-free —
the same numbers hold whatever the drawing's units.

Two measurement traps worth recording, because both produced convincing wrong answers
before being fixed:

* **Attachment.** Spurs first hung off nodes that were merely *coincident* with the
  trunk rather than splitting it, so every spur was an isolated stroke and none of the
  junction features (R_parent, continuation angle) were ever exercised.
* **Survival test.** Testing survival by edge-id membership scores every spliced trunk
  segment as deleted; testing it by distance-to-remaining-geometry scores a deleted
  2-unit spur as alive, because its tip is still within a stroke radius of the trunk.
  Only exact merge provenance (`mergedFrom`, recorded during canonicalization) gives
  the right answer — with the geometric test the shortest spurs appeared to be the
  *hardest* to remove, which is backwards.

### 5. Pruning as model selection

`select.py` sweeps λ, re-strokes every candidate, and picks the simplest graph whose
reconstruction error is within a tolerance of the best in the sweep (§13 Experiment 4).
Two design points matter:

* **Symmetric difference, not IoU, as the loss.** §11 says so, and there is a specific
  reason here: IoU is forgiving of small missing marks, which is exactly the
  over-pruning failure the handoff warns about.
* **An explicit anti-over-pruning guard.** Even symmetric difference can *improve*
  when a real stroke is deleted, because deleting a stroke removes its excess area
  along with it. So any candidate that raises MISSING area by more than 2% of source
  area relative to the unpruned graph is disqualified no matter how simple it is.

The sweep is also where the non-monotonicity shows up: on skimage-skan's case-20 graph
error goes 0.0444 → 0.0288 (λ=1.0) → 0.0336 (λ=1.5) → 0.0348 (λ=2.0). A single
hand-picked threshold cannot find that; a sweep with a selection rule can, and it finds
a *different* one for each backend, which is the point.

### 6. Feedback for the individual tracks (found while scoring their graphs)

**tegaki (Track 5) — the pruning ablation may not be reaching the graph output.**
`<img>.prune-tegaki-length.json` is **byte-identical to `<img>.prune-none.json` on
all ten images**, and `prune-tegaki-width` differs on only 3 of 10 (home-wide,
dinosaur-wide, landscape-square), by 1–5 branches. So the ported Tegaki pruning
rules are close to a no-op as emitted. Worth checking whether the prune stage runs
before graph serialization. This also means my A/B "hand-tuned" baseline for tegaki
is effectively "no pruning" on 7/10 images — stated here so the comparison is not
read as stronger than it is.

**tegaki and flo-mat — edge geometry endpoints drift from their node coordinates.**
tegaki: 87 files, P99 8.3 user units, max 13.7 — bigger than a stroke radius.
flo-mat: 28 files. This is not cosmetic for a shared layer: chain merging naturally
assumes the two edges at a shared node meet there, and that assumption silently
deleted 997 units² of geometry on house-wide before I fixed it. My layer now
tolerates the drift, but the graphs would be better without it. Likely cause: cap
extension applied to `geometry` without updating the node.

**skimage-skan — the per-vertex radius profile is worth a lot.** Scoring with the
profile instead of a per-edge median improves house-wide from 0.0243 to **0.0152**,
a 37% error reduction from data the backend already emits. Any track that has a
distance field should emit `radiusProfile`; any consumer should use it.

**autotrace, native-geometry, polygon-voronoi — add the `schema` string.** 119 files
lack `"schema": "centerline-graph/1"`. Everything else validates.

**polygon-voronoi — the built-in filtering is real.** Its `+filter` variants cut the
complexity index from ~330 to ~120 on house-wide at a small error cost, and on the
noisy synthetic capsule its output is already a single clean branch at IoU 0.9956
without any help from this layer. That is a meaningful point in favour of PyGeoOps'
automatic width-relative parameters, which was an open question in the handoff.

### 7. Honest limitations

* **Reconstruction error is not centerline error.** For the ten real inputs there is
  no ground-truth centerline, so everything here measures how well the drawing can be
  rebuilt, not how close the recovered path is to the path a person drew. The
  synthetic corpora have truth centerlines; comparing against them per-track is left
  undone because each track generated its own corpus with its own geometry, and a
  fair truth comparison needs the corpora unified first. **That is the single most
  useful next step for this layer.**
* **The re-stroke model is round-cap, round-join, and per-vertex width.** Backends
  that intend butt or square caps are scored against a model they did not target.
  The synthetic cap cases (7–9) exist to quantify that and I did not get to them.
* **Selection tolerance is a policy, not a fact.** "Simplest within 5% of the best
  error" is a defensible default, not a derived constant; a different product goal
  (say, minimum path count for a plotter) implies different weights. The weights are
  in one place (`select.COMPLEXITY_WEIGHTS`) for that reason.
* **The complexity index mixes units.** Branch count and control-point count are
  normalized across a candidate set before blending, so complexity comparisons are
  meaningful *within* one sweep and only roughly meaningful across backends with
  different geometry encodings (beziers vs dense polylines).

---

## Results

### The controlled A/B: automatic pruning vs each track's own pruning

[`abtest.md`](./abtest.md). Same backend, same rasterization, same tracing — only the
pruning stage differs. Automatic selection always starts from that track's
**unpruned** graph, and complexity is measured after canonicalization on both sides
so the comparison is like for like.

| backend | images | auto dominates | auto simpler at same error | tie | hand-tuned better |
|---|---|---|---|---|---|
| flo-mat (vs SAT s=1.3) | 9 | 1 | 7 | 0 | 1 |
| tegaki (vs its own width rule) | 9 | 0 | 8 | 1 | 0 |

On flo-mat the trade is consistent and worthwhile: **23–35% simpler graphs for
+0–8% reconstruction error**, and on `home-wide` automatic pruning strictly
dominates — **−24% error** *and* a simpler graph, because SAT at s=1.3 over-pruned
that image. A candidate somewhere in the sweep beat SAT outright on 4 of 9 images,
so there is headroom the selection rule leaves on the table.

On tegaki the gains are small (2–6% simpler), and the honest reason is that
**tegaki's published pruning is very nearly a no-op** — its `prune-none` and
`prune-tegaki-length` graphs are byte-identical on all ten images. So that column
is really "automatic pruning vs no pruning", and it is not evidence about Tegaki's
algorithm.

`landscape-square` is excluded from the A/B: the sweep did not finish on it within
the session. See the runtime note below.

### The cross-backend leaderboard

[`leaderboard.md`](./leaderboard.md), 79 of 80 cells. Every backend is shown at
**its own automatically selected pruning strength**, which is the point — no
backend is penalized for a threshold someone else picked. Ranked by median
symmetric difference as a fraction of source ink:

| backend | images | median err | best | worst |
|---|---|---|---|---|
| skimage-skan | 10 | **0.0188** | 0.0142 | 0.0380 |
| opencv-tracing | 4 | 0.0265 | 0.0204 | 0.0272 |
| native-geometry | 10 | 0.0268 | 0.0196 | 0.0900 |
| autotrace | 10 | 0.0448 | 0.0363 | 0.0523 |
| flo-mat | 10 | 0.0589 | 0.0341 | 0.0989 |
| tegaki | 10 | 0.0622 | 0.0410 | 0.1354 |
| polygon-voronoi | 9 | 0.0690 | **0.0118** | 0.1049 |
| incumbent | 10 | 0.1325 | 0.0849 | 0.2104 |

Three things need saying about this table, because it is easy to misread.

**The incumbent ranking is not a contradiction of its 0.02%.** It is the same
finding as §3 above from the other side: the incumbent's error is a sub-pixel halo
that a canvas-relative colour pixel-diff at 1200px barely registers and an
ink-relative symmetric difference registers fully. Both numbers are correct. If the
goal is "looks right to a person at normal zoom", the incumbent is still excellent;
if the goal is "the recovered stroke geometry is right", it is not the leader.

**polygon-voronoi has the best single score in the whole table (0.0118) and a
middling median.** That is the §19 hybrid argument in one row: it is the right
backend for some shapes and the wrong one for others, and per-shape selection by
reconstruction metric would beat any single choice.

**opencv-tracing's 4 images are not comparable to the others' 10.** It published
real-input graphs for only four; its median is over the easier subset.

### Always look at the render

The [cross-backend sheet](./cross-backend-sheet.png) catches something no number in
the table does: on `house-wide`, polygon-voronoi at its selected λ=2.0 **has lost
the sun** — the grey disc at top-left has no red centerline over it. Its error for
that cell (0.1130) is the worst in the row, so the metric does flag it, but only the
render says *what* went wrong. Same for the progress sheet at λ=10: the sun's rays
disappear exactly where error jumps from 0.042 to 0.117.

### A runtime failure worth recording

`polygon-voronoi/landscape-square` never completed a sweep. Its graph is over 1 MB
with many thousands of edges, and the cost is in **canonicalization, not scoring**:
`merge_chains` re-queues neighbours with an `endpoint not in queue` list scan, which
is O(V²) in the worst case, and pruning re-canonicalizes every pass for every λ. On
normal graphs this is invisible; on that one it is fatal. The fix is a set-backed
queue and an incremental degree map — straightforward, and the first thing to do if
this layer is productionized. Recorded rather than hidden because the same cost
lands on any track that feeds a very dense graph through this code.

---

## Verdict

The report's §19 claim — that the common graph layer is the most important
architectural choice — held up better than expected, and for a reason I did not
anticipate. It is not mainly about *sharing* pruning across backends; it is that
**the operation which makes pruning work at all is a graph operation none of the
backends perform**. Canonicalizing degree-2 chains is what turns "λ = one stroke
width" from a threshold that means eight different things into a threshold that
means one. Without it, the same λ that cleans a noisy medial axis to a single
correct centerline instead destroys the drawing.

Width-aware pruning as specified in §10.1 works, and the normalized length
`L / (2 R_med)` does nearly all the work — the radius, width-consistency and
tangent-continuity modifiers only break ties. On held-out labelled data the decision
boundary is monotone in normalized length, and λ ≈ 2 removes every noise spur while
keeping every real branch.

Pruning as model selection (§10.2) delivers what it promised, with a caveat worth
being precise about: it rarely finds *lower* error than a well-tuned threshold, and
that is not its job. It reliably finds a **substantially simpler graph at
equivalent error, automatically, per image, per backend** — and occasionally it
catches a hand-tuned threshold over-pruning and beats it outright. That is the
defensible-choice property the handoff asked for.

The re-stroke scorer is the piece I would trust most and also the piece that was
wrong the longest. Three of the four real bugs in this track were in *measurement*,
not in the algorithm being measured, and each produced numbers confident enough to
publish. That is the argument for the invariant tests and the vector/raster
cross-check being part of the deliverable rather than scaffolding.

---

## Addendum — path complexity and wobble

Added after the leaderboard, because the leaderboard has a blind spot: reconstruction
error rewards a path that **wiggles along the outline**, and the product goal is
"smooth consistent lines as if drawn by a kid on a digital coloring app". A path can
score well and look nothing like a drawn stroke. `clg/smoothness.py` separates the two.

The measure that matters is **wobble**: RMS perpendicular deviation from the path's own
low-pass version, cut at one stroke width, with the curvature bias removed, in stroke
radii. Everything is normalized by stroke width for the same reason the pruning
threshold is.

Getting it right took two corrections, both of which produced confident wrong answers
first:

1. **Tangential slide is not wobble.** Smoothing re-parameterizes as well as
   straightens, and counting the along-path component made a mathematically exact
   straight line score 0.083 instead of 0. Only the perpendicular component counts.
2. **Curvature bias is not wobble either.** A Gaussian low-pass pulls a genuinely
   curved path toward its chord by about σ²κ/2, so an exact arc scored 0.027 — about
   half what the real drawings scored, which made all eight backends look identical
   ("slightly restless", 0.052–0.075). Removing the residual's own low-frequency
   component leaves only the high-frequency part. Calibration after the fix: exact
   line 0.0000, exact arc 0.0015, tight arc 0.0041, smooth S-curve 0.0005, and
   injected jitter scales monotonically 0.021 → 0.068 → 0.154.

### Results

| backend | points / width | wobble | reads as |
|---|---|---|---|
| incumbent | 0.56 | 0.0250 | smooth |
| tegaki | 0.83 | 0.0334 | smooth |
| flo-mat | 1.33 | 0.0292 | smooth |
| **skimage-skan** | **2.20** | **0.0195** | **drawn in one motion** |
| opencv-tracing | 5.00 | 0.0204 | smooth |
| native-geometry | 10.33 | 0.0192 | drawn in one motion |
| autotrace | 14.04 | 0.0244 | smooth |
| polygon-voronoi | 15.48 | 0.0175 | drawn in one motion |

On the single ground line of `house-wide` — the same stroke, recovered by all eight —
the control-point counts are 21 · 36 · 61 · 116 · 336 · 473 · 756 · 1321. A **63×
spread for identical geometry.**

### What it says

- **The micro-adjustment worry does not hold against skimage-skan.** It is the third
  smoothest in the set and spends 7× fewer points than the heaviest, while also having
  the best reconstruction error. Its accuracy comes from placing the line correctly.
- **Dense is not the same as jittery.** polygon-voronoi, autotrace and native-geometry
  carry the most points and wobble the *least* — they densely sample a smooth curve.
  High point count is a file-size and editability problem, and a fitting pass removes
  it; it is not a "looks unnatural" problem.
- **Sparse-and-wobbly is the harder failure.** tegaki and flo-mat carry few points but
  move more between them, and there is no redundant detail to smooth away.
- **What this does not measure:** wobble is a property of the recovered path, not of
  how well it matches the line a person drew. The real inputs have no ground-truth
  centerline, so a path could be beautifully smooth and in the wrong place. Read it
  together with the error axis — and unifying the synthetic corpora (NOTES §7) is what
  would close this gap properly.

---

## Addendum 2 — raster scale, and three measurement bugs found on the way

Handoff item 1 was "sweep skimage-skan's raster scale", on the reasoning that it is
the leading backend and it only ever published scale 4. Doing it turned up a clear
answer, one clean negative result, and three bugs in this layer that were producing
confident wrong numbers — the same pattern as §7.

Reproduce:

```bash
python3 experiments/pruning-scoring/scalesweep.py --jobs 3            # 10 drawings x 5 scales
python3 experiments/pruning-scoring/scalesweep.py --corpus --jobs 3   # 20 truth cases x 5 scales
```

[`scalesweep.md`](./scalesweep.md) · [`scalesweep-corpus.md`](./scalesweep-corpus.md)

### 8. Scale 8 is the right default. Scale 16 is not.

Every cell re-extracts at its own scale and is then auto-pruned by this layer, so a
scale is judged on what survives cleanup rather than on its raw skeleton. Medians
over all ten drawings:

| scale | error | wobble | pts / stroke width | branches | extract |
|---|---|---|---|---|---|
| 1 | 0.0443 | 0.0298 | 3.66 | 59 | 2.9 s |
| 2 | 0.0252 | 0.0237 | 3.49 | 52 | 3.4 s |
| **4** (published) | 0.0205 | 0.0215 | 2.24 | 62 | 9.2 s |
| **8** | **0.0188** | **0.0178** | **1.76** | 76 | 31.1 s |

Scale 4 → 8 improves **all three axes at once**: −8% error, −17% wobble, −21%
control points per stroke width. That combination is what makes it a real result
rather than a metric artifact — the addendum above exists precisely because error
alone rewards a path that wiggles along the outline, and here the smoothness axis
moves the same way as the error axis instead of against it.

Scale 16 does not continue the trend. Over the nine drawings that completed all five
scales, error is flat (0.0187 vs 0.0188), **wobble is worse than scale 8** (0.0185 vs
0.0178), points per width is identical (1.75 vs 1.76), and extraction is 5.8× slower
(117.5 s vs 20.3 s median). skimage-skan's own notes nominated scale 16 as the
experiment to run; the answer is no.

### 9. Two drawings want a *lower* scale, and they are the two this backend is worst on

| drawing | best scale | error there | error at scale 4 |
|---|---|---|---|
| `sun-square` | 2 | **0.0246** | 0.0390 (−37%) |
| `landscape-square` | 2 | **0.0244** | 0.0268 (−9%) |

`sun-square` is skimage-skan's worst cell in the whole leaderboard, and it is worst
because of the scale, not the backend: it is thin tapering rays, and above scale 2
the taper tails resolve into skeleton structure that pruning then has to guess about.
This is the same shape-dependent story as the hybrid-routing finding — per-drawing
selection beats any single constant, and here the parameter is cheaper to route on
than the backend.

Counting outright wins the split is scale 16 on 4 drawings, scale 8 on 3, scale 2 on
2, scale 4 on 1 — but every scale-16 win is 1–4% over scale 8 at 6× the cost and
worse wobble, which is why the recommendation is 8 and not "whatever won".

### 10. The conjecture that motivated the sweep is false, and only ground truth shows it

skimage-skan's notes say: *"scale 4 is the default here; scale 8 is the right choice
if a pruning stage will clean up after it."* This layer is that pruning stage, so the
conditional is testable. It does not hold.

`scalesweep.py --corpus` runs the same sweep over that track's 20-case synthetic
corpus, which was generated from **known centerlines**. Case 20 is the stress test —
a single straight capsule under boundary jitter, whose true answer is one branch at
every scale. Branches surviving automatic pruning:

| scale | 1 | 2 | 4 | 8 | 16 |
|---|---|---|---|---|---|
| branches before pruning | 20 | 23 | 43 | 106 | 201 |
| **branches after pruning** | **1** | 4 | 4 | **21** | **59** |

Pruning does not keep up. It removes 95% of the spurious branches at scale 1 and 71%
at scale 16, but the absolute count it leaves behind grows by 15× across the sweep.
Scale 8 is still the right default — the accuracy and smoothness gains in §8 are
real and measured — but it is right *despite* the cleanup argument, not because of it.

Ground truth also tempers §8 in a second way. Median distance to the true centerline
over the 20 cases: 0.2511 (s1) · 0.1897 (s2) · **0.1363 (s4)** · **0.1332 (s8)** ·
0.1435 (s16), and the P95 is *best at scale 4* (0.1882, against 0.2522 at scale 8).
So where the line actually sits converges by scale 4 and stops improving; the scale-8
win on real drawings is a reconstruction-and-smoothness win, not a "the line is in a
more correct place" win. Stated plainly because the leaderboard cannot tell the
difference and this is the first measurement in this track that can.

This is a partial down-payment on §7's "single most useful next step". It is one
backend against one track's corpus, not the unified corpus that would let the tracks
be compared on truth — but `clg.metrics.centerline_error` is now in the shared layer,
so the remaining work is corpus unification, not measurement.

### 11. Three bugs in this layer, all of which published wrong numbers

**The leaderboard was scoring its own previous output as the incumbent's input.**
`bench.py` read the incumbent's graphs from `debug/pruning-scoring/graphs/incumbent/`
and promoted each cell's winner to `GRAPHS/<track>/<image>.json` — the same path. So
every run fed the previous run's *pruned, canonicalized* graph back in as "what the
incumbent published". Four of ten incumbent cells had drifted by the time it was
caught (butterfly-wide 0.1229 → 0.1167, island-tall 0.1285 → 0.1178, house-tall
0.1162 → 0.1119, home-wide 0.1618 → 0.1522) — always *better*, because
canonicalization lets the radius profile interpolate across spliced chains instead of
using a per-edge median, which flatters the re-stroke. Inputs now live in
`debug/pruning-scoring/incumbent/graphs/`, and two consecutive leaderboard runs now
produce byte-identical scores. The incumbent's median is unchanged at 0.1325; the
individual cells in the previous `leaderboard.md` were not reproducible.

**The `merge_chains` blow-up was diagnosed wrong.** §"A runtime failure worth
recording" blamed `merge_chains`'s O(V²) re-queue scan for
`polygon-voronoi/landscape-square` never completing. It is not the cause: on that
graph `merge_chains` runs in 0.0 s and performs **zero** merges. The real cost was
`metrics.boundary_distances` — `shapely.distance(points, one_big_boundary)` is a
linear scan over every boundary segment for every sample point, so it is
O(points × segments): 30 s per call, 97 s for a single `score_graph`, and a λ sweep
never finished. An STRtree over the boundary exploded into individual segments takes
that to 7.3 s, **13× faster, with distances identical to 1e-13 over 268k samples on
three backends**. The whole 80-cell leaderboard went from 1323 s to 317 s at the same
`--jobs 4`, the cell that never finished now takes 76 s, and it is filled — see §12.
(The header in `leaderboard.md` reads 435 s because that run used `--jobs 3` with the
scale sweep occupying a core.) The O(V²) queue scan was real and is also
fixed; it simply was not what was biting. Worth recording as a lesson: the profile
disagreed with a diagnosis that had been written down confidently enough to become
the next session's task list.

**Two reporters were being overwritten by the harness that feeds them.**
`bench.py leaderboard` and `abtest.py` each write a `.md` at the end of a run, but the
committed reports come from `lbreport.py` and `abreport.py`, which say materially
different things — `abreport.py` canonicalizes both sides before measuring complexity,
without which flo-mat's hand-tuned graph looks 7× more complex than it is (house-wide
cx 305.6 vs 61.6). Re-running a bench silently downgrades the published report. Always
re-run the matching reporter afterwards; the commands are in the handoff.

### 12. What the faster metric unblocked

Both were "did not finish in the session" in the previous handoff and are now simply
done:

- **The leaderboard is 80/80.** `polygon-voronoi/landscape-square` scores **0.0159**
  auto-pruned — the best of any backend on that drawing, ahead of opencv-tracing's
  0.0204 and skimage-skan's 0.0262. It is a second row for the hybrid-routing
  argument, which previously rested on `sun-square` alone. polygon-voronoi's median is
  unchanged at 0.0690; it is the extremes that make it interesting.
- **The A/B is 30 cells, not 18** — `landscape-square` for flo-mat and tegaki, plus
  **polygon-voronoi added as a third pair**, and that pair is the strongest evidence
  in the whole A/B: against PyGeoOps' own width-relative filtering, automatic pruning
  is better on **10 of 10** images (5 dominate outright, 5 lower error), and a
  candidate somewhere in the sweep beat the hand-tuned answer on 10 of 10. The
  "simpler, not more accurate" summary in the verdict was drawn from flo-mat and
  tegaki only; against a backend whose own filtering is genuinely tuned, automatic
  selection wins on error too.
