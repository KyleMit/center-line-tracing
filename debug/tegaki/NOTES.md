# Track 5 — Tegaki generator, adapted

Slug `tegaki` · branch `claude/centerline-tegaki-40g6tf` · report §6.9, §18.5

---

## Part 1 — The algorithm map (written for Tracks 3, 6 and 8)

Source: `github.com/gkurt/tegaki` @ `main` (cloned 2026-08-07, shallow).
License **MIT** — verified in the repo's `LICENSE` (MIT License, Copyright (c) 2026
Gokhan Kurt). The report's claim checks out. Anything vendored below carries that
attribution; see `experiments/tegaki/VENDOR.md`.

The generator lives at `packages/generator/` — ~5k lines of TypeScript, run under
Bun, **not published to npm** (the published `tegaki` package is the renderer).
It is a workspace package importing types from the sibling `tegaki` renderer
package, so it cannot be lifted out standalone without stubbing those types.
Everything below is a read of the actual source, file by file.

### Pipeline at a glance

`packages/generator/src/commands/generate.ts:272-288` is the whole pipeline in
seven calls:

```
flattenPath(glyph.commands, bezierTolerance)      // 1. flatten  → Point[][]
computePathBBox(subPaths)
rasterize(subPaths, bbox, resolution)             // 2. raster   → Uint8Array + transform
computeInverseDistanceTransform(bitmap, …)        // 3. DT       → Float32Array (radius field)
skeletonize({subPaths, raster, inverseDT, …})     // 4. skeleton + trace + prune → polylines
orderStrokes(polylines, inverseDT, …)             // 5. order/orient/width → Stroke[]
toFontUnits(strokes, raster.transform, …)         // 6. back to font units + timing
```

Note the ordering: **the distance transform is computed before skeletonization and
is passed into it.** The radius field is not an afterthought — it drives junction
cleanup, the distance-ordered thinner, the width lookup, and (on the Voronoi path)
the pruning threshold.

---

### Stage 1 — Flattening (`processing/bezier.ts`, 116 lines)

Adaptive de Casteljau subdivision, **flatness-tested by midpoint deviation**:

- quadratic: compare the true curve midpoint `0.25·P0 + 0.5·P1 + 0.25·P2` against
  the chord midpoint; recurse if `distSq > tolerance²`.
- cubic: same with `0.125·P0 + 0.375·P1 + 0.375·P2 + 0.125·P3`.
- `BEZIER_TOLERANCE = 0.5` **font units** (typically 1/1000 em, so this is a very
  tight tolerance — sub-pixel at any realistic raster resolution).
- Handles only `M / L / Q / C / Z` (opentype.js emits nothing else). **No arc
  support** — this is the first thing that breaks on real SVG, where `A` is common.
- `Z` closes by pushing a copy of the subpath start, so every closed contour is an
  explicit ring with `first === last`. Downstream code relies on this (the
  rasterizer iterates `i < path.length - 1` and would otherwise miss the closing
  edge).

**Takeaway for other tracks:** midpoint-deviation flattening at a fixed tolerance
is cheap and adequate. The tolerance is in *source* units, not pixels — so if you
scale the raster, the effective flattening error scales with it. Ours is set in
user units and should be tied to the raster scale, not left constant.

### Stage 2 — Rasterization (`processing/rasterize.ts`, 104 lines)

A **hand-written scanline fill with the nonzero winding rule**. No canvas, no
external rasterizer, no anti-aliasing — the output is a hard binary
`Uint8Array`.

- `DEFAULT_RESOLUTION = 400`. The glyph bbox is padded by `BITMAP_PADDING = 0.05`
  (5% each side), then **aspect-fit** into `resolution × resolution`:
  `scale = min(res/totalW, res/totalH)`; the bitmap is `ceil(totalW·scale) ×
  ceil(totalH·scale)`, so it is *not* square in general.
- The returned `transform {scaleX, scaleY, offsetX, offsetY}` is the only thing
  mapping bitmap space back to source space; `scaleX === scaleY` always.
- Scanline at pixel centre (`y + 0.5`), edges half-open in y (`scanY >= yMin &&
  scanY < yMax`) so shared vertices are counted once. Horizontal edges skipped.
  Winding accumulated left-to-right at pixel centres.

**Takeaway:** 400px across the *whole glyph* is coarse — a thin stroke in a dense
glyph can be 2-3 px wide. This is a deliberate speed choice for generating
thousands of glyphs, and it is the single biggest quality lever if you adapt the
pipeline. Note also that a binary, non-antialiased raster is *good* for
skeletonization: no threshold ambiguity, fully deterministic (report §15).

### Stage 3 — Distance transform (`processing/width.ts`, 166 lines)

Two implementations, selected by `DISTANCE_TRANSFORM_METHOD`:

- **`chamfer`** (the default!) — 2-pass forward/backward chamfer with cost 1
  orthogonal / `√2` diagonal. Approximate (up to ~8% error on long diagonals).
- **`euclidean`** — exact, via Felzenszwalb & Huttenlocher's lower-envelope-of-
  parabolas 1-D EDT applied along columns then rows. Returns true distances.

`computeInverseDistanceTransform` inverts the bitmap first, so the field is
"distance from an inside pixel to the nearest outside pixel" = **local inscribed
radius**. `getStrokeWidth(x, y)` = `2 × inverseDT[round(y)·w + round(x)]`.

The comment on the constant is the interesting part, and it is a real finding:

> `'euclidean'` … mathematically accurate but **may produce noisier junction
> cleanup due to sharper peaks**. `'chamfer'` … slightly less accurate, but
> produces **smoother gradients that can lead to cleaner results**.

They ship the *approximate* transform by default because junction-cluster
collapse picks an argmax over the field, and an exact EDT gives flat/tied plateaus
and sharp ridges that make that argmax jumpy. **This is a directly transferable
lesson for Track 3**, which gets an exact Euclidean field from
`medial_axis(return_distance=True)` and may want to smooth it before using it for
any argmax-style decision.

### Stage 4 — Skeletonization (`processing/skeletonize/`)

`skeletonize/index.ts` dispatches on `skeletonMethod`. **Six methods**, two
families:

| method | file | what it is |
|---|---|---|
| `zhang-suen` | `zhang-suen.ts` | classic 1984 two-sub-iteration thinning. **The default.** |
| `guo-hall` | `guo-hall.ts` | 1989 variant; `N = min(N1, N2)` paired-neighbour counting. Comment claims thinner diagonals and different junction topology. |
| `lee` | `lee.ts` | Lee/Kashyap/Chu 1994 via a precomputed **256-entry removal LUT** (removable iff `2 ≤ B(P) ≤ 6` and `A(P) = 1`), 8 directional sub-iterations per pass. Less directional bias. |
| `thin` | `morphological.ts` | same LUT as Lee but with `THIN_MAX_ITERATIONS = 25` — **deliberately partial thinning**, producing a thicker-than-1px skeleton. |
| `medial-axis` | `medial-axis.ts` | **distance-ordered homotopic thinning**: sort every foreground pixel by DT ascending, delete in that order if it is a simple point (crossing number `A(P) == 1`) and not degree ≤ 1. High-DT pixels die last, so the survivors lie on the true medial axis. |
| `voronoi` | `voronoi-medial-axis.ts` | bypasses the raster entirely; see below. |

