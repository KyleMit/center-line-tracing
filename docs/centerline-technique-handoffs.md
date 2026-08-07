# Centerline Recovery: Per-Technique Session Handoffs

Eight independent research tracks for recovering pen centerlines from filled SVG
line art. Each track below is a **self-contained prompt** meant to be pasted into
its own fresh session so the tracks can iterate in parallel without colliding.

> **Note on provenance.** These tracks were derived from the handoff docs that
> exist in this repo (`current-attempt-handoff.md`, `sun-vector-handoff.md`,
> `filled-svg-to-stroked-lines-handoff.md`,
> `python-filled-svg-to-stroked-lines-handoff.md`) — specifically their
> "Iterations Tried", "Literature And Tooling Notes", "Recommended Next Step",
> and "Extension Ideas" sections. There is no
> `docs/svg-centerline-stroke-recovery-report.md` in the repository or in git
> history; if that report exists elsewhere, reconcile this list against it.

---

## Common Setup

Every track prompt references this section. Read it first.

### The problem

The `inputs/*.svg` files look like pen/marker drawings but are internally
**filled shapes** — the outline of the ink, not the stroke. The goal is output
SVGs built from real stroked paths:

```xml
<path d="..." fill="none" stroke="#..." stroke-width="..." stroke-linecap="round" />
```

The original centerlines, stroke order, pressure/taper model, and join semantics
were all discarded when the fills were baked. Recovering them is the task.

### The sample set

Ten inputs, roughly ordered easy → hard. Use this as the escalation ladder:

| # | File | paths | fills | Notes |
|---|------|-------|-------|-------|
| 1 | `inputs/house-wide.svg` | 11 | 6 | simplest, mostly long clean strokes |
| 2 | `inputs/butterfly-wide.svg` | 11 | 6 | symmetric curves, few junctions |
| 3 | `inputs/boat-tall.svg` | 15 | 5 | some hatching |
| 4 | `inputs/island-tall.svg` | 16 | 6 | |
| 5 | `inputs/balloon-tall.svg` | 18 | 6 | long smooth arcs |
| 6 | `inputs/home-wide.svg` | 20 | 6 | |
| 7 | `inputs/house-tall.svg` | 21 | 6 | |
| 8 | `inputs/dinosaur-wide.svg` | 38 | 6 | many elements, best-known baseline (0.02%) |
| 9 | `inputs/landscape-square.svg` | 14 | 7 | merged corridors, dense hatching (0.73%) |
| 10 | `inputs/sun-square.svg` | 2 | 1 | single continuous scribble, hairpin tips |

### Environment (verified working on this container)

Linux, `python3.11`, `node22`, running as root. The macOS-era commands in the
old handoffs (`DYLD_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python ...`) are
**stale — ignore them**. There is no `.venv` and no `node_modules` at session
start.

```bash
# Python stack — all confirmed installable, cairo native lib is already present
pip3 install numpy scipy scikit-image shapely pillow cairosvg svgpathtools svgelements

# Node stack — sharp, pixelmatch, pngjs, simplify-js are already in package.json
npm install

# apt works and you are root. potrace installs cleanly:
apt-get install -y potrace
# autotrace has NO apt candidate on this image — build from source or skip it.
```

Rasterize with `cairosvg` (Python) or `sharp` (Node); both work.

### Branch and directory conventions

Each track owns its own branch and its own directories. **Do not write into
another track's directories**, and do not modify `src/` files that the baseline
depends on (`src/convert_filled_svg_to_stroked_lines.py`, `src/compare.js`) —
copy them into your track directory if you need to change them.

```
branch:       claude/centerline-<track-slug>
code:         experiments/<track-slug>/
artifacts:    debug/<track-slug>/          # contact sheets, diffs, overlays, sweeps
final SVGs:   outputs/<track-slug>/        # only promoted results
```

Branch from `claude/svg-centerline-stroke-techniques-d0hl0y`.

### The measurement harness you must build first

`src/compare.js` already exists and does a single-pair comparison:

```bash
node src/compare.js <input.svg> <output.svg> 1200 <diff.png> <side-by-side.png>
# prints: differing pixels: N/M = X%   similarity: Y%
```

