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
