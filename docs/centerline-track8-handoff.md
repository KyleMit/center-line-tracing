# Handoff — Track 8: the common graph layer, pruning, and scoring

**Paste this into a fresh session.** It continues the Track 8 work described in
[`centerline-technique-handoffs.md`](./centerline-technique-handoffs.md) § Track 8,
which is now merged to `main` (PR #10). Read this doc first, then
[`debug/pruning-scoring/NOTES.md`](../debug/pruning-scoring/NOTES.md).

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
| Branch | `claude/centerline-smoothness-grading` (off `main` after PR #10 merged) |
| Schema | `centerline-graph/1`, **frozen**, published in `debug/pruning-scoring/SCHEMA.md` |
| Conformance | 460/460 graph files across all 8 backends validate |
| Leaderboard | 79/80 cells, `debug/pruning-scoring/leaderboard.md` |
| A/B | 18 cells, `debug/pruning-scoring/abtest.md` |
| Complexity | 73 graphs, `debug/pruning-scoring/smoothness.md` |
| Tests | `python3 experiments/pruning-scoring/test_clg.py` — all invariants hold |

### Commands

```bash
python3 experiments/pruning-scoring/validate_graphs.py --all      # schema check
python3 experiments/pruning-scoring/test_clg.py                   # invariants
python3 experiments/pruning-scoring/bench.py leaderboard --jobs 4  # 79 cells, ~25 min
python3 experiments/pruning-scoring/abtest.py --jobs 4             # auto vs hand-tuned
python3 experiments/pruning-scoring/smoothness_report.py           # complexity + wobble
python3 experiments/pruning-scoring/synthprune.py                  # held-out pruning corpus
python3 experiments/pruning-scoring/sheets.py cross                # contact sheet
```

### The library

```python
import sys; sys.path.insert(0, "experiments/pruning-scoring")
from clg import CenterlineGraph, svgio, metrics, prune, select, smoothness

src = svgio.load_source("inputs/house-wide.svg")
g   = CenterlineGraph.load("debug/skimage-skan/graphs/house-wide__medial-axis@4.json")
m   = metrics.score_graph(g, src)          # IoU, symmetric difference, boundary, width
best, sweep = select.select(g, src)        # automatic pruning strength
s   = smoothness.graph_smoothness(g)       # wobble, points per stroke width
```

## Results you can rely on

**Backend ranking** (median symmetric difference / source ink, each backend at its
own auto-selected pruning strength):
skimage-skan **0.0186** · opencv-tracing 0.0234 (4 drawings only) ·
native-geometry 0.0265 · autotrace 0.0447 · flo-mat 0.0545 · tegaki 0.0614 ·
polygon-voronoi 0.0690 · incumbent 0.1252.

**skimage-skan is the recommendation** — best on 8 of 10 drawings, and it also
wins on the product goal: 2.20 control points per stroke width and wobble 0.0195
("drawn in one motion", the same band as a mathematically exact arc). Its accuracy
is not bought with micro-adjustment. That was checked, not assumed.

**Hybrid routing is not yet worth it.** Best-backend-per-drawing lands at 0.0173,
only 7% better than skimage-skan alone. The one exception worth routing:
`sun-square` (single scribble, hairpin tips), where polygon-voronoi scores 0.0118
against 0.0341 for the next best.

**Automatic pruning beats hand-tuned thresholds on simplicity, not error.** Against
flo-mat's SAT s=1.3 it gives 23–35% simpler graphs for +0–8% error, and strictly
dominates on `home-wide` (−24% error). See `abtest.md`.

## What to do next, in order

1. **Sweep skimage-skan's raster scale.** It published only scale 4, yet its own
   variants already span 79% on one drawing, and its notes nominate scale 16. This
   is the cheapest remaining win and it is on the leading backend.
   `experiments/skimage-skan/bench.py` takes `--scales`.
2. **Add a curve-fitting pass and measure it with `smoothness_report.py`.** The
   lever for "smoother still" is fitting, not backend choice — skimage-skan already
   exposes a simplify epsilon and can emit Béziers. Target: keep wobble ≤ 0.02
   while cutting points per stroke width. Watch the error axis at the same time; the
   two artifacts above are the right way to look at the trade.
3. **Unify the synthetic corpora.** Each track generated its own, so per-track
   centerline error against *ground truth* is still unmeasured — everything so far
   is reconstruction error. This is the single most useful missing measurement, and
   it is the only way to catch a path that is smooth but in the wrong place.
4. **Fix the `merge_chains` blow-up.** `polygon-voronoi/landscape-square` never
   completes a sweep: `merge_chains` re-queues neighbours with an `endpoint not in
   queue` list scan (O(V²)) and pruning re-canonicalizes every pass for every λ.
   A set-backed queue and an incremental degree map fix it. That is the one missing
   leaderboard cell.
5. **Only then, stroke semantics** (report §13 Experiment 5). Interfaces are already
   in `clg/semantics.py`; nothing is implemented, deliberately.

## Traps — every one of these bit me

- **Canonicalize before pruning, and after every pass.** Backends disagree about
  what an edge is (flo-mat: 426 edges for one noisy capsule; skimage-skan: 61).
  Pruning an un-canonicalized graph at λ=1.0 destroyed it — 426 edges → 11, IoU
  0.77 → 0.28. `merge_chains` is not an optimization, it is a precondition.
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
- **"One variant published" is not "not tunable".** It is unknown. Three backends
  never swept anything.
- **The container suspends between turns.** Long background jobs barely advance
  while you wait on them — run benches in the foreground, and note that
  `bench.py leaderboard` writes `metrics.json` after every cell so a partial run
  survives.

## Feedback owed to the other tracks

In `NOTES.md` §6, worth passing on: tegaki's `prune-length` variant is byte-identical
to `prune-none` on all ten images (its pruning ablation may not reach graph
serialization); tegaki and flo-mat have the endpoint-drift issue above;
skimage-skan's per-vertex `radiusProfile` is worth a 37% error reduction and
consumers should use it; 119 files just need the `"schema"` string added.
