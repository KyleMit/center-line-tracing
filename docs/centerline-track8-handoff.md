# Handoff — Track 8: the common graph layer, pruning, and scoring

**Paste this into a fresh session.** It continues the Track 8 work described in
[`centerline-technique-handoffs.md`](./centerline-technique-handoffs.md) § Track 8.
Read this doc first, then [`debug/pruning-scoring/NOTES.md`](../debug/pruning-scoring/NOTES.md)
— the two addenda at the end of NOTES are the recent work.

## Look at these two first

Both were built from the measured data in this repo and are the fastest way to
understand where things stand:

- **Cross-backend leaderboard** — ranking, per-drawing heatmap, tuning headroom
  <https://claude.ai/code/artifact/d1c6eb2b-7f9f-4784-82bc-92ef556b3044>
- **Path complexity** — the same stroke drawn by all eight backends with control
  points shown, plus wobble and accuracy-vs-complexity
  <https://claude.ai/code/artifact/97a73c4a-f49a-45b2-a562-1deeaac1d157>

They regenerate from `debug/pruning-scoring/metrics.json` and
`debug/pruning-scoring/smoothness.json`; if you re-run the benches, rebuild them.
Both are now slightly stale: the leaderboard gained its 80th cell and four
incumbent cells were corrected (NOTES §11–12).

---

## The product goal, in the owner's words

> "Smooth consistent lines as if drawn by a kid on a digital coloring app. I'd like
> them to closely follow the input design, but not at the expense of tiny micro
> optimizations that look unnatural."

This is the acceptance criterion. It is **not** the same as minimizing
reconstruction error, and the leaderboard alone will mislead you: error rewards a
path that wiggles along the outline. Always read error together with
`smoothness.md`.

## Where it stands

