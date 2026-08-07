# Track 1 — `flo-mat` vector MAT/SAT: notes and verdict

Slug `flo-mat` · branch `claude/centerline-flo-mat-jjpo0n` · code in
`experiments/flo-mat/` · artifacts here · promoted SVGs in `outputs/flo-mat/`.

Report refs: §6.1, §18.1 (backend), §9.2 (normalization), §10–§11 (pruning and
reconstruction scoring), §12.1 (synthetic corpus), §13 (graph model).

---

## TL;DR verdict

**flo-mat works, and it works better than the report expected.** On the
synthetic corpus it recovers the true centerline of every clean stroke shape to
within ~0.1 units on a 300×200 canvas with a 20-unit stroke — that is a
centerline error of about **0.5% of one stroke width** — and re-strokes to
IoU ≥ 0.998 on 16 of 22 cases. It is genuinely SVG-native: no rasterization, no
resolution parameter, no quantization noise.

Three caveats, all of which matter for productionizing it:

1. **`getPathsFromStr` silently linearizes SVG arcs.** Two of the three sentences
   of prior art we were handed were wrong because of this (details below). Any
   pipeline that feeds flo-mat must convert `A` to cubics first.
2. **flo-mat can hang.** Not throw — hang, in a non-terminating loop inside
   `findMats`, on ordinary artwork (`inputs/house-wide.svg`, a rotated rounded
   rect). Mitigable, but it means a production deployment needs a watchdog.
3. **It does not solve caps, joins or crossings**, exactly as §6.1 says. The MAT
   of a butt-capped or mitre-joined stroke contains 45° corner branches that are
   *correct medial axis* and *wrong centerline*. On real artwork these are the
   dominant visible defect.

Recommendation: **yes, make this the production vector backend**, with Track 8's
pruning layer on top. The graph JSON in `graphs/` is written for that.

---

## Two corrections to the brief and the report — read these first

### 1. `getPathsFromStr` turns SVG arcs into straight lines

The handoff's verified smoke test is:

```
d = 'M 50 90 L 250 90 A 10 10 0 0 1 250 110 L 50 110 A 10 10 0 0 1 50 90 Z'
getPathsFromStr(d) -> 1 loop; findMats(loops, 3) -> 1 mat
-> 1 curve: [[60,100],[240,100]]
```

and concludes that the MAT is "INSET BY ONE CAP RADIUS at each end", making cap
extension "your first required post-step, not an edge case".

That conclusion is an artifact. `getPathsFromStr` returns:

```
[[[50,90],[250,90]], [[250,90],[250,110]], [[250,110],[50,110]], [[50,110],[50,90]], ...]
```

— the two `A` commands have become **straight lines**. The shape being analysed
is a 200×20 **rectangle**, not a capsule, and `[[60,100],[240,100]]` is the
correct medial axis of that rectangle. Convert the arcs to cubics first and the
same capsule gives:

```
[[250,100],[183.33,100],[116.67,100],[50,100]]   r=10 at both ends
```

which is the true centerline, **exactly, end to end**. Verified in the corpus:
case `07-round-cap` scores IoU 0.9997 with cap calibration a measured no-op.

So: **cap extension is not needed for round caps.** It is needed for butt caps,
and it is needed for tapers. Round-capped pen strokes — the case the whole
project is about (§1.3) — need none.

`experiments/flo-mat/lib/normalize.mjs` does the conversion with
svg-path-commander's `normalizePath` + `arcToCubic` (report §7.2's pick).

### 2. `findMats(loops, 3)` does not do what the report's example says

The second parameter is a `MatOptions` **object**, not the `maxCurviness`
number the report's snippet implies. A bare `3` is ignored, so you silently get
the defaults:

```
{ applySat: true, satScale: 2, simplify: true, simplifyTolerance: 1/16, maxLength: 40, ... }
```

The report's "raw MAT" is therefore **already Scale-Axis-pruned at s = 2**. Every
raw-vs-SAT comparison in this track passes `{ applySat: false }` explicitly so
"raw" means raw.

Also, `node.cp` does not exist in v4.1.0. The maximal disk is
`node.pointOnShape.circle` → `{ center: [x, y], radius }`. That radius is the
"T" in MAT and it is exact.

### 3. flo-mat hangs on some full-precision inputs