Build two things on top of it in `experiments/<track-slug>/`:

1. **`bench`** — runs your converter across every input it currently handles,
   writes `debug/<track-slug>/metrics.json` (per-image differing-pixel %, path
   count, runtime, and pass/fail), and prints a table. Re-runnable in one
   command. This is your regression net: never promote a change that regresses
   an image without saying so explicitly.

2. **`contact-sheet`** — the visual deliverable, two kinds:
   - **Comparison sheet**: one row per image, four columns —
     `input | output | diff | overlay` (overlay = output strokes in red over the
     input in grey at 40% opacity), each row labelled with the filename and
     differing-pixel %. This is the artifact that shows how the technique is
     doing across the sample set.
   - **Progress sheet**: for your current focus image, one tile per iteration in
     chronological order, each labelled with a short tag and its score, so the
     trajectory of the technique is visible at a glance.

   Render at a size where individual strokes are legible (≥400px per tile), and
   include zoomed crops of the two or three worst regions. An HTML contact sheet
   is fine and often better than a PNG grid — but also emit a PNG so it can be
   viewed without a browser.

Pixel-diff % is a proxy, not the goal. A result can score well and still look
obviously wrong (blunt tips, angular protrusions, knuckle bulges). **Always look
at the rendered output**, and when the metric and your eyes disagree, trust your
eyes and say so in your notes.

### Working rules for every track

- **Start with one image.** Get a single end-to-end pass working before
  generalizing. Do not build the full pipeline before you have seen one result.
- **If an image gets hard, move on.** Timebox it, write down precisely what
  defeated you, and go to the next image on the ladder. Come back later with
  what you learned from the easier ones. Do not grind.
- **Keep iterating.** After the first pass, loop: look at the contact sheet →
  pick the single worst visible defect → form a hypothesis → change one thing →
  re-bench → record. Many small measured iterations beat one big rewrite.
- **Commit each meaningful iteration** with the score in the message, e.g.
  `rail-pair: house-wide 1.42% -> 0.91% (width from rail separation)`. The git
  log becomes the experiment log.
- **Keep a running `debug/<track-slug>/NOTES.md`**: what you tried, the number it
  produced, and — most importantly — *why you think it did that*. Negative
  results are valuable to the other tracks; record them.
- Push to your branch as you go. Do not open a PR unless asked.

### What "done" looks like for a track

A pushed branch containing: working code, `metrics.json` across every input you
attempted, comparison and progress contact sheets, promoted SVGs in
`outputs/<track-slug>/`, and a `NOTES.md` with an honest verdict — including
"this approach does not work for X, here is the evidence" if that is the answer.
A well-evidenced negative result is a successful track.

---

## Track 1 — Variable-Width Skeleton (per-path taper recovery)

**Branch:** `claude/centerline-taper-width` · **Slug:** `taper-width`