The `medial-axis` one is worth stealing on its own: it is **~30 lines** and turns
any distance field into a medial-axis-accurate skeleton without needing
scikit-image. It is exactly the "Euclidean medial axis vs morphological thinning"
distinction Tracks 3 and 6 are set up to compare, implemented in one file with a
shared interface, so their A/B is available here as a config flag.

#### Post-thinning cleanup (`skeletonize/cleanup.ts`, 234 lines)

Two passes, both DT-driven, applied to every thinning method **except**
`medial-axis` (which skips the cluster cleanup):

1. **`cleanJunctionClusters`** — up to `JUNCTION_CLEANUP_MAX_ITERATIONS = 5`
   passes of: flood-fill connected groups of degree ≥ 3 pixels; if a group has
   more than one pixel, delete the whole group, **re-add only its highest-DT pixel**
   (the most medial one), and **reconnect every severed arm to it with a Bresenham
   line**; then re-thin. Repeats because reconnection lines can create new clusters.

   This is the fix for thinning's classic "junction smear" — Zhang-Suen turns a
   crossing into a 2×2 or larger blob of degree-3+ pixels, which a tracer then
   reads as several spurious tiny branches. **Track 6 will hit exactly this**, and
   this is a working, cheap fix for it.

2. **`restoreErasedComponents`** — label the *bitmap's* connected components; for
   any component with zero surviving skeleton pixels, set its single highest-DT
   pixel as a skeleton pixel. This is how i-dots and other small blobs survive
   thinning. Tagged in our taxonomy this prevents `missing narrow segment` /
   `disconnected skeleton` on small marks.

#### Tracing (`processing/trace.ts`, 655 lines) — the most sophisticated stage

`traceAndSimplify` walks the 1-px skeleton into ordered polylines:

**Seeding and ordering.** Collect all degree-1 pixels as endpoints. Set a virtual
`lastEnd` at the **middle of the left edge** of the skeleton bbox (right edge if
`rtl`). Then loop: pick the nearest unvisited endpoint to `lastEnd`, trace a chain,
reverse it if its far end is nearer to `lastEnd` than its start, push it, set
`lastEnd` to its end. **This is greedy nearest-neighbour stroke sequencing, and it
is the whole of the stroke *order* logic** — it is not learned, not semantic, just
"start at the writing-entry side and always draw the stroke whose end you are
closest to". A second pass sweeps remaining pixels (loops with no endpoints,
isolated pixels).

**Chain walking (`traceChain`).** At degree-2 pixels it just follows. At branch
points it does two clever things:

- **`estimateDirection` with curvature extrapolation.** Takes the last
  `TRACE_LOOKBACK = 12` pixels, splits into an older and a recent half, and
  returns `recent + TRACE_CURVATURE_BIAS·(recent − older)` with bias `0.5`. So the
  predicted direction *anticipates continued turning* rather than assuming the
  stroke goes straight. On a curved stroke passing through a junction, a
  straight-line tangent picks the wrong branch; this does not.
- **`pickStraightest` with `peekAhead`.** Rather than comparing the 8 possible
  1-pixel steps, it follows each candidate branch ahead up to 12 px and compares
  the *branch's* direction. This upgrades an 8-way angular resolution to a
  continuous one — the single highest-value trick in the file.

**Crossing decision (`shouldStopAtJunction`).** This is Tegaki's answer to report
§2.2 / our `crossing ambiguity` tag, and it is a genuine heuristic, not a punt:

```
if any pair of outgoing branches is near-opposite (cos < JUNCTION_CROSSING_COS = -0.7,
    i.e. ≥ ~135° apart)                                  → a crossing stroke exists here
   and our incoming direction aligns with no branch
      (best cos < JUNCTION_ALIGNMENT_COS = 0.5, ~60°)    → STOP; this junction is not ours
otherwise                                                 → continue through
```

Read plainly: *if two other branches form a straight line through this point, and
I am arriving off-axis, then I am the stem of a T and the other stroke owns the
junction — end my stroke here.* If I am arriving roughly along one of the branches,
I am the through-stroke of an X and I keep going. That is the two-crossing-strokes
vs one-four-way-junction decision, decided locally, and it is exactly the decision
Track 1's flo-mat handoff says "flo-mat will not decide for you".

**Merging (`mergePolylines`).** Any two polylines whose endpoints are within
`max(w,h) · MERGE_THRESHOLD_RATIO = 0.08` are concatenated (all 4 orientations
tried), repeatedly, until stable. Note this threshold is **8% of the whole bitmap**
— very aggressive, and only sane because a glyph is small and its strokes are
long relative to it. On our drawings this would happily weld unrelated strokes
together; see the adaptation notes below.

**Junction-kink smoothing (`smoothJunctionKinks`).** Removes interior points using
three independent tests, any one of which drops the point:
1. *classic angle test* — angle at the point ≥ `SMOOTH_KINK_MIN_ANGLE = 155°`
   (i.e. nearly straight) → the point is redundant;
2. *curvature-prediction test* — if skipping the point aligns better with the
   `estimateDirection` prediction by more than `SMOOTH_KINK_THRESHOLD = 0.15` in
   cosine, drop it;
3. *smoothness test* — if skipping the point makes the angle at the **previous**
   point smoother by > 0.15 cosine, the point was a junction detour → drop it.

Test 3 is the one that removes the little lateral jog thinning leaves where a
branch meets a stroke. Tagged in our taxonomy: this is a targeted `join artifact`
remover.

#### **PRUNING** (`trace.ts:628-651`) — the priority-(a) deliverable

This is the whole of the thinning path's pruning, and it is **deliberately naive**:

```js
effectiveSpurMin = min( round(max(w,h) · SPUR_LENGTH_RATIO), 10 )   // ratio = 0.08, hard cap 10 px
keep polyline P if:
    pathLength(P) >= effectiveSpurMin
  OR P is "isolated" — no endpoint of P is within mergeThreshold of any endpoint
     of any other polyline
```

Three things to say about it, in order of importance to Track 8:

1. **It is absolute-length pruning, not width-aware.** `L ≥ 0.08·bitmapSize`,
   capped at 10 px. There is no `R` term anywhere. This is precisely the failure
   mode report §10 predicts, and it is why the constant needs a cap: without the
   cap, a small glyph gets erased entirely. **A hard cap on a length threshold is
   the tell-tale sign of a threshold that should have been scale-free.**
2. **The isolation clause is the interesting half.** A short polyline is only a
   spur if it is *attached to something*. Isolated short components are real marks
   (i-dots, punctuation) and are kept unconditionally. This is a cheap and
   effective structural distinction that pure length-thresholding misses, and it
   generalizes directly: **"short AND attached" is a much better spur predicate
   than "short".** Track 8 should take this.
3. **Pruning happens on polylines, after tracing and merging — not on the graph.**
   So a spur that got merged into a longer chain is never considered. The junction
   cleanup upstream is doing most of the real spur-suppression work; by the time
   this filter runs, most artifacts are already gone.