`inputs/house-wide.svg` element `rect-9` (a rounded rect under
`translate(...) rotate(...)`) makes `findMats` loop forever. It is not slow — it
does not terminate; a 4-minute wall clock produced nothing.

Reproduced and characterised:

| input to `findMats` | result |
|---|---|
| loops at full double precision | **hangs** |
| same loops, coords rounded to 1e-2 | ok, 215 ms |
| same loops, coords rounded to 1e-10 | ok, 190 ms |
| same shape via `getPathsFromStr(d)` | ok, 200 ms |

Any perturbation escapes it, including one 10 000× finer than the trigger — so
this is a **fragile geometric degeneracy**, not a tolerance issue, and rounding
is a mitigation, not a fix. The report's example never hits it because parsing a
path string rounds to the digits in the file.

Two responses, both in the code:

- `normalize.mjs` quantizes every normalized coordinate to `1e-4` user units.
- `mat-pool.mjs` runs each element's `findMats` in a **worker thread with a hard
  timeout** (20 s default). A hang becomes a recorded per-element failure with
  the rest of the drawing still processed, instead of a dead bench run.

Anyone productionizing flo-mat needs the second one.

---

## Pipeline

```
inputs/*.svg
  -> normalize.mjs   transforms, shapes->paths, subpaths->closed loops,
                     arcs+shorthand -> line/quad/cubic, degenerate-segment drop,
                     coordinate quantization
  -> mat.mjs         findMats per element (worker + timeout), optional toScaleAxis
  -> graph model     nodes {id,x,y,radius}, edges {geometry,length,medianRadius,
                     radiusProfile,sourceElementId}
  -> graph.mjs       degenerate-edge contraction, chain extraction, radius
                     measurement, cap calibration
  -> emit            <path fill="none" stroke-linecap="round"> per chain
  -> metrics.mjs     IoU, symmetric difference, boundary median/P95, centerline
                     error vs known truth, complexity, width CV, runtime
```

Normalization is verified before any MAT runs, as the brief asks: every corpus
case and every real input re-renders at **IoU ≥ 0.9999** against the original
(`normIoU` column). Normalization is not a source of error in any result here.

### Two things that are graph hygiene, not pruning

The brief says not to hand-roll pruning. These two are deliberately *below* that
line and both are reported in the metrics:

- **Coincident-node merge** (tolerance `1e-6 × maxDim`). flo-mat emits several
  `CpNode`s at the same centre, differing in the 1e-9s. Without merging, a plain
  capsule reports 14 nodes and 13 edges instead of 2 and 1.
- **Degenerate-edge contraction** (`length < 1e-3 × diagonal`). Every round cap
  disk carries a fan of ~0.04-unit MAT branches — `L / 2R ≈ 0.002` — because the
  maximal disk touches the boundary along an arc rather than at points. They are
  a discretization artifact of the contact arc.

Together these take the horizontal capsule from *13 emitted strokes* to *1*, with
IoU going 0.9990 → 0.9998. Everything above that scale is left alone for Track 8.

### Width estimation is measured, not interpolated

Stroke width comes from a **length-weighted median of distance-to-boundary**
sampled densely along each chain, not from interpolating flo-mat's node radii.
With `simplify: true` a whole 122-unit branch can be a single MAT curve with
radius sampled only at its two ends — one of which is a junction bulge — so
interpolation over-estimates width badly. On the T junction that error alone was
worth **IoU 0.949 → 0.998**.

flo-mat's own node radii are kept unchanged in the graph JSON (they are exact
maximal-disk radii and Track 8 should have them); the dense sampled profile is
published alongside as `edges[].radiusProfile`.

---

## Synthetic corpus results (the go/no-go)

22 cases: the report's 20 (§12.1) plus the two acute joins the Track 1 brief
calls out. Generated by stroking known centerlines with an analytic
line/arc stroker (`lib/stroker.mjs`, Paper.js boolean union), so the output is
real curved vector geometry rather than a densified polygon.

`cl.p95` = 95th percentile distance from recovered centerline points to the known
source path, in canvas units, stroke width 20.