```text
Read docs/centerline-technique-handoffs.md § Common Setup first, and follow its
environment, branch, directory, harness, and working rules exactly.
Your slug is `taper-width`; work on branch claude/centerline-taper-width.

TECHNIQUE: Variable-width skeleton — recover stroke width as a function of
position along each centerline, instead of one width per element.

The existing baseline (src/convert_filled_svg_to_stroked_lines.py) rasterizes
each filled element, skeletonizes it (Zhang-Suen), traces the skeleton graph,
and emits each path with a SINGLE median stroke width. The source drawings are
made with a pressure-sensitive pen: strokes are fat in the middle and taper to
needle points at the ends. A single median width simultaneously under-fills the
fat middles and over-fills the tips, and it can never render a needle tip at all.
The old handoff lists this as the #1 remaining perceptual gap.

THE IDEA: the Euclidean distance transform of the filled mask, sampled at each
skeleton pixel, IS the local stroke radius. That signal is already computed and
then thrown away by taking its median. Keep it as a per-vertex width profile and
render strokes that actually vary in width.

WHAT TO BUILD:
1. Get the baseline running on this Linux container first (the DYLD/venv
   commands in docs/current-attempt-handoff.md are stale — see Common Setup).
   Reproduce the known-good numbers as your control: dinosaur-wide 0.02%,
   landscape-square 0.73%. If you cannot reproduce them, say so with evidence
   and use whatever you do get as the control baseline.
2. Copy the converter into experiments/taper-width/ and extend it to carry a
   per-vertex radius array alongside each traced centerline.
3. Smooth the radius profile along the path (the raw DT is noisy and spikes at
   junctions) and decide how to render it. Three options, try them in order of
   increasing cost:
   a. Split each path into K runs of near-constant width (K adaptive, 2-6),
      emit each run as its own stroke with overlap at the seams so no gap shows.
   b. Emit the stroke as a filled ribbon polygon built by offsetting the
      centerline by the radius profile on both sides — note this reintroduces a
      fill, so only do it if you can justify it; the project requirement is
      stroked paths, so (a) is the safer target.
   c. Taper only the terminal segments (last ~15% of each end) to a needle,
      keeping the interior at median width — cheap, and may capture most of the
      visual win.
4. Measure the path-count cost. Splitting multiplies path counts; if a technique
   triples the file size for 0.1% improvement, record that tradeoff honestly.

FIRST TARGET: inputs/sun-square.svg — it is a single continuous scribble with the
most extreme taper in the set, so the effect is maximally visible and there is
only one element to reason about. Then inputs/landscape-square.svg (dense
tapered hatching, currently 0.73%), then the ladder.

WATCH FOR: junction radius spikes (the DT balloons where strokes cross, which
will make a stroke bulge at every crossing — you likely need to clamp or
interpolate the profile across junction neighbourhoods); and seam artifacts
where split runs meet.

SUCCESS: visible needle tips and fat middles on the sun and the landscape
hatching, without regressing dinosaur-wide. Report both the pixel metric and a
zoomed visual verdict — this technique is expected to win perceptually even if
the metric barely moves, and that is a legitimate result.
```

---

## Track 2 — Vector Chordal-Axis Medial Axis (no rasterization)

**Branch:** `claude/centerline-chordal-axis` · **Slug:** `chordal-axis`

```text
Read docs/centerline-technique-handoffs.md § Common Setup first, and follow its
environment, branch, directory, harness, and working rules exactly.
Your slug is `chordal-axis`; work on branch claude/centerline-chordal-axis.

TECHNIQUE: Reconstruct centerlines in VECTOR space from the outline geometry via
constrained Delaunay triangulation (chordal axis), with no rasterization step.

Rasterizing destroys sharp corners: at a hairpin fold the medial axis of a
rasterized stroke pulls back from the true point, and skeleton + round cap
renders the fold as a rounded blob instead of a sharp point. Triangulating the
outline polygon instead gives terminal triangles that point straight INTO the
sharp corners, so tips are recovered as exact vertices.

PRIOR ART IN THIS REPO: src/sun_vectorize.py already implements this for
inputs/sun-square.svg and it works — read it and docs/sun-vector-handoff.md
before writing anything. It scores ~6.3% on the sun vs the raster pipeline's
~4.2%, but with SHARP tips, which is the perceptual win. It is standalone and
hard-codes the sun's 2-path structure (outer ring + scribble).

YOUR JOB: generalize it into a real converter that handles arbitrary inputs.

WHAT TO BUILD:
1. Get src/sun_vectorize.py running on this Linux container and reproduce the
   sun result as your control.
2. Copy it to experiments/chordal-axis/ and remove the sun-specific assumptions:
   - Handle N filled elements of arbitrary colour, not a fixed ring+scribble.
   - Handle paths with holes / multiple subpaths (even-odd and nonzero winding).
   - Replace the hard-coded ring reconstruction with a general closed-loop case:
     detect when an element is an annulus (a band with two boundary loops) and
     take its mid-loop, rather than fitting a circle.
3. Robustness is the real work here. Bezier and arc flattening tolerance,
   degenerate slivers, self-intersecting outlines, and near-duplicate boundary
   points will all break the triangulation. Build in validation and a clear
   failure mode per element (fall back and report, never crash the run).
4. Classify triangles by boundary-edge count (terminal=2, sleeve=1, junction=0),
   build the graph, prune tip-fork spurs, contract fold clusters into single
   sharp vertices, then trace. That skeleton of the algorithm is already in
   sun_vectorize.py — reuse it.

FIRST TARGET: inputs/sun-square.svg (already works — get it green as a control),
then inputs/butterfly-wide.svg (few junctions, smooth curves — the gentlest test
of generalized flattening), then inputs/house-wide.svg, then the ladder.

WATCH FOR: junction triangles in dense hatching produce a hairball of short
graph edges; the fold-cluster contraction radius that works on the sun will
likely need to be a function of local stroke width rather than a constant.

SUCCESS: a general converter that beats the raster pipeline on tip sharpness
across at least three inputs. Expect it to LOSE on pixel-diff while winning
visually — document both, with zoomed tip crops as the evidence.
```