**The Voronoi path prunes completely differently, and correctly**
(`voronoi-medial-axis.ts:400-468`):

```js
// walk from each degree-1 node to the first degree-3+ node, accumulating length
localWidth = 2 · nearestBoundaryDist(junctionPoint)
if (length < localWidth · 1.5) → delete the whole spur chain
```

That **is** `L / (2·R_parent) < 1.5` — report §10.1's normalized feature, with
`R` sampled at the *junction* (i.e. `R_parent`, not `R_med`), and a threshold of
1.5 stroke widths. So Tegaki contains both a naive and a width-aware pruner, and
the width-aware one is on the geometrically better backend. **This is the single
most useful number in the repository for Track 8: a working implementation's
choice of `L/(2R) < 1.5` as the spur threshold.**

It is preceded by `contractShortEdges(adj, 2.0)` — merge any graph edge shorter
than 2 px, keeping the higher-degree endpoint. That is a separate, purely
topological simplification that collapses the Voronoi hairball at junctions before
pruning ever runs. Track 8's graph library wants this as a primitive.

#### The Voronoi skeletonizer (`voronoi-medial-axis.ts`, 483 lines)

Independent of the raster: sample the flattened outline every
`VORONOI_SAMPLING_INTERVAL = 2` bitmap-px, build a Delaunay/Voronoi with
`d3-delaunay`, keep only Voronoi edges whose **midpoint *and both endpoints*** are
inside the shape (nonzero-winding point-in-polygon against the flattened
contours), snap vertices to a 0.1 px grid to build an adjacency graph, contract
short edges, prune width-aware spurs, and trace chains between non-degree-2 nodes.
Per-point width comes from brute-force nearest-boundary-sample distance.

This is Track 4's approach (sampled-point Voronoi, not segment Voronoi) with the
same known weakness — it is an approximation from boundary *samples*, so
sampling interval trades accuracy against a hairball. Worth noting it still
rasterizes for the bitmap the debug visualiser needs, but the geometry never
touches pixels.

#### `RDP_TOLERANCE = 1.5` px

Final simplification is plain Ramer-Douglas-Peucker at 1.5 bitmap px. No Bézier
fitting anywhere in the generator — output is polylines, and the *renderer* draws
them with Catmull-Rom (`packages/renderer/src/lib/catmullRom.ts`). So Tegaki
never solves the curve-fitting problem Track 3 is solving; it defers it to
render time.

### Stage 5 — Width estimation (`processing/stroke-order.ts` + `width.ts`) — priority (b)

Deceptively simple and worth stating precisely:

```
width(point) = 2 · inverseDT[ round(y)·bitmapWidth + round(x) ]
```

Per **point**, not per stroke. Every emitted point carries its own width, and the
renderer varies stroke weight along the path. Three refinements matter:

- On the Voronoi path, width is instead `2 × ` nearest-boundary-sample distance —
  sub-pixel, no rounding to a pixel grid.
- **Single-point strokes (dots) get their width overwritten** with the average
  per-point width of all multi-point strokes. Rationale in the source: a dot's DT
  value is the blob's inscribed radius, which is *not* the pen width — a 12px-wide
  dot drawn with a 4px pen would otherwise render as a 12px-wide stroke. This is a
  real, non-obvious correction and it generalizes: **the medial radius at an
  isolated blob measures the blob, not the pen.**
- Nothing smooths the width profile along a stroke, and nothing rejects outliers.
  At junctions the inscribed radius spikes (the inscribed circle at an X crossing
  is much bigger than the stroke) — Tegaki simply lives with the resulting bulge.
  **That spike is the width-estimation failure mode to watch for**, and a median
  or a low-percentile statistic along the stroke is the obvious fix. We use the
  median in our port and record the full profile.

### Stage 5b — Stroke ordering and orientation (`stroke-order.ts`, 244 lines) — priority (c)

Report §9.8 asks for exactly this. Tegaki's answer has four parts:

1. **Order** is inherited from tracing: greedy nearest-neighbour from a
   writing-entry side (middle-left for LTR, middle-right for RTL). No re-sorting.
   The `COMPONENT_SORT_Y_TOLERANCE` / `POLYLINE_SORT_Y_TOLERANCE` constants
   describing row-major sorting are **declared but no longer used** — a previous
   ordering scheme that was replaced by the trace-order approach. (Worth knowing
   if you read the constants file first and expect to find row sorting.)
2. **Orientation** (`orientPolyline`): for an open polyline, score each end as
   `y + x·ORIENT_X_WEIGHT` with `ORIENT_X_WEIGHT = 2`, and start from the lower
   score. With weight 2, x dominates y, so it is *left-to-right, top-to-bottom as
   tiebreak*; for RTL the x-weight flips sign. For a near-closed loop
   (`dist(start,end) < 5 px`) it instead **rotates** the ring to begin at the
   leftmost (rightmost for RTL) point — you cannot reverse a loop into a natural
   start, you have to re-index it.
3. **Dot deferral** (`classifyDots` + `reorderByPriority`): a stroke is a "dot"
   (priority −1) if its bbox diagonal is < `DOT_DIAG_RATIO = 0.15` of the glyph
   bbox diagonal **AND** its bbox gap to every other stroke's bbox is >
   `DOT_ISOLATION_RATIO = 0.04` of that diagonal. Dots are then stably re-sorted to
   draw after all body strokes. Same "small AND isolated" predicate as the pruner,
   used for a different decision — a nice piece of design.
4. **Timing** (`font-units.ts`): each point gets `t = cumulativeLength / totalLength`
   ∈ [0,1]; each stroke gets `duration = length / DRAWING_SPEED (3000 units/s)` and
   a `delay` accumulated with `STROKE_PAUSE = 0.15 s` between strokes.

**Honest assessment for Track 8:** the order heuristics are entirely spatial and
carry no stroke semantics — nothing here knows a roof is drawn before a wall. The
transferable parts are (2) the orientation scoring function, (3) the small-and-
isolated → draw-last rule, and (4) the arc-length `t` parameterization, which is
the right serialization format for order/direction metadata regardless of how the
order is chosen. The greedy nearest-neighbour sequencing is a reasonable default
and is better than DOM order for a drawing, because it minimizes pen travel.

### What Tegaki does *not* do