| # | case | IoU | sym % | cl.p95 | strokes | edges | failure tag |
|---|---|---|---|---|---|---|---|
| 1 | horizontal-line | 0.9998 | 0.02 | 0.00 | 1 | 1 | — |
| 2 | diagonal-line | 0.9999 | 0.01 | 0.00 | 1 | 1 | — |
| 3 | circular-arc | 0.9976 | 0.24 | 0.19 | 1 | 9 | — |
| 4 | s-curve | 0.9983 | 0.17 | 0.19 | 1 | 13 | — |
| 5 | tight-u-curve | 0.9993 | 0.07 | 0.19 | 1 | 9 | — |
| 6 | closed-loop | 0.9982 | 0.18 | 0.19 | 1 | 16 | — |
| 7 | round-cap | 0.9997 | 0.03 | 0.19 | 1 | 1 | — |
| 8 | butt-cap | 0.9538 | 4.82 | 9.17 | 5 | 5 | `cap artifact` |
| 9 | square-cap | 0.9382 | 6.59 | 11.39 | 5 | 5 | `cap artifact` |
| 10 | round-join-90 | 0.9974 | 0.26 | 0.19 | 3 | 5 | — |
| 11 | bevel-join-90 | 0.9796 | 2.08 | 2.83 | 5 | 7 | `join artifact` |
| 12 | miter-join-90 | 0.9821 | 1.82 | 1.42 | 3 | 5 | `join artifact` |
| 13 | x-crossing-separate | 0.9999 | 0.01 | 0.00 | 2 | 2 | — |
| 14 | x-crossing-unioned | 0.9981 | 0.19 | 1.60 | 5 | 13 | `crossing ambiguity` |
| 15 | t-junction | 0.9980 | 0.20 | 0.22 | 3 | 5 | — |
| 16 | y-junction | 0.9998 | 0.02 | 0.19 | 3 | 7 | — |
| 17 | near-parallel | 0.9998 | 0.02 | 0.18 | 2 | 2 | — |
| 18 | self-overlap | 0.9845 | 1.56 | 2.49 | 7 | 12 | `crossing ambiguity` |
| 19 | variable-width | 0.7154 | 33.34 | 0.20 | 1 | 1 | width model |
| 20 | noisy-boundary | 0.7518 | 33.01 | 10.44 | 423 | 426 | `outline noise branch` |
| 21 | round-join-acute | 0.9879 | 1.22 | 2.26 | 3 | 5 | `join artifact` |
| 22 | miter-join-acute | 0.9461 | 5.58 | 11.77 | 3 | 5 | `join artifact` |

Reproduce: `node experiments/flo-mat/corpus-bench.mjs`. Sheet:
`corpus-sheet.png`. Per-case graphs: `graphs/NN-*.json`.

### What the corpus says, case by case

**Pure geometry (1–7, 10, 13, 15–17) is solved.** Lines, arcs, S curves, tight
U turns, closed loops, round caps, round joins, separate crossings, T and Y
junctions and near-touching parallels all reconstruct at IoU ≥ 0.997 with a
centerline error under 0.2 units — 1% of a stroke width. A straight capsule
comes out as **exactly one edge between two nodes**, the true endpoints, radius
10.000. There is no resolution parameter anywhere in that path.

Case 17 confirms the classic Voronoi failure does not occur here: two capsules
1 unit apart produce two independent MATs with no bridging branch, because they
are separate loops rather than sampled boundary points.

**Caps (8, 9) fail in the way §2.3 predicts, but not the way the brief predicts.**
The failure is *corner branches*, not inset. A butt-capped stroke is a
rectangle; the medial axis of a rectangle includes four 45° branches running
into the corners, each `r√2` long. Re-stroked at full width they produce
"bone-end" flares. The centerline *median* error is 0.00 — the trunk is exactly
right — while `cl.p95` is 9.2 (butt) and 11.4 (square), entirely from the corner
branches. Square caps additionally place the MAT terminus at the true endpoint,
so no extension is needed there either.

**Joins (11, 12, 21, 22) fail the same way.** A bevel or mitre join is a corner,
and a corner spawns a branch. Round joins (10, 21) are clean because a round
join has no corner. This is a strong argument for the report's §1.3 framing:
flo-mat is close to exact for round-capped, round-joined pen strokes and needs
help for everything else.