---

## Track 3 — Outline Rail Pairing

**Branch:** `claude/centerline-rail-pairing` · **Slug:** `rail-pairing`

```text
Read docs/centerline-technique-handoffs.md § Common Setup first, and follow its
environment, branch, directory, harness, and working rules exactly.
Your slug is `rail-pairing`; work on branch claude/centerline-rail-pairing.

TECHNIQUE: Treat the filled shape as a ribbon with two opposing boundary "rails".
Match each point on one rail to the point facing it across the ink on the other
rail; the centerline is the midpoint sequence and the stroke width is the rail
separation — both recovered exactly, for free, at every point.

WHY THIS INSTEAD OF SKELETONIZATION: the known failure of the current pipeline is
"merged corridors" — where two near-parallel pen passes overlap lengthwise, the
union skeleton collapses them into ONE line, producing knuckle bulges and sparse
hatching. A skeleton fundamentally cannot represent two strokes in one blob.
Rail pairing can, because two parallel passes present four rails, and the correct
pairing recovers two separate centerlines. This is the #2 remaining gap in
docs/current-attempt-handoff.md and no prior attempt has tried it.

WHAT TO BUILD:
1. Extract the boundary of each filled element as an ordered polygon (from the
   SVG path data directly, or by contouring a high-res raster — your call, but
   vector is cleaner and avoids a resampling stage).
2. Pair the rails. This is the core research problem; approaches to try:
   - Normal casting: from each boundary point, cast a ray along the inward
     normal and record where it exits the shape. Points whose rays land on each
     other are a rail pair. Cheap and works well on clean parallel-sided runs.
   - Width-consistency matching: prefer pairings whose separation varies smoothly
     along the run, which naturally rejects the spurious "across the junction"
     pairings that normal casting produces at crossings.
   - Dynamic programming / optimal transport over the two boundary arcs, which
     handles taper and mild curvature better than greedy matching.
3. Segment the boundary into rail runs first: split the boundary at high-
   curvature corners (stroke ends and junction corners), then pair RUNS rather
   than raw points. This is usually what makes the whole thing tractable.
4. Emit centerline = midpoints, width = separation (which gives you the taper
   from Track 1 for free — coordinate with that track's rendering choices via
   its NOTES.md if it has pushed any).

FIRST TARGET: inputs/house-wide.svg — 11 paths, mostly long clean parallel-sided
strokes, which is the ideal case for rail pairing and will tell you fast whether
the matching works at all. Then inputs/balloon-tall.svg (long smooth arcs), then
go straight to inputs/landscape-square.svg because its merged corridors are the
specific defect this technique exists to fix — that is your real test.

WATCH FOR: junctions are where this breaks. At a crossing the "rails" of one
stroke are interrupted by the other. Expect to need an explicit junction pass
that detects interruption, bridges the rail across the gap, and continues. Do
not try to solve junctions before you have clean straight-run pairing working.

SUCCESS: two distinct centerlines recovered from a merged corridor in
landscape-square where the current pipeline produces one. A single zoomed
before/after crop proving that is worth more than any percentage.
```

---

## Track 4 — Direction-Field Junction Disambiguation (PolyVector-style)

**Branch:** `claude/centerline-frame-field` · **Slug:** `frame-field`

