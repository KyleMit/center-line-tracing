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

## Part 4 — Experiment log

(Newest last. Every entry: what changed, the number, and why it did that.)

</content>
</invoke>