| | |
|---|---|
| Branch | `claude/centerline-track8-handoff-d6mrkw` (off `main` after PR #11 merged) |
| Schema | `centerline-graph/1`, **frozen**, published in `debug/pruning-scoring/SCHEMA.md` |
| Conformance | 461/461 track graph files, plus 149/149 scale-sweep graphs |
| Leaderboard | **80/80 cells**, `debug/pruning-scoring/leaderboard.md` |
| A/B | **30 cells across 3 backends**, `debug/pruning-scoring/abtest.md` |
| Complexity | 73 graphs, `debug/pruning-scoring/smoothness.md` |
| Raster scale | 49/50 cells (10 drawings × 5 scales), `debug/pruning-scoring/scalesweep.md` |
| Ground truth | 100/100 cells (20 truth cases × 5 scales), `debug/pruning-scoring/scalesweep-corpus.md` |
| Tests | `python3 experiments/pruning-scoring/test_clg.py` — all invariants hold |

### Commands

```bash
python3 experiments/pruning-scoring/validate_graphs.py --all      # schema check
python3 experiments/pruning-scoring/test_clg.py                   # invariants
python3 experiments/pruning-scoring/bench.py leaderboard --jobs 4  # 80 cells, ~5 min
python3 experiments/pruning-scoring/lbreport.py                    # <- ALWAYS after the bench
python3 experiments/pruning-scoring/abtest.py --jobs 4             # auto vs hand-tuned
python3 experiments/pruning-scoring/abreport.py                    # <- ALWAYS after the abtest
python3 experiments/pruning-scoring/smoothness_report.py           # complexity + wobble
python3 experiments/pruning-scoring/scalesweep.py --jobs 3         # raster scale, real drawings
python3 experiments/pruning-scoring/scalesweep.py --corpus --jobs 3  # raster scale, ground truth
python3 experiments/pruning-scoring/synthprune.py                  # held-out pruning corpus
python3 experiments/pruning-scoring/sheets.py cross                # contact sheet
```

**The `*report.py` steps are not optional.** `bench.py` and `abtest.py` each write a
`.md` at the end of a run, and it is *not* the published report — `abreport.py`
canonicalizes both sides before measuring complexity, without which flo-mat's
hand-tuned graph looks 7× more complex than it is. Running a bench without its
reporter silently downgrades the committed document. (NOTES §11.)

### The library

```python
import sys; sys.path.insert(0, "experiments/pruning-scoring")
from clg import CenterlineGraph, svgio, metrics, prune, select, smoothness

src = svgio.load_source("inputs/house-wide.svg")
g   = CenterlineGraph.load("debug/skimage-skan/graphs/house-wide__medial-axis@4.json")
m   = metrics.score_graph(g, src)          # IoU, symmetric difference, boundary, width
best, sweep = select.select(g, src)        # automatic pruning strength
s   = smoothness.graph_smoothness(g)       # wobble, points per stroke width
e   = metrics.centerline_error(g, truth)   # vs KNOWN centerlines — synthetic only
```

## Results you can rely on

**Backend ranking** (median symmetric difference / source ink, each backend at its
own auto-selected pruning strength):
skimage-skan **0.0188** · opencv-tracing 0.0265 (4 drawings only) ·
native-geometry 0.0268 · autotrace 0.0448 · flo-mat 0.0589 · tegaki 0.0622 ·
polygon-voronoi 0.0690 · incumbent 0.1325.

**skimage-skan is the recommendation**, and it wins on the product goal as well as
on error: 2.20 control points per stroke width and wobble 0.0195 ("drawn in one
motion", the same band as a mathematically exact arc). Its accuracy is not bought
with micro-adjustment. That was checked, not assumed.

**Run skimage-skan at raster scale 8, not 4.** Across all ten drawings, moving from
its published scale 4 to scale 8 improves **all three axes at once**: error 0.0205 →
0.0188 (−8%), wobble 0.0215 → 0.0178 (−17%), control points per stroke width 2.24 →
1.76 (−21%), for 3.4× the extraction time. Scale 16 is not worth it — flat error,
*worse* wobble than scale 8, and 5.8× the runtime again. Two drawings want scale 2
instead, and they are the two this backend is worst on: `sun-square` (0.0246 vs
0.0390 at scale 4, −37%) and `landscape-square`. NOTES §8–9,
[`scalesweep.md`](../debug/pruning-scoring/scalesweep.md).

**Hybrid routing is worth more than it looked.** Best-backend-per-drawing lands at
**0.0162** against skimage-skan's 0.0188 — 14% better, where the previous
measurement said 7%. The change is one cell: `landscape-square` never used to
finish, and polygon-voronoi wins it (0.0159 against opencv-tracing's 0.0204). So
there are now two drawings where a different backend wins decisively rather than
one — that and `sun-square` (polygon-voronoi 0.0118 vs 0.0341 next best). Both are
polygon-voronoi, and both are the drawings with fine scribbled detail.

**Automatic pruning beats hand-tuned thresholds, and against a genuinely tuned
backend it wins on error too.** Against flo-mat's SAT s=1.3 and tegaki's own rule it
buys 16–35% simpler graphs for +0–8% error. Against polygon-voronoi's PyGeoOps
width-relative filtering it is better on **10 of 10** images — 5 dominating outright,
5 at lower error — and a sweep candidate beat the hand-tuned answer on 10 of 10. See
`abtest.md`.

**Reconstruction error is not centerline error, and now there is one place that
shows the difference.** `clg.metrics.centerline_error` measures distance to *known*
centerlines, split into invented geometry and missed geometry (never averaged — a
pruning sweep trades one for the other). On skimage-skan's 20-case truth corpus,
where the line actually sits converges by scale 4 and stops improving, even though
reconstruction error keeps falling to scale 8. NOTES §10.

## What to do next, in order

1. **Add a curve-fitting pass and measure it with `smoothness_report.py`.** The lever
   for "smoother still" is fitting, not backend choice — skimage-skan already exposes
   a simplify epsilon and can emit Béziers, and the scale sweep shows the two axes
   move together rather than trading off, so there is room. Target: keep wobble
   ≤ 0.02 while cutting points per stroke width. Watch the error axis at the same
   time; the two artifacts above are the right way to look at the trade.
2. **Unify the synthetic corpora.** Still the single most useful missing measurement,
   but the shape of the remaining work has changed: the *measurement* now exists
   (`clg.metrics.centerline_error`, validated against skimage-skan's own
   implementation to 16 digits and covered by `test_clg.py`). What is missing is one
   corpus every track runs, so per-track centerline error becomes comparable. Right
   now each track generated its own with its own geometry.
3. **Decide whether raster scale should be routed per drawing.** The sweep says a
   fixed scale 8 matches the per-image cherry-pick over skimage-skan's three
   published variants (both median 0.0188), and per-drawing scale selection reaches
   ~0.0179. That is a small error gain, but `sun-square` alone is −37%, and choosing
   a raster scale is far cheaper than choosing a backend. The selection rule would
   need a criterion that does not require ground truth.
4. **Re-check why pruning does not keep up with resolution** (NOTES §10). On the
   noisy-boundary truth case, branches surviving automatic pruning go 1 → 4 → 4 → 21
   → 59 across scales 1 → 16. λ is scale-free by construction and the spurs *do* have
   small `R_med`, so this should not happen; either the spur radius estimate is
   contaminated at high resolution or the selection rule is stopping short of the
   right λ. This is a well-posed question with a known correct answer, which makes it
   a good next experiment.
5. **Only then, stroke semantics** (report §13 Experiment 5). Interfaces are already
   in `clg/semantics.py`; nothing is implemented, deliberately.

## Traps — every one of these bit me

- **Canonicalize before pruning, and after every pass.** Backends disagree about
  what an edge is (flo-mat: 426 edges for one noisy capsule; skimage-skan: 61).
  Pruning an un-canonicalized graph at λ=1.0 destroyed it — 426 edges → 11, IoU
  0.77 → 0.28. `merge_chains` is not an optimization, it is a precondition.
- **Never let a harness write into the directory it reads from.** `bench.py` promoted
  each leaderboard winner to `GRAPHS/<track>/<image>.json`, which was also where the
  incumbent's *input* graphs lived, so every run scored the previous run's pruned
  output as "what the incumbent published". Four of ten incumbent cells had drifted
  before it was caught, always in the flattering direction. Two consecutive runs now
  produce identical scores; if you add a track, check that its inputs are not under
  `debug/pruning-scoring/graphs/`.
- **Profile before believing a written-down diagnosis — including one in this file.**
  The previous handoff said `polygon-voronoi/landscape-square` never finished because
  `merge_chains` is O(V²). It is not: on that graph `merge_chains` takes 0.0 s and
  makes zero merges. The cost was unindexed point-to-boundary distance in
  `metrics.boundary_distances`, 97 s per `score_graph`. Indexing it was a 13× speedup
  on that cell and made the whole leaderboard 4× faster. A confident diagnosis that
  nobody profiled became the next session's task list.
- **Source polygons need real fill-rule handling.** Ring-parity nesting inflated
  `house-wide`'s area 25% and made every backend look like it was missing a fifth of
  the drawing. `svgio` nodes the rings, polygonizes, and classifies faces by winding
  number. If a new metric says everyone is failing, suspect the metric.
- **`src/compare.js` measures something else.** It diffs *colour* over the whole
  canvas; the vector metric is symmetric difference over *ink*. The incumbent's
  0.02% is ~0.5% of ink and grows to 0.05% at native resolution. Quote both or
  neither. A re-emitted black SVG scores ~3.7% against a coloured input for no
  geometric reason at all.
- **Chain merging must not assume edges meet at their shared node.** tegaki and
  flo-mat let geometry drift up to 13.7 units from the node. Dropping the shared
  vertex unconditionally deleted 997 units² across 51 fragments.
- **"One variant published" is not "not tunable".** It is unknown, and on the leading
  backend it was worth 8% error and 17% wobble. Three backends never swept anything.
- **The container suspends between turns.** Long background jobs barely advance
  while you wait on them — run benches in the foreground, and note that
  `bench.py leaderboard` and `scalesweep.py` both write after every cell so a partial
  run survives. Budget for it: `scalesweep.py --scales 16` did not finish
  `dinosaur-wide` in 45 minutes, which is the one missing cell of fifty.

## Feedback owed to the other tracks

In `NOTES.md` §6, worth passing on: tegaki's `prune-length` variant is byte-identical
to `prune-none` on all ten images (its pruning ablation may not reach graph
serialization); tegaki and flo-mat have the endpoint-drift issue above;
skimage-skan's per-vertex `radiusProfile` is worth a 37% error reduction and
consumers should use it; 119 files just need the `"schema"` string added.

New, for **skimage-skan** specifically: promote scale 8 rather than 4 (NOTES §8), and
note that the "scale 8 is fine if a pruning stage cleans up after it" conjecture in
that track's notes is measurably false — the pruning stage does not keep up
(NOTES §10). The accuracy argument for scale 8 survives; the cleanup argument does not.