```text
Read docs/centerline-technique-handoffs.md § Common Setup first, and follow its
environment, branch, directory, harness, and working rules exactly.
Your slug is `frame-field`; work on branch claude/centerline-frame-field.

TECHNIQUE: Compute a smooth direction field (a frame field / PolyVector field)
over the ink region, then trace centerlines by following the field — so that at
a junction, a stroke continues in the direction the field says it should,
rather than being decided by local skeleton topology.

The old handoff names this as THE central missing capability: "junction
disambiguation: deciding how stroke branches should pass through acute turns,
overlaps, and self-intersections." Every other technique in this project fights
junctions with local heuristics (paired tracing, overlap-spur folding, tip-corner
detection). This track attacks it with global information instead.

THE IDEA (from the line-drawing vectorization literature, e.g. PolyVector fields
and junction-aware frame fields): near a stroke's interior the ink has one clear
local orientation; at a crossing it has two. Fit a field that can represent
one-or-two directions per point (classically via a complex-valued 4-symmetry
field), regularized to be smooth, and constrained to align with the ink boundary
tangents. Then a stroke crossing a junction simply follows its own field branch
straight through, and the ambiguity resolves globally instead of locally.

WHAT TO BUILD:
1. Rasterize each element to a mask at high scale. Compute boundary tangents and
   a structure tensor / gradient orientation field over the ink.
2. Fit the smooth direction field by minimizing (alignment to boundary tangents)
   + (smoothness), which is a sparse linear or nonlinear least-squares solve —
   scipy.sparse is available. Start with a SINGLE-direction field, get the whole
   pipeline end-to-end, and only then upgrade to a two-direction/4-symmetry field
   for crossings. Do not start with the hard version.
3. Detect junction regions (where the field's single-direction fit has high
   residual, or where the mask is locally much wider than the stroke width).
4. Trace: stream centerlines along the field from stroke endpoints, and at each
   junction continue along the field branch rather than choosing by graph degree.
5. Compare directly against the existing --trace-mode paired heuristic on the
   same images — the whole point is to beat that heuristic at junctions.

FIRST TARGET: inputs/dinosaur-wide.svg — it has the most elements and junctions
of any input and it has the strongest known baseline (0.02%), so any junction
improvement or regression shows up immediately against a solid control. If the
field fitting is slow, develop against a single cropped element first, then
scale up. Then inputs/landscape-square.svg (dense crossing hatching).

WATCH FOR: this is the most research-heavy track and the most likely to eat time
without producing output. Timebox the field solver hard. If after a reasonable
effort the field is not converging to something visibly sensible, fall back to
"use the field ONLY to score junction continuations in the existing paired
tracer" — a much smaller change that still tests the core hypothesis and will
produce a usable result.

SUCCESS: a junction that the current pipeline gets wrong (angular protrusion,
wrong pairing) resolved correctly, shown as a zoomed crop. Also report field
visualizations in your contact sheets — a rendered field overlay is the fastest
way to see whether the solve is sane.
```

---

## Track 5 — Gesture Assembly + Bézier Fitting

**Branch:** `claude/centerline-gesture-bezier` · **Slug:** `gesture-bezier`