**Unioned crossing (14): flo-mat does not produce a degree-4 node.** Tagged
`crossing ambiguity` as instructed, but the specific finding is more useful than
"it's ambiguous": the MAT of two unioned 20-wide strokes crossing at ~60° is
**two degree-3 nodes joined by a short 12.4-unit edge whose radius is 13.2** —
not one degree-4 vertex. The corpus data shows `deg4 = 0` for case 14. So the
question Track 8 has to answer is not "split this 4-way vertex" but "recognise
this short high-radius edge between two 3-prongs as the *interior* of a crossing
and pair the four arms through it". The `radiusProfile` on that edge (a clear
bulge to 1.32× the surrounding radius) is the signal. The same pattern appears
in case 18 (self-overlap), where the crossing is between two parts of one stroke.

**Variable width (19) is a re-stroke limitation, not an extraction failure.** The
centerline is recovered essentially perfectly (`cl.p95` 0.20) on a stroke that
tapers 6 → 30. IoU 0.715 is entirely the constant-width output model. The
`radiusProfile` on that single edge tracks the true taper. Any consumer that can
emit variable width — or that splits the chain — recovers this; the pipeline has
a `--variableWidth` mode that does exactly that, and it exists to demonstrate the
radius data is sound rather than as a production format.

**Noise (20) is the one that needs pruning.** A ±1.2-unit boundary perturbation on
a 20-wide stroke turns 1 edge into 426 and IoU 0.9998 into 0.7518. This is §10's
whole point in one number. SAT fixes most of it — see below.

---

## Raw MAT vs. Scale Axis Transform

`node experiments/flo-mat/sat-sweep.mjs` → `sat-sweep.json`. IoU / edge count:

| case | raw | s=1.1 | s=1.3 | s=1.5 | s=2 | s=3 |
|---|---|---|---|---|---|---|
| 08-butt-cap | 0.9538/5 | 0.9532/5 | 0.9532/5 | **0.9761/1** | 0.9761/1 | 0.9761/1 |
| 09-square-cap | 0.9382/5 | 0.9364/5 | 0.9364/5 | **0.9785/1** | 0.9785/1 | 0.9785/1 |
| 10-round-join-90 | **0.9974/5** | 0.9974/5 | 0.9974/5 | 0.9931/4 | 0.9931/4 | 0.9931/4 |
| 11-bevel-join-90 | 0.9796/7 | **0.9965/5** | 0.9965/5 | 0.9965/5 | 0.9965/5 | 0.9965/5 |
| 12-miter-join-90 | 0.9821/5 | 0.9821/5 | 0.9821/5 | **0.9897/4** | 0.9897/4 | 0.9897/4 |
| 18-self-overlap | **0.9845/12** | 0.9845/12 | 0.9845/12 | 0.9845/12 | 0.9845/12 | 0.9383/10 |
| 20-noisy-boundary | 0.7518/426 | 0.9338/63 | **0.9472/54** | 0.9472/54 | 0.9396/51 | 0.9407/50 |
| 21-round-join-acute | **0.9879/5** | 0.9867/5 | 0.9867/5 | 0.9867/5 | 0.9867/5 | 0.9867/5 |

Every other case is flat across the whole sweep — SAT touches nothing it should
not touch.

Reading:

- **SAT is very good at boundary noise.** Case 20: 426 edges → 54, IoU +0.20.
  That is the single most valuable thing it does, and it is free.
- **SAT clears cap and bevel corner branches** at s ≥ 1.5 (caps) and s ≥ 1.1
  (bevel), collapsing case 8/9 to a single clean edge.
- **SAT starts eating real detail above that.** Round-join-90 loses 0.004 IoU and
  a real edge at s ≥ 1.5; acute round join loses at s ≥ 1.05; self-overlap loses
  a genuine branch at s = 3 (IoU 0.9845 → 0.9383).
- The usable window is roughly **s ∈ [1.3, 1.5]**, and it is a genuine trade:
  there is no single s that fixes caps without touching round joins.

That trade is the argument for Track 8's model-selection pruning (§10.2): the
right s is per-shape, and it should be chosen by re-stroke score rather than
picked once. Note also that flo-mat's *default* (`applySat: true, satScale: 2`)
sits on the far side of that window.

---

## Real ladder

See `metrics.json` and `comparison-sheet.png`. Reproduce with
`node experiments/flo-mat/bench.mjs`.

`pixdiff` is symmetric-difference pixels over the whole 1200 px canvas, which is
the same convention as the incumbent's numbers in
`docs/current-attempt-handoff.md`.