- No Bézier fitting (deferred to the renderer's Catmull-Rom).
- No cap extension. Font glyphs have no round caps to compensate for, so the
  medial-axis inset that Track 1's handoff calls out (§2.3) is simply not a
  problem it has. **Adapting it to pen artwork means adding cap handling** — this
  is the largest single gap between Tegaki's problem and ours.
- No reconstruction-based validation (report §11). Quality is eyeballed.
- No holes/even-odd handling beyond nonzero winding.
- No arcs in the flattener.

---

## Part 2 — What we ported, and why

See `experiments/tegaki/` (plain ES-module JavaScript, Node 22, no Bun, no TS).
We did **not** try to run the monorepo: the generator is a Bun workspace package
importing types from the sibling renderer, its entry point is a font-download CLI,
and the handoff explicitly timeboxes this. Porting the seven algorithm files was
faster than making the monorepo consume an SVG, and it is what produces reusable
knowledge. Vendored-from and attribution: `experiments/tegaki/VENDOR.md`.

Ported faithfully:

- `bezier.js` — adaptive de Casteljau, **plus arc (`A`) flattening** which Tegaki
  lacks and our inputs need, plus the relative-command and `H/V/S/T` forms.
- `raster.js` — the scanline nonzero fill, verbatim in behaviour. Kept binary and
  non-antialiased, which keeps us deterministic (§15).
- `dt.js` — both the chamfer and the exact Felzenszwalb–Huttenlocher EDT.
- `thin.js` — Zhang-Suen, Guo-Hall, Lee-LUT, partial morphological, and the
  distance-ordered medial-axis thinner. All five.
- `cleanup.js` — junction-cluster collapse with Bresenham re-attachment, and
  erased-component restoration.
- `trace.js` — chain walking with curvature-extrapolated look-ahead, the
  `shouldStopAtJunction` crossing rule, merging, three-test kink smoothing, RDP.
- `voronoi.js` — the sampled-boundary Voronoi medial axis, including the
  **width-aware** spur pruner and short-edge contraction.
- `order.js` — orientation scoring, loop rotation, dot classification and
  deferral, arc-length `t`.

Changed deliberately (all flagged in code with `ADAPTED:`):

- **Per-element processing.** Tegaki rasterizes one glyph; we rasterize each
  filled SVG element separately, like the incumbent. Merging same-colour elements
  is known to wreck `landscape-square.svg`.
- **Raster scale instead of fixed 400px.** `--scale` is px per user unit
  (default 2). Tegaki's aspect-fit-to-N behaviour is available as `--resolution N`
  for fidelity comparisons. A shared 400px budget across a whole drawing would put
  our strokes at ~1px.
- **`mergeThreshold` is width-relative, not bitmap-relative.** 8% of the bitmap is
  right for a glyph and catastrophic for a drawing; we use `k · R_global` (default
  `k = 1.5`). This is the clearest example of a Tegaki constant that does not
  survive the change of domain.
- **Cap extension added.** Terminal branches are extended along their tangent by
  the local radius, because our strokes have round caps and glyphs do not (§2.3).
- **Width per stroke = median of the per-point profile**, because SVG cannot vary
  width along one path. The full per-point profile is kept in the graph JSON.
- **Both pruners are implemented and switchable** (`--prune tegaki-length` vs
  `--prune tegaki-width`) so the naive and width-aware variants can be measured
  against each other on the same skeleton. That A/B is the point of this track.

---

## Part 3 — The stroke order/direction metadata field

We extend the common graph model (Common Setup §"Emit the common graph model")
with one optional block per edge and one document-level array. Everything else is
unchanged, so Track 8's loader can ignore it entirely.

```ts
interface CenterlineEdge {
  id: string; from: string; to: string;
  geometry: Point[];
  length: number; medianRadius?: number; sourceElementId?: string;

  /** Track 5 extension. Absent on backends that do not infer stroke semantics. */
  strokeOrder?: {
    /** 0-based draw sequence across the whole document. Dense, no gaps. */
    index: number;
    /** Which end of `geometry` the pen starts at, AFTER orientation is applied.
     *  Always "start" in our output — we reverse the geometry array itself
     *  rather than carry a flag, so `geometry[0]` is always the pen-down point
     *  and `geometry[n-1]` is always the pen-up point. Recorded explicitly so a
     *  consumer never has to guess whether the array was reordered. */
    direction: "start" | "end";
    /** True if the geometry array was reversed relative to the raw traced chain. */
    reversed: boolean;
    /** Arc-length parameter per geometry point, in [0,1], t[0]=0, t[n-1]=1.
     *  Same length as `geometry`. This is the animation/gesture parameterization. */
    t: number[];
    /** "body" | "dot". Dots are small-and-isolated marks deferred to draw last. */
    class: "body" | "dot";
    /** Per-point width (diameter) profile in user units, same length as geometry.
     *  Native output of the width stage; `medianRadius` is derived from it. */
    widthProfile: number[];
  };
}
```

Document level, alongside `nodes`/`edges`:

```ts
strokeOrderMeta: {
  method: "tegaki-greedy-nn";     // greedy nearest-neighbour from an entry side
  entrySide: "left" | "right";
  orientRule: "score = y + x * ORIENT_X_WEIGHT, lower score starts";
  orientXWeight: number;          // 2
  order: string[];                // edge ids in draw order — the canonical sequence
}
```

`order` is the authoritative sequence; `strokeOrder.index` duplicates it per-edge
for convenience. Both are emitted so a consumer can use either.

---

## Part 4 — Results

Reproduce everything below with:

```bash
node experiments/tegaki/synth.js                      # regenerate the 20-case corpus
node experiments/tegaki/bench.js synth  --tag baseline
node experiments/tegaki/bench.js real   --tag final
node experiments/tegaki/bench.js prune                # pruner A/B
node experiments/tegaki/bench.js prune-sweep --only dinosaur-wide,landscape-square
node experiments/tegaki/bench.js ab                   # skeletonizer A/B, synthetic
node experiments/tegaki/bench.js ab-real --only house-wide,dinosaur-wide
node experiments/tegaki/sheet.js comparison --tag final
```

All numbers land in `debug/tegaki/metrics.json`, keyed by run.

### 4.1 Headline — it works, and it is competitive on the first pass

Config: `zhang-suen` / `chamfer` DT / `tegaki-width` pruning / raster scale 2 px
per user unit / cap style `round`. Promoted SVGs are in `outputs/tegaki/`, graph
JSON in `debug/tegaki/graphs/`.

| image | IoU | symDiff% | miss% | extra% | bd med | bd P95 | strokes | pts | px-diff |
|---|---|---|---|---|---|---|---|---|---|
| house-wide | 0.9537 | 4.8 | 2.2 | 2.5 | 0 | 0.5 | 26 | 374 | **0.09%** |
| butterfly-wide | 0.9403 | 6.2 | 2.7 | 3.5 | 0 | 0.5 | 16 | 591 | **0.15%** |
| boat-tall | 0.9506 | 5.1 | 1.5 | 3.6 | 0 | 0.5 | 26 | 515 | **0.04%** |
| island-tall | 0.9493 | 5.2 | 1.9 | 3.4 | 0 | 0.5 | 32 | 503 | **0.07%** |
| balloon-tall | 0.9420 | 6.0 | 2.2 | 3.8 | 0 | 0.5 | 46 | 622 | **0.06%** |
| home-wide | 0.9405 | 6.2 | 2.5 | 3.7 | 0 | 0.5 | 32 | 384 | **0.05%** |
| house-tall | 0.9424 | 5.9 | 2.6 | 3.3 | 0 | 0.5 | 37 | 614 | **0.11%** |
| dinosaur-wide | 0.9319 | 7.1 | 2.9 | 4.2 | 0 | 0.5 | 44 | 553 | **0.08%** |
| landscape-square | 0.8874 | 12.0 | 5.7 | 6.2 | 0 | 1.5 | 81 | 986 | **0.88%** |
| sun-square | 0.8682 | 13.8 | 9.0 | 4.8 | 0 | 1.5 | 16 | 161 | **4.27%** |

`px-diff` is the incumbent's own harness — `node src/compare.js <input> <output>
1200` — so it is directly comparable to the recorded baselines:

| | dinosaur | landscape | sun |
|---|---|---|---|
| incumbent (`convert_filled_svg_to_stroked_lines.py`) | **0.02%** | **0.73%** | ~4.2% raster |
| **tegaki (this track)** | 0.08% | 0.88% | 4.27% |
| autotrace `-centerline`, best fixed-width sweep (recorded) | 0.17% | 1.79% | — |
| autotrace `-centerline`, raw (recorded) | 3.10% | 15.61% | — |

**Verdict on transfer: Tegaki's approach transfers to artistic pen strokes.** A
pipeline designed for font glyphs, ported in a session and given an SVG front
end, lands within 4× of an incumbent that was tuned over multiple sessions on
these exact images, and beats the off-the-shelf tracing baseline by 2× on both
of the recorded comparison points. It is not better than the incumbent, and on
dinosaur-wide it is 4× worse. But the gap is small enough that the *ideas* are
worth harvesting, which is the question this track existed to answer.

### 4.2 Synthetic corpus — true centerline error

Mean IoU **0.948**, median centerline P95 **0.537** on a stroke of width 20 —
i.e. the recovered centerline sits within ~2.7% of a stroke width of the known
source path for 95% of its length. Per-case table is in `metrics.json` under
`synth:baseline`; the contact sheet is `debug/tegaki/sheet/synth.baseline.png`.

The two cases that fail are the two designed to be hard:

- **19 variable-width** (IoU 0.739). The centerline is recovered essentially
  perfectly (P95 0.354) — the loss is entirely from emitting ONE width per path,
  because SVG cannot taper a stroke. The per-point profile is correct and is in
  the graph JSON; this is a limitation of the output format, not the extraction.
  Anyone consuming `strokeOrder.widthProfile` gets the right answer.
- **20 noisy boundary** (IoU 0.787, width error −3.9 on a true width of 20).
  Boundary jitter both spawns spurious branches and *depresses the inscribed
  radius*, so the recovered stroke is systematically too thin. Worth flagging to
  Track 8: **width estimated from a distance transform is biased low on a noisy
  boundary**, and the bias is one-sided, so a robust statistic along the stroke
  does not fix it — you would want to smooth the boundary or take a high
  percentile rather than the median.

Three defects the corpus caught that no amount of looking at the real images
would have — this is the argument for building it first:

1. **A half-pixel systematic bias.** Tegaki's `toFontUnits` maps the pixel
   *index* back to source units; the pixel *centre* is at index + 0.5. At 400px
   per glyph nobody notices. Measured against a known centerline it is a
   constant 0.5 px offset up and to the left of every recovered path.
2. **Cap overshoot.** The obvious cap rule — extend the terminal by one local
   radius — overshot the true endpoint of a round-capped capsule by 6 units out
   of 10. See §4.5.
3. **Width polluted by the cap extension.** Sampling the DT at the extended tip
   pulled the median width of a width-20 capsule down to 14.

### 4.3 PRUNING — the priority (a) deliverable, for Track 8

**Finding 1: Tegaki's own thinning-path pruner is completely inert on this
input.** `tegaki-length` (`L ≥ min(0.08 · bitmapSize, 10) px`, or isolated)
removed **zero** branches on all ten real images, in every configuration tested
— junction cleanup on and off, merging on and off. The reason is the hard 10 px
cap that Tegaki needs so small glyphs are not erased: on our rasters 10 px is
under half a stroke width, and every real spur is longer than that. This is the
report's §10 prediction confirmed in a working implementation: **an absolute
length threshold that needs a cap is a threshold that should have been
scale-free.**

**Finding 2: its width-aware pruner works, and its shipped constant is right.**
`tegaki-width` — Tegaki's Voronoi-path rule `L < 1.5 · (2 R_parent)`, i.e.
`L/(2R) < 1.5`, lifted onto the raster graph — fires on every image with real
junction structure, and is nearly free:

| | strokes (no prune) | strokes (width prune) | branches removed | IoU cost |
|---|---|---|---|---|
| dinosaur-wide | 48 | 44 | 4 | 0.9323 → 0.9319 |
| landscape-square | 86 | 81 | 5 | 0.8885 → 0.8874 |
| home-wide | 33 | 32 | 1 | 0.9419 → 0.9405 |

**Finding 3: the threshold sweep has a knee, and the knee is at 1.5.** Report
§10.2 asks for pruning as model selection; here is the trade-off curve
(`bench.js prune-sweep`):

| `L/(2R) <` | dinosaur IoU | dinosaur strokes | landscape IoU | landscape strokes |
|---|---|---|---|---|
| 0 (off) | 0.9323 | 48 | 0.8885 | 86 |
| 0.5 | 0.9321 | 47 | 0.8879 | 83 |
| 1.0 | 0.9319 | 45 | 0.8877 | 82 |
| **1.5** | **0.9319** | **44** | **0.8874** | **81** |
| 2.0 | 0.9298 | 43 | 0.8841 | 78 |
| 3.0 | 0.9265 | 42 | 0.8841 | 78 |
| 6.0 | 0.9237 | 41 | 0.8811 | 77 |

Up to 1.5 the curve is flat — four branches on dinosaur cost 0.0004 IoU. Past
1.5 the cost per removed branch jumps roughly **5×** (2.0 costs 0.0021 for one
more branch). Tegaki's shipped 1.5 sits exactly on the knee, on artwork it was
never designed for. That is a real, independent validation of the constant, and
Track 8 should start there rather than searching from scratch.

**Finding 4 — the one that matters most, and it is not about pruning.**
Junction-cluster collapse removes far more spurious structure than pruning ever
does, and it does so *before* the pruner can see anything:

| | with junction cleanup | without | pruning's contribution |
|---|---|---|---|
| house-wide | 26 strokes | 76 | 0 branches |
| landscape-square | 86 strokes | 252 | 5 branches |
| dinosaur-wide | 48 strokes | 165 | 4 branches |

Removing junction cleanup **triples** the graph at essentially unchanged IoU
(house-wide 0.9537 → 0.9457, landscape 0.8885 → 0.8893 — landscape actually goes
*up* by 0.0008 while carrying 3× the strokes, which is exactly the "IoU is
forgiving" trap Track 8's handoff warns about).

So the practical recommendation to Track 8 is: **most of what looks like a
pruning problem on a thinned skeleton is a junction-representation problem.**
Collapse each multi-pixel junction cluster to its highest-radius pixel and
re-attach the arms *first*; whatever survives that is a real branch, and then
`L/(2R) < 1.5` cleans up the remainder. Pruning a raw thinned skeleton is doing
the hard job with the wrong tool.

Two implementation notes that cost us time and will cost Track 8 the same:

- **The attachment test must be topological, not metric.** Our first version
  asked "is this endpoint within the merge threshold of any point of another
  polyline?". With a threshold of ~1.5 stroke radii on dense pixel chains, every
  endpoint is near something, every branch classifies as a two-ended bridge, and
  the pruner removes nothing. Use the skeleton's degree at the endpoint. (This is
  what Tegaki's Voronoi pruner does — degree-1 node walking to the first
  degree-3+ node — and it is part of why that pruner works while the length one
  does not.)
- **Pruning must run before endpoint merging, or on the graph rather than on
  polylines.** Tegaki prunes *after* `mergePolylines`, which welds branch stubs
  into longer chains and destroys the very structure the pruner is looking for.
  With merging disabled, the width-aware pruner finds 3–6× more spurs
  (landscape 5 → 29, dinosaur 4 → 9). This is an ordering bug in the reference
  implementation, not a tuning issue.

### 4.4 WIDTH ESTIMATION — the priority (b) deliverable

Native and essentially free: `width(p) = 2 · inverseDT[round(p)]`, per point.
Width coefficient of variation across the ladder runs 0.03–0.23 (the outlier is
`home-wide` at 0.59, which genuinely mixes a thick outline with thin detail).
Four things learned that generalize beyond Tegaki:

1. **Take the median along the stroke, not the mean.** The inscribed radius
   spikes at junctions — the inscribed circle at a crossing is much larger than
   the stroke — and a mean is dragged up by every junction the stroke passes
   through. Tegaki never has to choose because it keeps the whole profile.
2. **The radius at a cap is not the pen width.** Sampling at a cap-extended tip
   put the median of a width-20 capsule at 14. Inherit the neighbour's width.
3. **Tegaki's dot correction is right and non-obvious**: an isolated blob's
   inscribed radius measures the *blob*, not the pen that drew it. A 12-px dot
   drawn with a 4-px pen renders as a 12-px stroke unless you override it.
4. **DT-derived width is biased LOW on a noisy boundary** (synthetic case 20:
   −3.9 against a true width of 20). One-sided, so robust statistics do not help.

### 4.5 CAP HANDLING — an ambiguity, stated honestly

This is the largest gap between Tegaki's problem and ours: font glyphs have no
caps, so Tegaki has no cap logic at all, and report §2.3's "caps materially
affect the medial axis" is a problem it never had to solve.

We added cap extension, and the synthetic corpus settled the design. The
inscribed radius along a stroke's axis is flat at the pen radius until the true
endpoint and falls away through the cap, so **the end of the radius plateau is
the endpoint**. That recovers round and square caps to within 0.25 units
(cases 01, 07, 09: recovered `50.25→249.75` against a truth of `50→250`).

**But round and butt caps are genuinely indistinguishable locally.** The true
endpoint of a round-capped stroke and the *traced tip* of a butt-capped stroke
have identical radius profiles: full radius at the point, falling linearly to
zero one radius further out. There is no local signal separating them. We
default to `capStyle: 'round'` — extend to the plateau end, do not extend when
there is no plateau — which is correct for our round-capped inputs and leaves
butt-capped strokes one radius short at each end (synthetic case 08, centerline
Hausdorff 10.25 = exactly one radius). `capStyle: 'ink'` inverts the trade.
Tagged `cap artifact`; not hidden.

### 4.6 SKELETONIZER A/B — priority (d), five side by side on identical rasters

This is the comparison Tegaki gives away for free, and it is directly relevant
to Tracks 3 and 6 (Euclidean medial axis vs morphological thinning).

**Synthetic corpus** (ground truth available):

| method | mean IoU | median centerline P95 | median Hausdorff | strokes | points | mean abs width err |
|---|---|---|---|---|---|---|
| **zhang-suen** | **0.9474** | **0.537** | 2.805 | 28 | 165 | 0.53 |
| voronoi | 0.9369 | 3.829 | 9.375 | 1074 | 6251 | 3.82 |
| guo-hall | 0.9244 | 0.953 | 2.184 | 25 | 158 | 1.15 |
| lee | 0.8939 | 1.768 | 4.233 | 26 | 115 | 1.04 |
| medial-axis | 0.8930 | 2.019 | 5.599 | 32 | 257 | 0.98 |

**Real images:**

| method | house-wide IoU / pts | dinosaur IoU / pts |
|---|---|---|
| zhang-suen | 0.9537 / 374 | 0.9319 / 553 |
| guo-hall | 0.9525 / 377 | **0.9425** / 557 |
| lee | 0.8650 / 324 | 0.8014 / 454 |
| medial-axis | 0.9239 / 669 | 0.9067 / 1019 |
| voronoi (RDP-matched) | 0.9320 / 403 | 0.9255 / 594 |

Readings:

- **Zhang-Suen wins overall** and is the right default — best geometry AND the
  simplest graph, which §11 says to prefer when the two disagree.
- **Guo-Hall vs Zhang-Suen is genuinely image-dependent.** Over the full ladder
  Zhang-Suen edges it on the mean (0.9306 vs 0.9287), but Guo-Hall wins on 5 of
  10 images — decisively on dinosaur-wide (0.9425 vs 0.9319) and house-tall,
  and loses on boat/balloon/home/island. Nobody had compared these two before;
  the answer is "neither dominates", which supports the report's §19 hybrid
  conclusion at the level of *thinning algorithm*, not just backend.
- **The distance-ordered medial-axis thinner is WORSE, and for an instructive
  reason.** It never deletes a degree ≤ 1 pixel, so every tiny boundary bump
  spawns a branch and *keeps* it: 126 strokes and 1019 points on dinosaur-wide
  against Zhang-Suen's 44 and 553, with `extra%` at 8.2 vs 4.2 (the spurs add
  ink). This is report §10's "raw medial axis is hypersensitive to tiny shape
  irregularities" measured directly. **A geometrically more correct skeleton is
  not automatically a better one** — Track 3 should expect the same from
  `skimage.medial_axis` and plan for pruning accordingly.
  Note that Tegaki runs junction cleanup for every method *except* this one,
  which confounds its own comparison; `--junction-cleanup-for-medial-axis 5`
  makes it controlled, and the conclusion holds either way (IoU 0.809 with
  cleanup, 0.893 without, both well under Zhang-Suen's 0.947).
- **Lee's LUT thinning collapses on real images** (0.80–0.87) while scoring
  respectably on the synthetic corpus. `miss%` is 11.1 on dinosaur against
  Zhang-Suen's 2.9, so it is eroding real ink — its eight directional
  sub-iterations pull back much harder from stroke ends on curved artwork than
  on straight synthetic capsules. Do not judge a thinner on straight lines.
- **Voronoi's apparent advantage was an artifact of complexity.** Tegaki's
  Voronoi path bypasses `traceAndSimplify` entirely, so it is the one method
  whose output is never RDP-simplified. Unsimplified it scored *best* on
  dinosaur (0.9506) — while carrying 13,033 points against Zhang-Suen's 553.
  Applying the same RDP tolerance drops it to 0.9255 at 594 points. **At matched
  complexity, sampled-point Voronoi is worse than Zhang-Suen thinning**, which
  is a relevant negative for Track 4. Its raw graph is a hairball: 1074 strokes
  for the 20 simple synthetic shapes, before pruning.

### 4.7 Raster resolution sensitivity — `raster quantization`

Scale is px per user unit; runtime is O(scale²).

| scale | house-wide IoU | house ms | landscape IoU | landscape extra% | landscape ms |
|---|---|---|---|---|---|
| 1 | 0.9304 | 539 | 0.8786 | 4.5 | 1,084 |
| **2** | 0.9537 | 1,846 | **0.8874** | 6.2 | 5,708 |
| 3 | 0.9565 | 4,839 | 0.8843 | 6.9 | 15,991 |
| 4 | 0.9614 | 10,417 | 0.8793 | 8.1 | 36,187 |

House-wide improves monotonically. **Landscape-square peaks at scale 2 and then
gets worse**, with `extra%` climbing 6.2 → 8.1: a finer raster resolves more
boundary irregularity, which the medial axis faithfully turns into more spurious
branches, which add ink. More resolution is not monotonically better on artwork
with dense, irregular strokes — another instance of §10's sensitivity, and a
useful warning for Tracks 3 and 6, which are both planning resolution sweeps.

For reference, Tegaki's own default (aspect-fit the whole element into 400 px)
corresponds to roughly scale 0.25 on `landscape-square` — far below anything
usable here. Its resolution choice does not survive the change of domain.

### 4.8 Failure taxonomy

Measured counts from the final run (`real:final` in `metrics.json`):

| image | miss% (`missing narrow segment`) | extra% (`outline noise branch`) | spurs pruned | residue dots dropped | crossings seen | crossings stopped |
|---|---|---|---|---|---|---|
| house-wide | 2.2 | 2.5 | 0 | 2 | 5 | 0 |
| butterfly-wide | 2.7 | 3.5 | 0 | 1 | 11 | 0 |
| boat-tall | 1.5 | 3.6 | 0 | 1 | 8 | 3 |
| island-tall | 1.9 | 3.4 | 0 | 3 | 12 | 2 |
| balloon-tall | 2.2 | 3.8 | 0 | 3 | 17 | 5 |
| home-wide | 2.5 | 3.7 | 1 | 2 | 8 | 1 |
| house-tall | 2.6 | 3.3 | 0 | 3 | 18 | 3 |
| dinosaur-wide | 2.9 | 4.2 | 4 | 0 | 9 | 2 |
| landscape-square | 5.7 | 6.2 | 5 | 6 | 152 | 11 |
| sun-square | **9.0** | 4.8 | 0 | 0 | 45 | 1 |

Qualitative classification from the crops (`debug/tegaki/sheet/crops.*.png`):

- **`crossing ambiguity` — the dominant failure, and it owns sun-square.** Where
  two passes of the scribble touch, the two strokes merge into one wide corridor
  and the medial axis of that corridor is a *lens*: two arcs bulging apart, not
  two strokes crossing. The hairpin turn at the end of each pass is replaced by
  an arrowhead. This is not a tuning failure — the medial axis of the union is
  genuinely that shape (report §2.5, "merged source elements are harder"). No
  amount of pruning recovers it; it needs the branch-pairing / stroke-grouping
  layer that is Track 8's §13 Experiment 5. sun-square's 9.0% miss is almost
  entirely this.
- **`cap artifact`** — butt/square-capped strokes, by construction (§4.5).
  Uniformly one radius, at each free end.
- **`join artifact`** — largely handled. Junction-cluster collapse plus the
  three-test kink smoother remove the lateral jog thinning leaves at branch
  points; what remains shows up as the small `extra%` baseline of 2.5–4.2%.
- **`outline noise branch`** — 4–5 per drawing on the two densest images, all
  removed by `L/(2R) < 1.5`.
- **`disconnected skeleton`** — not observed; `restoreErasedComponents` catches
  it, and no components needed restoring on the final run.
- **`raster quantization`** — quantified in §4.7; the resolution *peak* on
  landscape is the notable form.
- **`excessive curve complexity`** — 35–63 points per 1000 units of centerline.
  Output is polylines: Tegaki does no Bézier fitting (it defers to the
  renderer's Catmull-Rom) and neither do we. Track 3's fit-curve stage is the
  missing piece and would cut this substantially.
- **`wrong endpoint`** — one phantom-blob class found and fixed: Tegaki paints
  every leftover single skeleton pixel as a dot at the *average* stroke width,
  which put six visible blobs on landscape-square. A single point is a real mark
  only if it is the only thing representing its ink component.

Note the rows where `crossings stopped` is 0 but `crossings seen` is 5–11: the
tracer detected a crossing and decided it was the through-stroke every time. On
landscape it stopped at 11 of 152. That ratio is the `shouldStopAtJunction`
heuristic actually making decisions, and it is worth Track 8 knowing that a
working local T-vs-X rule exists and how often it fires.


### 4.9 STROKE ORDER AND DIRECTION — priority (c), the stretch goal

Implemented, serialized (Part 3 schema), and visualized:
`debug/tegaki/sheet/stroke-order.png` and `debug/tegaki/sheet/order.<image>.svg`
draw each stroke in a viridis ramp from first (dark purple) to last (yellow),
with a dot at the pen-down end and an arrowhead at the pen-up end.

| image | strokes | reversed by the orientation rule | classified as dots |
|---|---|---|---|
| house-wide | 26 | 3 | 0 |
| boat-tall | 26 | 3 | 0 |
| dinosaur-wide | 44 | 7 | 0 |
| landscape-square | 81 | 38 | 0 |

The sequences are plausible as drawing orders: on `house-wide` the sun goes
first, then the house body, then the tree, and the ground line last; on
`boat-tall`, sun → mast and hull → sails → water. Directions are consistent —
mostly left-to-right, top-to-bottom, which is what `score = y + 2x` produces.

**Three honest caveats, because this is the part most likely to be over-read:**

1. **The global order is DOM order between elements, greedy nearest-neighbour
   only within an element.** Tegaki orders strokes inside one glyph; we process
   each filled SVG element separately and concatenate. So the cross-element
   sequence is inherited from the source document, not inferred. That is why the
   cloud on `house-wide` is drawn early despite being far from the sun — it is
   simply the next element in the file. Report §9.8 lists "preserve original
   source-element ordering as a weak hint" as a legitimate rule, and that is
   exactly what this is, but it should not be mistaken for a spatial decision.
2. **Nothing here is semantic.** No part of this knows a roof is drawn before a
   wall, or that an outline precedes its hatching. It is proximity and a
   coordinate score. It is a reasonable default and better than random, and it
   is nothing more than that.
3. **The dot classifier never fires on our artwork** (0 across all ten images).
   It is scoped to one element, and our elements do not contain small isolated
   marks alongside body strokes the way a glyph contains an i-dot beside a stem.
   The rule is ported and correct; the situation it was designed for does not
   arise here. Applied document-wide instead of per-element it probably would
   fire, and that is the obvious next experiment for whoever picks this up.

The transferable pieces for Track 8's Experiment 5 are the orientation scoring
function, the "small AND isolated → draw last" predicate, and the arc-length `t`
parameterization — which is the right serialization regardless of how order is
eventually decided.


---

## Part 5 — Verdict

**Does Tegaki's approach transfer to artistic pen strokes? Yes, with one caveat
and one gap.**

It transfers because the problem really is the same one: a filled 2-D region
that was produced by stroking a 1-D path. Ported in a session, with an SVG front
end and cap handling bolted on, it produces 0.04–0.15% pixel diff on eight of
the ten real inputs, 0.88% on landscape-square and 4.27% on sun-square — within
4× of an incumbent tuned specifically on these images, and 2× better than the
off-the-shelf tracing baseline on both of the recorded comparison points.

**The caveat: almost none of its constants survive the change of domain.** The
400 px whole-glyph raster is roughly 8× too coarse. The 8%-of-bitmap endpoint
merge threshold would weld unrelated strokes across a page. The 10 px spur cap
makes its length pruner inert. Every one of those is right for a glyph and wrong
for a drawing, and each had to be re-derived. What transfers is the *structure*
of the pipeline and the *shape* of its heuristics, not its numbers — with the
single striking exception of `L/(2R) < 1.5`, which is scale-free and lands
exactly on the measured knee here too. That is not a coincidence; it is what
being scale-free buys you, and it is §10's argument for normalized features in
one data point.

**The gap: merged corridors.** Where two strokes run together, the medial axis
of the union is a lens, not two strokes. Tegaki has no answer because glyph
strokes are drawn once and merged strokes are rare; our sun-square is nothing
but merged strokes. This needs stroke grouping and branch pairing, above the
geometry layer. It is the single largest remaining source of error in this
track's output, and it is Track 8's Experiment 5, not a skeletonizer choice.

**What we hand to other tracks:**

- **Track 8** — `L/(2R_parent) < 1.5` with a measured knee; the "short AND
  attached" spur predicate; the "small AND isolated" dot predicate; the finding
  that junction-cluster collapse beats pruning 3:1 and must run first; the two
  ordering/attachment bugs in the reference implementation; short-edge
  contraction as a graph primitive; and the width-estimation biases in §4.4.
- **Tracks 3 and 6** — a controlled five-way skeletonizer comparison on
  identical rasters; the warning that the geometrically-correct distance-ordered
  medial axis produces 3× the graph for worse geometry; the Guo-Hall vs
  Zhang-Suen verdict (image-dependent, neither dominates); junction-cluster
  collapse as a ready-made fix for thinning's junction smear; the
  chamfer-vs-exact-DT observation (Tegaki ships the *approximate* transform on
  purpose, because exact ridges make argmax decisions jumpy); and the resolution
  result that finer is not monotonically better.
- **Track 4** — at matched RDP complexity, sampled-point Voronoi is *worse* than
  Zhang-Suen thinning here (0.9255 vs 0.9319 on dinosaur), and its raw graph is
  a hairball (1074 strokes for 20 simple shapes).
- **Everyone** — the stroke-order/direction schema in Part 3, with a working
  producer and a visualization (§4.9), plus the observation that Tegaki's stroke
  ordering carries no stroke semantics at all: it is greedy nearest-neighbour
  from a writing-entry side, and in our adaptation the cross-element sequence is
  just DOM order. Useful as a default, but it is not the semantic layer §9.8 is
  reaching for.

**Would we productionize this?** Not as-is — the incumbent is better on the
images we have, and Track 1's vector MAT should beat a raster pipeline on vector
input if it holds up. But three components are worth lifting into whatever
architecture wins: junction-cluster collapse, the curvature-extrapolating
look-ahead tracer with its T-vs-X rule, and `L/(2R) < 1.5`.

---

## Part 6 — Experiment log

Chronological. Each entry: what changed, the number, and why it did that.

1. **First end-to-end run, synthetic capsule.** Output geometry `43.75→256.25`
   against a truth of `50→250`, width 14 against 20. Three bugs at once
   (half-pixel, cap overshoot, cap-polluted width) — see §4.2.
2. **Half-pixel correction** (map the pixel centre, not the index). Removed a
   constant 0.5-unit bias from every path.
3. **Cap rule v1: extend by `1 · R`.** Overshot by 6 units. Replaced.
4. **Cap rule v2: radius-plateau.** Capsule now `50.25→249.75`; mean synthetic
   IoU 0.905 → 0.922, median centerline P95 0.768 → 0.537. Diagonal and arc caps
   went from Hausdorff ≈ 10 (one radius) to ≈ 0.35.
5. **Metric bug: closed-loop holes.** Synthetic case 06 read IoU 0.433 /
   symDiff 130% because the re-stroke scorer rasterized a loop's outer and inner
   rings separately and OR-ed them, filling the hole. Grouping them per stroke
   → 0.958. Mean synthetic IoU 0.922 → **0.948**. Worth stating plainly: the
   scorer was wrong, not the geometry.
6. **First real ladder.** Mean IoU 0.931, six phantom blobs visible on
   landscape-square.
7. **Residue-dot filter, attempt 1** ("was it re-seeded?"). Wrong in both
   directions — dropped real ink dots on butterfly-wide (IoU 0.9402 → 0.9359)
   and kept landscape's residue. Reverted.
8. **Residue-dot filter, attempt 2** (structural: is this point the only thing
   representing its ink component?). landscape 91 → 85 strokes, house-wide
   28 → 26, IoU unchanged to four decimal places. Simpler graph, same fidelity.
9. **Pruner A/B, first attempt: both pruners removed nothing.** Diagnosed to a
   metric attachment test (§4.3). Switched to skeleton degree.
10. **Pruner A/B, corrected.** `tegaki-length` still removes zero — that is the
    real answer, not a bug. `tegaki-width` removes 4 on dinosaur, 5 on landscape.
11. **Junction-cleanup ablation.** house-wide 26 → 76 strokes with cleanup off,
    landscape 86 → 252, at unchanged IoU. The finding that reframed the whole
    pruning question.
12. **Prune threshold sweep.** Knee at 1.5; cost per branch jumps 5× past it.
13. **Skeletonizer A/B, first run: Guo-Hall scored 0.62 mean IoU.** That was a
    transcription error in the C-term grouping of my port, not a property of
    Guo-Hall. Fixed → 0.9244. Recorded here because "the exotic method scored
    badly" is exactly the result one is tempted not to double-check.
14. **Controlled medial-axis comparison.** Tegaki skips junction cleanup for
    that method only; with cleanup forced on it is still well behind Zhang-Suen.
15. **Voronoi RDP fairness fix.** Tegaki's Voronoi path is never simplified.
    Unsimplified it "won" on dinosaur (0.9506) with 13,033 points; at matched
    RDP tolerance it is 0.9255 at 594. The advantage was complexity, not quality.
16. **Resolution sweep.** landscape peaks at scale 2 and degrades above it.
17. **Guo-Hall on the full ladder.** Mean 0.9287 vs Zhang-Suen's 0.9306, but it
    wins 5 of 10 images. Neither dominates.
18. **Final promotion** at zhang-suen / chamfer / tegaki-width / scale 2.