```text
Read docs/centerline-technique-handoffs.md § Common Setup first, and follow its
environment, branch, directory, harness, and working rules exactly.
Your slug is `gesture-bezier`; work on branch claude/centerline-gesture-bezier.

TECHNIQUE: Two coupled ideas about the OUTPUT representation rather than the
extraction. (1) Assemble fragments into long, continuous, human-plausible
strokes by minimum-curvature linking across junctions. (2) Fit smooth cubic
Béziers to the result instead of emitting dense polylines.

Current output is polylines with one vertex per few skeleton pixels. That is
both huge and subtly wrong-looking: a hand-drawn stroke is smooth and continuous,
and the current pipeline chops it into fragments at every junction and then
renders each fragment as a chain of tiny straight segments. Both handoff docs
list Bezier fitting as an unimplemented extension, and "preserve or reconstruct
drawing order" as another.

THE IDEA: this is offline handwriting / sketch trajectory reconstruction. A human
drawing a stroke does not stop at a crossing. Given a graph of centerline
fragments, the correct assembly is the one that continues smoothly: at each
junction, pair the incoming and outgoing fragments that minimize turn angle and
curvature discontinuity, producing a small number of long strokes rather than
many short ones. Then fit each long stroke with a curvature-continuous Bezier
chain (Schneider-style least-squares fitting with adaptive subdivision at high
error), which both smooths raster stair-stepping and shrinks the file massively.

WHAT TO BUILD:
1. Take centerline fragments from the existing baseline (run
   src/convert_filled_svg_to_stroked_lines.py and consume its traced paths, or
   add a debug dump of the pre-simplification skeleton graph). You are not
   re-solving extraction — you are re-solving assembly and representation.
2. Gesture assembly: build the fragment graph, then greedily (or via a matching
   solve) pair fragments through each junction by minimum turn angle, with a
   cutoff so genuinely-separate strokes are not welded together. Track how many
   strokes the drawing decomposes into and sanity-check it against how many
   strokes a human would plausibly have drawn.
3. Bezier fitting: implement least-squares cubic fitting with adaptive
   subdivision on max-error, plus corner detection so that genuine sharp corners
   are preserved as C0 breaks rather than smoothed into arcs. This corner
   handling is what makes or breaks the result.
4. Report file size and path/segment counts alongside pixel metrics — a 10x
   size reduction at equal fidelity is a real win for this track.

FIRST TARGET: inputs/balloon-tall.svg — long smooth arcs are exactly where
polyline output looks worst and Bezier fitting wins most obviously. Then
inputs/boat-tall.svg, then inputs/dinosaur-wide.svg (does assembly hold up with
38 elements and many junctions?).

WATCH FOR: over-smoothing. The failure mode is rounding off the sharp pen
corners that Tracks 1 and 2 are working hard to sharpen. Your corner detector
must run BEFORE fitting, and you should verify tip sharpness visually on every
iteration, not just the aggregate metric.

SUCCESS: markedly fewer, longer, smoother strokes at equal-or-better pixel
fidelity and much smaller files, with sharp corners preserved. Include a
stroke-count and byte-size column in your metrics table.
```

---

## Track 6 — External Tracers + Width Recovery

**Branch:** `claude/centerline-external-tracers` · **Slug:** `external-tracers`

```text
Read docs/centerline-technique-handoffs.md § Common Setup first, and follow its
environment, branch, directory, harness, and working rules exactly.
Your slug is `external-tracers`; work on branch claude/centerline-external-tracers.

TECHNIQUE: Use established vectorization engines for the centerline geometry, and
add the missing piece — per-path stroke width — as a post-pass of our own.

PRIOR RESULT AND WHY IT IS NOT THE WHOLE STORY: autotrace's -centerline mode was
tested before and scored badly (dinosaur 3.10%, landscape 15.61% raw; best
fixed-width sweep 0.17% and 1.79%). But read the diagnosis in
docs/current-attempt-handoff.md: "raw autotrace centerline output did not
preserve usable stroke widths." The geometry may have been fine and the WIDTH was
the failure — and the previous test only ever tried a single global fixed width
per drawing. That is a weak test of a potentially strong tool.

THE IDEA: let the external tracer produce centerline geometry, then recover width
ourselves by sampling the Euclidean distance transform of the original filled
mask along each traced path. Per-path (or per-vertex) width, measured from the
source, instead of one global guess.

WHAT TO BUILD:
1. Get the tools. On this container: `apt-get install -y potrace` works.
   `autotrace` has NO apt candidate — you will need to build it from source
   (autotrace/autotrace on GitHub, needs autotools + imagemagick dev headers) or
   find another route. Timebox the build; if it fights you, proceed with the
   others and record the blocker.
   Also evaluate: VTracer (Rust, `cargo install vtracer`, or the npm/wasm build),
   Inkscape's command-line trace if installable, and potrace itself (which is
   outline-only, so it is useful here as a CLEAN OUTLINE SOURCE feeding Track
   3-style processing, not as a centerline tracer).
2. Build a uniform adapter: input SVG -> raster mask -> tracer -> centerline
   paths in our coordinate space. Getting the coordinate/scale round-trip exactly
   right is fiddly and is a common source of misleading bad scores — verify it by
   overlaying traced centerlines on the input mask before you measure anything.
3. Width recovery post-pass: compute the EDT of the source mask, sample it along
   each traced path, take a robust per-path statistic (and optionally a per-vertex
   profile), and emit stroked paths at that width.
4. Then sweep the tracer's own parameters (corner threshold, error threshold,
   filter iterations, despeckle) — but only after width recovery is in, since the
   previous evaluation conflated the two.

FIRST TARGET: inputs/house-wide.svg (simplest — proves the adapter and the
coordinate round-trip), then re-run inputs/dinosaur-wide.svg and
inputs/landscape-square.svg to compare directly against the recorded prior
numbers (3.10% / 15.61% raw, 0.17% / 1.79% fixed-width). Beating 0.17% and 1.79%
is your bar; beating the Python pipeline's 0.02% / 0.73% is the stretch goal.

WATCH FOR: some tracers emit centerlines only for thin structures and outlines
for thick ones, silently mixing the two in one file. Detect and report that
rather than measuring a mixed result.

SUCCESS: a clear, evidenced verdict on whether an off-the-shelf tracer plus our
width recovery is competitive with the bespoke pipeline. "No, and here are the
numbers and the crops showing why" is a perfectly good outcome that saves
everyone else time.
```