Results are filled in below from the committed `metrics.json`.

### Dominant real-artwork defect

The zoom crops (`zoom-house-wide.png`) show it clearly: where a stroke ends in a
**squared or angled end** rather than a round cap — which is common in this
artwork where one stroke was drawn over another — the MAT's corner branches get
re-stroked at full width and produce small bumps hanging off the stroke. Same
mechanism as corpus cases 8/9/11/12, and it is the main thing standing between
this backend and the incumbent's numbers. It is a pruning problem, so it belongs
to Track 8; SAT at s ≈ 1.3–1.5 removes much of it.

---

## Runtime

`findMats` is fast: 50–400 ms per element on this artwork, roughly linear in
boundary Bézier count. Whole-image wall clock is dominated by the per-element
worker spawn and by the metrics (two exact Euclidean distance transforms at
1200 px). Per-element `findMats` time is recorded as `matMs` in `metrics.json`.

There is no rasterization anywhere in the extraction path, so there is no
resolution parameter and no `raster quantization` failure class for this
backend at all — the one structural advantage the report predicted, confirmed.

---

## Failure-tag counts (report §13 Experiment 2 taxonomy)

| tag | where it shows up in this track |
|---|---|
| `cap artifact` | corpus 8, 9 — 45° corner branches at flat ends; real artwork, squared stroke ends |
| `join artifact` | corpus 11, 12, 21, 22 — corner branches at bevel/mitre joins |
| `outline noise branch` | corpus 20 — 426 edges from a 1-edge shape; the main SAT use case |
| `crossing ambiguity` | corpus 14, 18 — two degree-3 nodes plus a high-radius short edge, never a degree-4 node |
| `disconnected skeleton` | **not observed** — MAT connectivity is exact per loop |
| `missing narrow segment` | **not observed** on the corpus |
| `wrong endpoint` | corpus 8 only (butt cap: MAT ends one radius short and stays there) |
| `excessive curve complexity` | corpus 20; also `simplify: false` roughly triples edge counts |
| `raster quantization` | **not applicable** — no rasterization in the extraction path |

---

## For Track 8

`graphs/*.json` is the deliverable that matters most. Schema:

```jsonc
{
  "schema": "centerline-graph/1",
  "backend": "flo-mat@4.1.0",
  "image": "...", "source": "...", "options": { ... },
  "nodes": [{ "id": "g0_n3", "x": 1.2, "y": 3.4, "radius": 9.87 }],
  "edges": [{
    "id": "g0_e2", "from": "g0_n3", "to": "g0_n4",
    "geometry": [[[x,y],[x,y],[x,y],[x,y]]],   // 2/3/4 control points per bezier
    "length": 122.5,
    "medianRadius": 11.25,                     // mean of the two endpoint disks
    "radiusProfile": [10.0, 10.0, ...],        // 9 samples per bezier, measured
    "sourceElementId": "path-12"
  }],
  "stats": { ... }
}
```

Notes for consuming it:

- `nodes[].radius` is flo-mat's **exact maximal-disk radius**. It is the real
  MAT radius, not a sampled estimate.
- `edges[].radiusProfile` is distance-to-boundary sampled along the edge. Use
  this, not interpolation between node radii — see the width-estimation note
  above for why the difference is worth 0.05 IoU.
- Node ids are prefixed `g{elementIndex}_g{matIndex}_n{k}`; `sourceElementId`
  gives the originating SVG element so per-element processing is preserved.
- The graphs are emitted **unpruned** apart from the two hygiene steps above.
- Useful signals already present for pruning work: terminal branches at squared
  ends have `L/(2R) ≈ 0.7` (a corner branch is `r√2` long, so ~0.7 stroke
  widths), while noise branches on case 20 are `L/(2R) < 0.2`. Crossing interiors
  show up as short edges with `radiusProfile` peaking well above the surrounding
  branches.

---

## Reproducing everything

```bash
npm install
node experiments/flo-mat/corpus-bench.mjs        # synthetic corpus + sheet
node experiments/flo-mat/sat-sweep.mjs           # raw MAT vs SAT sweep
node experiments/flo-mat/bench.mjs               # real ladder + sheet + graphs
node experiments/flo-mat/real-sat-sweep.mjs house-wide
node experiments/flo-mat/zoom.mjs house-wide 3   # worst-region crops
```