---

## Track 7 — Raster-Supervised Stroke Optimization (fit by rendering)

**Branch:** `claude/centerline-fit-by-render` · **Slug:** `fit-by-render`

```text
Read docs/centerline-technique-handoffs.md § Common Setup first, and follow its
environment, branch, directory, harness, and working rules exactly.
Your slug is `fit-by-render`; work on branch claude/centerline-fit-by-render.

TECHNIQUE: Stop trying to DERIVE the centerline geometrically. Instead, propose
strokes, render them, compare to the target, and optimize the stroke parameters
to minimize the difference.

Every other track is a forward geometric construction whose errors are only
discovered at the end, when we measure pixels. This track closes that loop: the
pixel metric we already use for evaluation becomes the objective function that
drives the fit. Anything the metric rewards, the optimizer will find — including
solutions no geometric heuristic would have proposed.

WHAT TO BUILD:
1. A fast differentiable-or-samplable renderer for stroked paths. Options in
   increasing order of ambition:
   a. Analytic coverage: a stroked polyline's coverage of a pixel is a
      capsule-distance function — render by evaluating distance-to-segment on a
      grid with numpy. Fast, vectorized, and gives you exact gradients w.r.t.
      vertex positions and widths analytically. START HERE.
   b. Finite-difference or CMA-ES / simulated annealing over parameters if you
      cannot get analytic gradients working. Slower but far simpler.
   c. A real differentiable vector renderer (diffvg-style) if you want to invest
      — check installability before committing, and do not let it block you.
2. Initialization matters more than the optimizer. Seed from the existing
   baseline's skeleton output (run src/convert_filled_svg_to_stroked_lines.py),
   then let optimization REFINE vertex positions, widths, and endpoint extents.
   Random initialization will not converge on drawings this complex.
3. Optimize per element, not globally, so runs stay fast and failures stay local.
   Free parameters: vertex positions, per-vertex width, endpoint extension.
   Add a regularizer penalizing curvature and total vertex count so the optimizer
   does not shred smooth strokes into noise chasing the last 0.1%.
4. Watch runtime. Report seconds-per-element; a technique that needs ten minutes
   per drawing is a different proposition than one that needs two, and that
   tradeoff is part of the result.

FIRST TARGET: inputs/house-wide.svg — few elements, simple geometry, fast
iterations while you get the renderer and optimizer loop correct. Verify your
renderer against sharp/cairosvg output on a hand-written test SVG BEFORE
optimizing anything; a subtly wrong renderer will silently optimize toward
garbage and cost you the whole session. Then inputs/butterfly-wide.svg, then
inputs/dinosaur-wide.svg to see if it can beat 0.02%.

WATCH FOR: overfitting to the metric. The optimizer will happily produce wiggly,
inhuman strokes that score beautifully. Judge every result visually and keep the
curvature regularizer honest. If the output scores better but looks worse, that
is a finding about the METRIC and you should write it up — it matters to every
other track.

SUCCESS: measurable improvement over the seed initialization on at least two
images, with output that still looks hand-drawn. Also valuable: a per-image
report of how much headroom the metric shows above the current pipeline, which
tells everyone else how much is left on the table.
```

---

## Track 8 — Stroke Decomposition Before Centerlining

**Branch:** `claude/centerline-decomposition` · **Slug:** `decomposition`

```text
Read docs/centerline-technique-handoffs.md § Common Setup first, and follow its
environment, branch, directory, harness, and working rules exactly.
Your slug is `decomposition`; work on branch claude/centerline-decomposition.

TECHNIQUE: Split each filled element into individual overlapping stroke
primitives FIRST, then centerline each primitive independently and let them
overlap in the output.

Every current approach centerlines the union of the ink and then tries to undo
the damage with junction heuristics. But a drawing is not a union — it is a
sequence of separate pen strokes laid on top of each other. If you can segment
the filled region back into its constituent strokes before extracting any
centerline, then each stroke is a simple ribbon with an unambiguous medial axis,
and junctions stop being a problem entirely because they were never merged.
This inverts the pipeline order, which is why it is worth a separate track.

THE IDEA: at a place where two strokes cross, the union's boundary has four
distinctive concave corners (the notches where one stroke's edge runs into the
other's). Those notches are the cut points. Pair them up across the junction —
respecting stroke-width continuity and direction continuity — cut the region, and
you have recovered the individual overlapping ribbons. This is a shape-
decomposition problem (in the spirit of convex/near-convex decomposition and
occlusion-aware shape completion), applied to ink.

WHAT TO BUILD:
1. Junction detection on the filled mask: find regions where the local width is
   substantially greater than the surrounding stroke width (via the distance
   transform), and locate the concave boundary corners bounding each such region.
2. Notch pairing: match concave corners across the junction so each pair forms
   one cut. Score candidate pairings on cut length, resulting width continuity,
   and direction continuity of the reconnected pieces. This is the crux.
3. Cut and reassemble: split the region at the cuts into pieces, then reconnect
   pieces across each junction into whole strokes (piece A continues into piece C
   through the junction, B into D). Each reassembled stroke is a simple ribbon.
4. Centerline each ribbon with whatever is simplest and most reliable — the
   existing skeletonizer is fine, since the hard case has been removed. Overlap
   the strokes freely in the output; overlapping is CORRECT here.
5. A useful sanity check: reconstruct the union from your decomposed strokes and
   diff it against the original mask. If the decomposition is valid, that
   reconstruction should be near-perfect independent of centerline quality —
   which lets you debug decomposition and centerlining separately. Build that
   check early; it will save you.

FIRST TARGET: inputs/butterfly-wide.svg — few, clean, well-separated crossings,
so you can verify notch detection and pairing on cases you can check by eye.
Then inputs/boat-tall.svg (hatching with real crossings), then
inputs/landscape-square.svg (dense hatching — the stress test).

WATCH FOR: shallow-angle crossings, where two strokes meet at a narrow angle and
the notches are barely concave or absent entirely; and self-overlap, where one
stroke doubles back onto itself and "decomposition" would wrongly split a single
stroke in two. Detect these and fall back to plain skeletonization for that
element rather than producing garbage — a per-element fallback keeps the whole
run useful.

SUCCESS: a crossing correctly decomposed into two continuous strokes, shown as a
zoomed crop with each recovered stroke in a different colour. That image is the
deliverable that proves the idea; the pixel metric is secondary here.
```

---

## Cross-track coordination

The tracks are deliberately independent, but three produce results the others
want:

- **Track 1 (taper width)** and **Track 3 (rail pairing)** both produce per-point
  width. Whichever lands first should write its rendering approach into
  `debug/<slug>/NOTES.md` so the other can reuse it rather than re-deciding.
- **Track 7 (fit-by-render)** measures how much headroom the pixel metric has
  above the current pipeline, and is the most likely to discover that the metric
  itself is misleading. That finding, if it comes, changes how every other track
  should judge itself.
- **Tracks 2, 3, and 8** all attack junctions from different directions
  (triangulation, rail matching, decomposition). If two of them converge on the
  same junction taxonomy, that taxonomy is probably right and worth promoting
  into shared code.

None of them should block on the others.
