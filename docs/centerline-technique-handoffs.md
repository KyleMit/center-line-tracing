# Centerline Recovery: Per-Backend Session Handoffs

Eight independent tracks derived from
[`docs/svg-centerline-stroke-recovery-report.md`](./svg-centerline-stroke-recovery-report.md).
Each track below is a **self-contained prompt** meant to be pasted into its own
fresh session, so every candidate backend in the report can be prototyped and
iterated on in parallel without collisions.

Track numbering follows the report's §18 final ranking. Tracks 1–4 are its Tier 1
("prototype immediately"); Tracks 5–7 cover Tier 2 and Tier 3; Track 8 is the
shared semantic layer the report calls "probably the most important custom logic"
(§10) and "the single most valuable quality technique to add" (§11).

| Track | Report ref | Backend / idea | Tier |
|---|---|---|---|
| 1 | §6.1, §18.1 | `flo-mat` vector MAT/SAT over Béziers | 1 |
| 2 | §6.2, §18.2 | AutoTrace `-centerline` baseline | 1 |
| 3 | §6.5–6.7, §18.3 | scikit-image `medial_axis` + Skan + fit-curve | 1 |
| 4 | §6.3–6.4, §18.4/9 | PyGeoOps + fitodic polygon-Voronoi centerlines | 1/3 |
| 5 | §6.9, §18.5 | Tegaki generator, adapted | 2 |
| 6 | §6.6, §6.8, §18.6/10 | OpenCV thinning + `skeleton-tracing` | 2/3 |
| 7 | §6.10–6.12, §18.8/11/12 | Boost.Polygon Voronoi, CGAL, PostGIS | 2/3 |
| 8 | §10, §11, §13 | Width-aware pruning + re-stroke scoring + graph layer | — |

---

## Common Setup

Every track prompt references this section. Read it, and the report, first.

### The problem

Per the report's framing, this is **inverse stroke recovery**: given a filled 2-D
region that was plausibly produced by stroking one or more 1-D paths, infer
centerline paths that can be re-stroked. This is *not* ordinary vectorization —
Potrace/VTracer find the **boundary**; we want the **curve through the interior**
(§8). For roughly constant-width round-capped pen strokes the target object is
the **Euclidean medial axis / MAT** (§1.3), plus pruning (§10).

Output shape:

```xml
<path d="..." fill="none" stroke="#..." stroke-width="..." stroke-linecap="round" />
```

### The sample set

Ten real inputs, ordered easy → hard. Use as the escalation ladder (§12.2):

| # | File | paths | fills | Notes |
|---|------|-------|-------|-------|
| 1 | `inputs/house-wide.svg` | 11 | 6 | simplest, long clean strokes |
| 2 | `inputs/butterfly-wide.svg` | 11 | 6 | smooth curves, few junctions |
| 3 | `inputs/boat-tall.svg` | 15 | 5 | some hatching |
| 4 | `inputs/island-tall.svg` | 16 | 6 | |
| 5 | `inputs/balloon-tall.svg` | 18 | 6 | long smooth arcs |
| 6 | `inputs/home-wide.svg` | 20 | 6 | |
| 7 | `inputs/house-tall.svg` | 21 | 6 | |
| 8 | `inputs/dinosaur-wide.svg` | 38 | 6 | many elements; best-known baseline **0.02%** |
| 9 | `inputs/landscape-square.svg` | 14 | 7 | merged corridors, dense hatching; **0.73%** |
| 10 | `inputs/sun-square.svg` | 2 | 1 | single scribble, hairpin tips; raster ~4.2% blunt / vector ~6.3% sharp |

The existing Python pipeline (`src/convert_filled_svg_to_stroked_lines.py`) is the
incumbent to beat; those bolded numbers are its scores. `src/sun_vectorize.py` is
a working chordal-axis experiment. Read `docs/current-attempt-handoff.md` and
`docs/sun-vector-handoff.md` for what has already been tried and rejected.

### Build the synthetic ground-truth corpus first (§12.1)

**Do this before touching your backend.** The real inputs have no ground truth —
only reconstruction error. Synthetic shapes generated *from known centerlines* let
you measure true centerline error and isolate exactly which geometric feature
breaks your backend. Generate filled shapes by stroking known paths, keeping the
source path:

1. horizontal line · 2. diagonal line · 3. circular arc · 4. S curve ·
5. tight U curve · 6. closed loop · 7. round cap · 8. butt cap · 9. square cap ·
10. round join · 11. bevel join · 12. miter join · 13. X crossing kept as separate
shapes · 14. X crossing boolean-unioned · 15. T junction · 16. Y junction ·
17. almost-touching parallel lines · 18. small self-overlap · 19. variable-width
stroke · 20. noisy vectorized boundary

Report §6.1 flags cases 7–9 and 13–16 as the highest-risk area for any backend.
Run these before the real artwork — a backend that fails case 14 will fail
`landscape-square.svg` too, and the synthetic case tells you *why* in minutes.

### Metrics (§11) — build this harness second

`src/compare.js` already gives a raster pixel-diff:

```bash
node src/compare.js <input.svg> <output.svg> 1200 <diff.png> <side-by-side.png>
```

Keep it for continuity with the incumbent's numbers, but the report is explicit
that **re-stroke reconstruction scoring** is the real measure. Implement:

- **IoU** — `area(S_orig ∩ S_recon) / area(S_orig ∪ S_recon)`
- **Symmetric difference area** — `area(S_orig XOR S_recon)`; the best optimization loss
- **Boundary distance** — nearest-distance error, report **median and P95** (never max — one pathological point dominates it)
- **Centerline complexity** — stroke count, branch count, Bézier segment count, total length. Between two results with near-identical geometry error, **prefer the simpler graph**
- **Width error** — variation in estimated local radius along the centerline
- **Runtime** per element
- **Centerline Hausdorff/P95 vs the known source path** — synthetic corpus only

Write `debug/<slug>/metrics.json` from one re-runnable `bench` command, and print
a table. Never promote a change that regresses an image without saying so.

### Emit the common graph model (§13, Experiment 3)

Every track must serialize its extraction to this shape before pruning, so results
are comparable across sessions and Track 8's shared layer can consume any backend:

```ts
interface CenterlineNode { id: string; x: number; y: number; radius?: number }
interface CenterlineEdge {
  id: string; from: string; to: string;
  geometry: Bezier[] | Point[];
  length: number; medianRadius?: number; sourceElementId?: string;
}
```

Dump it as JSON to `debug/<slug>/graphs/<image>.json`. This is a hard requirement,
not a nicety — it is what makes eight parallel sessions add up to one system.

### Tag every failure (§13, Experiment 2)

Classify each defect with the report's taxonomy, and put the counts in your
metrics table: `cap artifact` · `join artifact` · `outline noise branch` ·
`crossing ambiguity` · `disconnected skeleton` · `missing narrow segment` ·
`wrong endpoint` · `excessive curve complexity` · `raster quantization`.

Shared vocabulary across tracks is how we learn which backend fails where.

### Contact sheets — the visual deliverable

Two kinds, both required:

- **Comparison sheet** — one row per image, four columns:
  `input | output | diff | overlay` (overlay = recovered centerlines in red over
  the input fill in grey at 40%), labelled with filename, IoU, and pixel-diff %.
  Include zoomed crops of the two or three worst regions.
- **Progress sheet** — for your current focus image, one tile per iteration in
  chronological order, labelled with a short tag and score, so the trajectory is
  visible at a glance.

≥400px per tile so individual strokes are legible. HTML is fine and often better,
but also emit a PNG so it can be viewed without a browser.

Metrics are proxies. **Always look at the rendered output**, and when the numbers
and your eyes disagree, trust your eyes and say so in your notes.

### Environment — verified working on this container

Linux, `python3.11`, `node22`, running as root. The macOS commands in the older
handoffs (`DYLD_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python …`) are **stale —
ignore them**. No `.venv` and no `node_modules` at session start.

```bash
# Python — all verified installable; native cairo is already present
pip3 install numpy scipy scikit-image shapely pillow cairosvg svgelements \
             pygeoops centerline skan opencv-contrib-python-headless

# Node — sharp/pixelmatch/pngjs/simplify-js already in package.json
npm install
# verified available on npm: flo-mat@4.1.0, fit-curve@0.2.0,
# svg-path-commander@2.3.1, @resvg/resvg-js@2.6.2, paper@0.12.18

# apt works and you are root
apt-get install -y potrace          # installs cleanly
# autotrace: NO apt candidate on this image — see Track 2
# skeleton-tracing: NOT on npm — vendor from GitHub (LingDong-/skeleton-tracing)
```

`npm install` on this image rewrites `package-lock.json` by stripping `libc`
fields from optional deps. That is npm-version churn, not a real dependency
change — **revert it** (`git checkout -- package-lock.json`) rather than commit it.

Use `resvg` (§7.1) for deterministic rasterization where a backend needs pixels —
the report specifically calls out determinism (§15) as mattering for reproducible
scoring. `cairosvg` and `sharp` also work.

### Branch and directory conventions

Each track owns its branch and directories. **Do not write into another track's
directories**, and do not modify the incumbent
`src/convert_filled_svg_to_stroked_lines.py` or `src/compare.js` — copy them into
your track directory if you need changes.

```
branch:       claude/centerline-<slug>
code:         experiments/<slug>/
artifacts:    debug/<slug>/           # contact sheets, metrics.json, graphs/, NOTES.md
final SVGs:   outputs/<slug>/         # only promoted results
```

Branch from `claude/svg-centerline-stroke-techniques-d0hl0y`.

### Working rules

- **Start with one image.** One end-to-end pass before generalizing. Do not build
  the whole pipeline before seeing a result.
- **If an image gets hard, move on.** Timebox it, write down precisely what
  defeated you, go to the next rung. Return later with what the easier ones
  taught you. Do not grind.
- **Keep iterating.** Loop: contact sheet → pick the single worst visible defect →
  hypothesis → change one thing → re-bench → record.
- **Do not implement sophisticated pruning early** (§13, Experiment 1). The point
  of the first pass is learning which backend preserves the expected centerline.
  Pruning is Track 8's job and it will consume your graph JSON.
- **Commit each meaningful iteration** with the score in the message, e.g.
  `flo-mat: house-wide IoU 0.71 -> 0.88 (cap extension by radius)`. The git log
  becomes the experiment log.
- **Keep `debug/<slug>/NOTES.md`**: what you tried, the number, and *why you think
  it did that*. Negative results are valuable to the other tracks — record them.
- Push to your branch as you go. Do not open a PR unless asked.

### What "done" looks like

A pushed branch with: working code, `metrics.json` across every input attempted,
graph JSON, comparison + progress contact sheets, promoted SVGs in
`outputs/<slug>/`, and `NOTES.md` with an honest verdict — including "this backend
does not work for X, here is the evidence." A well-evidenced negative result is a
successful track; the report explicitly wants failure modes classified.

---

## Track 1 — `flo-mat` Vector MAT/SAT

**Branch:** `claude/centerline-flo-mat` · **Slug:** `flo-mat` · Report §6.1, §18.1 — **Tier 1, rank 1**

```text
Read docs/centerline-technique-handoffs.md § Common Setup and
docs/svg-centerline-stroke-recovery-report.md §6.1 first. Follow Common Setup's
environment, corpus, metrics, graph-model, branch, directory, contact-sheet and
working rules exactly. Your slug is `flo-mat`; branch claude/centerline-flo-mat.

BACKEND: flo-mat — analytical Medial Axis Transform + Scale Axis Transform
computed directly over closed line/quadratic/cubic Bezier loops. npm, MIT, v4.1.0.

WHY IT IS RANKED FIRST: it is the only library found that combines the right
geometry model (Euclidean MAT), SVG-native Bezier input, JS/TS usability, and
scale-aware pruning (SAT) built in. Our inputs are ALREADY vector, so every raster
backend throws away information before it starts. flo-mat does not.

VERIFIED FOR YOU — read this, it will save you an hour:
  - flo-mat@4.1.0 installs clean (`npm install flo-mat`) and `require()` works.
  - THE REPORT'S §6.1 EXAMPLE IS STALE: there is no `getCurveToNext` export in
    v4.1.0. The real function is `getMatCurveToNext(node)`. Related exports that
    do exist: findMats, getPathsFromStr, traverseEdges, toScaleAxis, isTerminating,
    getBranches, getBranchBeziers, getMatCurveBetween, getMatCurvesBetween,
    beziersToSvgPathStr, loopFromBeziers.
  - Smoke test that PASSES today — a round-capped horizontal capsule, width 20,
    true centerline (50,100)->(250,100):
      d = 'M 50 90 L 250 90 A 10 10 0 0 1 250 110 L 50 110 A 10 10 0 0 1 50 90 Z'
      getPathsFromStr(d) -> 1 loop; findMats(loops, 3) -> 1 mat;
      traverseEdges + getMatCurveToNext -> 1 curve: [[60,100],[240,100]]
  - NOTE WHAT THAT RESULT MEANS: the MAT is correct but INSET BY ONE CAP RADIUS
    at each end (60 not 50, 240 not 250). This is exactly report §2.3 "caps
    materially affect the medial axis". Cap extension is therefore your first
    required post-step, not an edge case — extend each terminal branch outward
    along its tangent by the local radius. The incumbent pipeline solves the same
    problem with --calibrate-caps; see docs/current-attempt-handoff.md.

WHAT TO BUILD:
1. Normalize SVG geometry first (§9.2): resolve transforms, flatten nested groups,
   convert shapes to paths, split subpaths into closed loops, get winding right for
   holes. svg-path-commander@2.3.1 (§7.2) is on npm and is the report's pick.
   Getting this stage wrong will look like a flo-mat failure — verify by
   re-rendering your normalized geometry and diffing it against the original
   BEFORE you run any MAT.
2. Run the synthetic corpus (Common Setup) through findMats. Report §6.1 names the
   exact high-risk cases: round/butt/square caps, 90-degree and acute joins,
   C curve, loop, unioned X crossing, T junction, near-touching parallels, noisy
   boundary. This is the go/no-go for the whole track — run it early.
3. Extract the MAT graph into the common graph model, with radius per node (flo-mat
   carries it — that is the "T" in MAT, and Track 8 needs it).
4. Compare raw MAT against toScaleAxis(mat, s) for a sweep of s (the report's
   example uses 1.5). SAT is the built-in pruning; find where it helps and where it
   eats real detail. Do NOT hand-roll pruning — that is Track 8.
5. Cap extension (above), then emit stroked paths and score.

FIRST TARGET: the synthetic capsule and cap/join cases, then
inputs/house-wide.svg (11 paths, long clean strokes), then the ladder.

WATCH FOR: the report's stated primary risk is behavior at ends and merged
intersections. Also expect trouble with the boolean-unioned X crossing (case 14) —
a degree-4 MAT node is ambiguous between "two crossing strokes" and "one four-way
junction", and flo-mat will not decide for you. Record the failure, tag it
`crossing ambiguity`, and leave the decision to Track 8.

SUCCESS: an evidenced verdict on the report's top-ranked backend, with the
synthetic corpus results as the core evidence, plus scores on as much of the real
ladder as you reach. If flo-mat is as good as the report expects, this becomes the
production vector backend, so the quality of your graph JSON matters a lot.
```

---

## Track 2 — AutoTrace Centerline Baseline

**Branch:** `claude/centerline-autotrace` · **Slug:** `autotrace` · Report §6.2, §18.2 — **Tier 1, rank 2**

```text
Read docs/centerline-technique-handoffs.md § Common Setup and
docs/svg-centerline-stroke-recovery-report.md §6.2 first. Follow Common Setup's
environment, corpus, metrics, graph-model, branch, directory, contact-sheet and
working rules exactly. Your slug is `autotrace`; branch claude/centerline-autotrace.

BACKEND: AutoTrace `-centerline` — rasterize, then get SVG centerline paths from
one command. CLI + C library, mature.

WHY IT MATTERS: the report calls it the best zero-custom-code baseline and says to
"keep it in the evaluation even if it does not become the production
architecture." Its job is to tell every other track how much their complexity is
actually buying. A backend that cannot beat one shell command is not worth
shipping.

PRIOR RESULT, AND WHY IT IS NOT THE LAST WORD: autotrace centerline was already
tried here (docs/current-attempt-handoff.md) and scored badly — dinosaur 3.10%,
landscape 15.61% raw; best fixed-width sweep 0.17% and 1.79%. But read the
diagnosis: "raw autotrace centerline output did not preserve usable stroke
widths." The GEOMETRY may have been fine and the WIDTH was the failure — and that
test only ever tried ONE global fixed width per drawing. That is a weak test.
Your job is to run the strong version of it.

GETTING THE TOOL — do this first and timebox it hard:
  - `autotrace` has NO apt candidate on this image (verified: "Package 'autotrace'
    has no installation candidate"). You must build from source
    (github.com/autotrace/autotrace — autotools, needs imagemagick/glib dev
    headers), or find a prebuilt binary.
  - `apt-get install -y potrace` DOES work, but potrace is outline-only (§8.1) and
    is NOT a centerline tool — do not substitute it and call it a result.
  - If the build defeats you after a bounded effort, say so plainly, record the
    blocker, and pivot to delivering the width-recovery post-pass (below) against
    the previously-recorded autotrace numbers plus whatever tracer you can run.
    Do not let a build fight consume the session.
  - LICENSING (§6.2): the CLI is GPL, the library LGPL. Note which you use — it
    constrains productionization, and the report flags this deliberately.

WHAT TO BUILD:
1. A uniform adapter: input SVG -> deterministic raster (resvg, §7.1/§15) ->
   autotrace -centerline -> centerline paths mapped back into the ORIGINAL SVG
   coordinate space. The coordinate/scale round-trip is fiddly and is the most
   common source of misleadingly bad scores. Verify it by overlaying traced
   centerlines on the source fill and LOOKING at it before you measure anything.
2. THE ACTUAL NEW IDEA — width recovery: compute the Euclidean distance transform
   of the source filled mask, sample it along each traced centerline, and take a
   robust per-path statistic (plus optionally a per-vertex profile). Per-path width
   measured from the source, instead of one global guess for the whole drawing.
   This is what the prior evaluation never did.
3. Sweep raster resolution (§12.3 asks for several) and autotrace's own parameters
   — corner threshold, error threshold, filter iterations, despeckle — but only
   AFTER width recovery is in, since the earlier evaluation conflated the two.
4. Emit the common graph model so results are comparable with the other tracks.

FIRST TARGET: inputs/house-wide.svg to prove the adapter and the coordinate
round-trip, then re-run inputs/dinosaur-wide.svg and inputs/landscape-square.svg to
compare directly against the recorded prior numbers. Beating 0.17% / 1.79% is your
bar; beating the incumbent's 0.02% / 0.73% is the stretch goal.

WATCH FOR: some tracers emit centerlines for thin structures but outlines for thick
ones, silently mixing both in one file. Detect and report that rather than
measuring a mixed result. Also tag `raster quantization` failures — resolution
dependence is this backend's structural weakness and quantifying it is a genuine
contribution.

SUCCESS: a defensible number that every other track measures itself against, plus
a clear verdict on whether off-the-shelf tracing plus our own width recovery is
competitive. "No, and here are the numbers and crops" is a fully successful result.
```

---

## Track 3 — scikit-image `medial_axis` + Skan + fit-curve

**Branch:** `claude/centerline-skimage-skan` · **Slug:** `skimage-skan` · Report §6.5, §6.7, §7.4, §18.3 — **Tier 1, rank 3**

```text
Read docs/centerline-technique-handoffs.md § Common Setup and
docs/svg-centerline-stroke-recovery-report.md §6.5, §6.7, §7.4 first. Follow
Common Setup's environment, corpus, metrics, graph-model, branch, directory,
contact-sheet and working rules exactly. Your slug is `skimage-skan`; branch
claude/centerline-skimage-skan.

BACKEND: the report's "best foundation for a sophisticated raster backend" —
skimage.morphology.medial_axis(..., return_distance=True) for skeleton + local
radius, Skan to turn the skeleton into a real graph, fit-curve/Paper.js to fit
clean Beziers at the end.

WHY THIS BEATS PLAIN THINNING: `return_distance=True` is the whole point (§6.5).
It hands you the local stroke radius at every skeleton pixel for free. That single
signal is what makes width-aware pruning (§10) possible — pruning on branch length
alone removes real detail and keeps ugly artifacts, while pruning on
`L / (2 * R_med)` (branch length in units of local stroke width) is scale-free and
actually works. Ordinary thinning (Track 6) cannot do this.

RELATIONSHIP TO THE INCUMBENT: src/convert_filled_svg_to_stroked_lines.py already
does raster + Zhang-Suen thinning + a hand-rolled tracer, and scores 0.02% /
0.73%. You are NOT rebuilding it. The differences that justify this track are:
(a) true Euclidean medial axis instead of morphological thinning, (b) Skan's
proper graph layer instead of a bespoke tracer, (c) a retained distance field
feeding principled pruning, (d) Bezier output instead of dense polylines. Read the
incumbent first so you inherit its hard-won lessons (cap calibration, element-mode
processing) instead of rediscovering them.

WHAT TO BUILD:
1. Deterministic rasterization at high resolution (resvg, §7.1/§15 — determinism
   matters because your scores must be reproducible). Process each filled element
   separately; the incumbent learned the hard way that merging same-colour elements
   wrecks the landscape image.
2. medial_axis(mask, return_distance=True). Keep BOTH outputs. Compare against
   skeletonize() on the same masks so you can state what the Euclidean version buys.
3. Skan (§6.7) -> sparse graph, branches, coordinates. Map it straight into the
   common graph model with radius per node from the distance field. Skan's
   `summarize()` gives you branch types and lengths nearly for free.
4. Bezier fitting with fit-curve@0.2.0 (npm, Schneider fitting) or Paper.js
   simplify (§7.3, §7.4). Detect genuine corners BEFORE fitting and keep them as C0
   breaks — over-smoothing sharp pen corners is this stage's classic failure and
   the sun image will punish it immediately.
5. Report path complexity and file size alongside geometry error; §11 says prefer
   the simpler graph when geometry error is comparable, and Bezier output should
   win big here.

FIRST TARGET: synthetic corpus cases 1-12 (the medial axis of a known capsule
should BE the known centerline — if it is not, your rasterization or scale mapping
is wrong, and you want to find that on a shape you can verify by eye). Then
inputs/house-wide.svg, then inputs/dinosaur-wide.svg to compare head-to-head with
the incumbent's 0.02%.

WATCH FOR: raster medial axis is famously noisy — every tiny boundary bump spawns a
branch (§10). Resist hand-tuning thresholds to hide it; capture the radius data
cleanly and let Track 8 do principled pruning. Also expect the classic raster
`disconnected skeleton` and `raster quantization` failures at low resolution; sweep
resolution and report the sensitivity.

SUCCESS: a clean, well-instrumented raster backend emitting a proper graph with
radii — the most likely production fallback if flo-mat (Track 1) proves fragile.
Quality of the graph JSON and the radius data matters more here than the headline
pixel score, because Track 8 builds directly on it.
```

---

## Track 4 — PyGeoOps + fitodic Polygon-Voronoi Centerlines

**Branch:** `claude/centerline-polygon-voronoi` · **Slug:** `polygon-voronoi` · Report §6.3, §6.4, §18.4, §18.9 — **Tier 1 rank 4 + Tier 3 rank 9**

```text
Read docs/centerline-technique-handoffs.md § Common Setup and
docs/svg-centerline-stroke-recovery-report.md §6.3, §6.4, §4.2 first. Follow
Common Setup's environment, corpus, metrics, graph-model, branch, directory,
contact-sheet and working rules exactly. Your slug is `polygon-voronoi`; branch
claude/centerline-polygon-voronoi.

BACKENDS: two Python polygon-centerline APIs, evaluated head-to-head because they
share an input model and a failure surface:
  - pygeoops.centerline (Tier 1 rank 4) — the report's "best high-level Python
    polygon-centerline API found", with densification, branch filtering,
    simplification, and width-RELATIVE automatic parameters already exposed.
  - centerline.geometry.Centerline by fitodic (Tier 3 rank 9) — Voronoi over
    polygons, Shapely API plus a create_centerlines CLI. GIS-oriented, useful as
    an independent baseline.

Both verified installable: `pip3 install pygeoops centerline`.

WHY THIS TRACK: it is the fastest route to a real number. Neither library needs a
custom graph layer to produce output, and PyGeoOps' built-in width-relative branch
filtering is a ready-made comparison point for the pruning logic Track 8 is
building from scratch. If PyGeoOps' automatic parameters get close to hand-tuned
pruning, that is a significant finding for the whole project.

THE STRUCTURAL LIMITATION, STATED UP FRONT (§6.3, §4.2): neither is SVG-native.
Beziers must be flattened to polygons first, so you inherit a flattening-tolerance
parameter that trades boundary fidelity against Voronoi noise — too coarse and you
lose the shape, too fine and you get a hairball of spurious branches. Treat that
tolerance as a first-class swept parameter, not a constant. Voronoi centerlines are
also approximations built from boundary SAMPLE POINTS rather than the true
continuous medial axis, so expect systematic deviation on curved strokes. Quantify
it on the synthetic arcs rather than asserting it.

WHAT TO BUILD:
1. SVG -> Shapely polygon conversion: parse paths (svgelements is installed and
   handles the SVG spec well), flatten curves at a configurable tolerance, resolve
   holes and winding, build valid Shapely geometry. Validate with
   `.is_valid`/`buffer(0)` — invalid polygons are the #1 cause of garbage Voronoi
   output, and the failure is silent.
2. Run BOTH libraries over the same polygons through one interface so the
   comparison is apples-to-apples. Expose each library's own knobs (PyGeoOps:
   densification, min branch length, simplification; fitodic: interpolation
   distance).
3. Sweep flattening tolerance x library knobs on the synthetic corpus and report a
   2-D result surface, not a single number.
4. Emit the common graph model. Radius is NOT free here the way it is with a true
   MAT — recover it by sampling distance-to-boundary from the Shapely polygon along
   the centerline, and say clearly that it is derived rather than native.

FIRST TARGET: synthetic cases 1-6 (line, diagonal, arc, S, U, loop) — the pure
geometry cases where a Voronoi centerline should be near-exact and any error is
attributable to flattening. Then case 17 (almost-touching parallel lines), which is
where Voronoi approaches classically produce spurious connecting branches. Then
inputs/house-wide.svg and up the ladder.

WATCH FOR: GIS libraries assume road/river-shaped polygons and can behave oddly on
artistic strokes with round caps — the report flags exactly this (§6.3
"Disadvantages for SVG artwork"). Also watch runtime on dense drawings; Voronoi over
a finely densified boundary gets expensive fast (§16), so record seconds-per-element.

SUCCESS: two more independent baselines on the board with a clear statement of
where polygon-Voronoi centerlines are and are not adequate for artistic strokes —
plus a verdict on whether PyGeoOps' automatic width-relative filtering is
competitive with bespoke pruning, which directly informs Track 8.
```

---

## Track 5 — Tegaki Generator, Adapted

**Branch:** `claude/centerline-tegaki` · **Slug:** `tegaki` · Report §6.9, §18.5 — **Tier 2, rank 5**

```text
Read docs/centerline-technique-handoffs.md § Common Setup and
docs/svg-centerline-stroke-recovery-report.md §6.9 first. Follow Common Setup's
environment, corpus, metrics, graph-model, branch, directory, contact-sheet and
working rules exactly. Your slug is `tegaki`; branch claude/centerline-tegaki.

SUBJECT: Tegaki (github.com/gkurt/tegaki) — a TypeScript project whose internal
generator converts font outlines to animated strokes by flattening, rasterizing,
skeletonizing, tracing, pruning, estimating width, and ORDERING strokes.

WHY THE REPORT SINGLES IT OUT: it is "an unusually relevant full reference
pipeline" — the only found implementation that solves the ENTIRE problem we have,
end to end, including the parts every other track defers. It implements several
skeletonizers side by side (thinning, distance-transform medial axis, and Voronoi
medial axis), which is a ready-made internal comparison, and it does stroke
ordering and width estimation, which nothing else on the list does.

PACKAGING CAVEAT (§6.9, and this shapes the whole track): the generator is an
INTERNAL CLI/library inside a monorepo, not a published npm dependency. The report
is explicit that it is best treated as code to STUDY, VENDOR, OR ADAPT — not
`npm install`ed. Plan for reading and porting, and check its license and honour it
in anything you vendor (report says MIT — verify against the repo itself).

WHAT TO BUILD:
1. Fetch and read the generator. Before writing any code, produce a written map in
   NOTES.md of its pipeline stages and the exact algorithm at each: how it
   flattens, at what resolution it rasterizes, which skeletonizers it offers, how
   it traces, HOW IT PRUNES, how it estimates width, and how it orders strokes.
   That map is a deliverable on its own and is directly useful to Tracks 3, 6 and
   8 — write it for them, not just for you.
2. Extract the parts that generalize. Priorities in order:
   a. Its PRUNING heuristics — the report calls pruning the most important custom
      logic (§10) and this is a working implementation of it. Feed what you learn
      straight to Track 8.
   b. Its WIDTH ESTIMATION — nothing else on the list does this natively.
   c. Its STROKE ORDERING/direction — report §9.8, and Experiment 5. This is the
      one place stroke semantics already exist in working code.
   d. Its multiple skeletonizers, as a cheap internal A/B.
3. Adapt it to our input: it consumes font outlines internally, so the work is
   giving it arbitrary SVG filled paths. Reuse the normalization stage from Track 1
   if it has pushed (svg-path-commander), otherwise write a minimal one.
4. Emit the common graph model, plus stroke order/direction metadata — you will
   likely be the only track producing the latter, so define the field clearly and
   document it in NOTES.md.

FIRST TARGET: get ANY output from the adapted generator on a single synthetic
capsule, then inputs/house-wide.svg. Do not attempt full fidelity to Tegaki's
behaviour — the goal is to learn whether its approach transfers to artistic pen
strokes, not to port a monorepo.

WATCH FOR: this track has the highest ratio of reading to writing, and the highest
risk of sinking the session into build tooling (Bun, monorepo wiring, TS config).
Timebox the build hard. If it will not run, the written algorithm map plus a
from-scratch port of just the pruning and width-estimation logic is STILL a
successful outcome — say so and deliver that.

SUCCESS: the algorithm map, plus at least one Tegaki-derived technique ported and
measured against a track that lacks it. Stroke ordering is the stretch goal and
would be genuinely novel for this project.
```

---

## Track 6 — OpenCV Thinning + `skeleton-tracing`

**Branch:** `claude/centerline-opencv-tracing` · **Slug:** `opencv-tracing` · Report §6.6, §6.8, §18.6, §18.10 — **Tier 2 rank 6 + Tier 3 rank 10**

```text
Read docs/centerline-technique-handoffs.md § Common Setup and
docs/svg-centerline-stroke-recovery-report.md §6.6, §6.8, §4.4 first. Follow
Common Setup's environment, corpus, metrics, graph-model, branch, directory,
contact-sheet and working rules exactly. Your slug is `opencv-tracing`; branch
claude/centerline-opencv-tracing.

BACKEND: the speed-and-portability path — cv2.ximgproc.thinning (Zhang-Suen /
Guo-Hall, Apache-2.0) for the skeleton, and LingDong-'s skeleton-tracing to turn
the 1-pixel skeleton into polylines.

WHY IT IS ITS OWN TRACK RATHER THAN A VARIANT OF TRACK 3: the report positions
these as PRODUCTION primitives, not research ones. Two properties nothing else on
the list has: (a) OpenCV thinning is very fast and is already present in most
production stacks; (b) skeleton-tracing has implementations in JavaScript, WASM,
Python, C/C++, Rust, Swift, C#, Go and Java — so this is the only pipeline that
ports to the browser or another runtime unchanged. If the project ever needs
client-side or cross-language centerline extraction, this is the candidate. Your
job is to find out what that portability COSTS in quality.

THE KNOWN TRADEOFF, STATED UP FRONT (§4.4, §6.6): morphological thinning gives you
NO distance field. You get a 1-pixel skeleton and nothing else, so width-aware
pruning (§10) is not available natively and you must recover radius separately
(sample a distance transform along the traced skeleton — cheap, but derived rather
than native). Thinning is also more prone to staircase artifacts and to spurious
short branches at junctions than the Euclidean medial axis. Track 3 is the
head-to-head comparison; coordinate with its NOTES.md so the two are measured on
identical masks.

GETTING THE TOOLS:
  - `pip3 install opencv-contrib-python-headless` — VERIFIED available. You need
    the CONTRIB build; ximgproc is not in the base opencv package.
  - skeleton-tracing is NOT on npm (verified). Vendor it from
    github.com/LingDong-/skeleton-tracing and note its MIT license. Pick the
    Python or JS binding; if you pick JS, you get the portability story for free.

WHAT TO BUILD:
1. Deterministic rasterization (resvg, §15) per filled element. Use the SAME
   rasterization settings as Track 3 so the comparison is honest.
2. cv2.ximgproc.thinning with BOTH THINNING_ZHANGSUEN and THINNING_GUOHALL, and
   report the difference — the report names both and nobody here has compared them.
3. skeleton-tracing to polylines. Compare its output against the incumbent's
   hand-rolled tracer (src/convert_filled_svg_to_stroked_lines.py) on the same
   skeletons — if a vendored library matches a bespoke tracer, that is worth
   knowing and simplifies the architecture.
4. Recover radius by sampling a distance transform along the polylines, so you can
   still emit the common graph model with radius populated. Flag in your JSON that
   radius is derived, not native.
5. Measure RUNTIME carefully and report it prominently (§16). Speed is this track's
   entire value proposition — if it is not meaningfully faster than Track 3, say so,
   because that removes its reason to exist.

FIRST TARGET: synthetic corpus cases 1-6 and 13-16 (the junction cases, where
thinning's spurious-branch behaviour shows up most clearly and is comparable
against Track 3's medial axis on identical inputs). Then inputs/house-wide.svg,
then inputs/dinosaur-wide.svg.

WATCH FOR: thinning artifacts at junctions and at stroke ends (thinning pulls back
from round caps differently than the medial axis does) — tag them `join artifact`,
`cap artifact`, and `outline noise branch` so the counts are directly comparable
with Track 3's.

SUCCESS: a quantified quality-vs-speed-vs-portability tradeoff against Track 3 on
identical rasterizations, plus a Zhang-Suen vs Guo-Hall verdict. This track wins by
being decisively measured, not by topping the leaderboard.
```

---

## Track 7 — Native Geometry Engines: Boost.Polygon Voronoi, CGAL, PostGIS

**Branch:** `claude/centerline-native-geometry` · **Slug:** `native-geometry` · Report §6.10–6.12, §18.8, §18.11, §18.12 — **Tier 2 rank 8 + Tier 3 ranks 11–12**

```text
Read docs/centerline-technique-handoffs.md § Common Setup and
docs/svg-centerline-stroke-recovery-report.md §6.10, §6.11, §6.12, §4.5 first.
Follow Common Setup's environment, corpus, metrics, graph-model, branch, directory,
contact-sheet and working rules exactly. Your slug is `native-geometry`; branch
claude/centerline-native-geometry.

SUBJECT: the three heavyweight geometry engines the report rates as powerful but
not first choices. Bundled into one track because they share a question — is a
lower-level, numerically-controlled geometry kernel worth the integration cost? —
and because two of them are expected to produce the WRONG geometry, which is worth
establishing cheaply rather than expensively.

PRIORITIES — spend your time in this order, and do not let the later ones eat the
first:

1. BOOST.POLYGON VORONOI (§6.10, Tier 2 rank 8) — THE MAIN EVENT, ~70% of the
   session. A C++ point/segment Voronoi kernel. Unlike the polygon-Voronoi
   libraries in Track 4, it accepts SEGMENT sites rather than only sampled points,
   which means the Voronoi diagram of a polygon's EDGES is much closer to the true
   medial axis with far less densification noise. This is the report's route to
   "a fully controlled native vector implementation if the higher-level libraries
   prove inadequate", and it is the only track that can give exact numerical
   control. Build a small C++ tool: read flattened polygon edges (JSON or a simple
   text format from a Python/Node front-end), construct the segment Voronoi, filter
   to cells interior to the polygon, emit the medial-axis graph as the common graph
   model. Boost is apt-installable (`apt-get install -y libboost-dev`); verify
   before committing, and if it is unavailable, say so and reprioritize.

2. CGAL STRAIGHT SKELETON 2 (§6.12, Tier 3 rank 12) — BOUNDED EXPERIMENT, ~20%.
   The report is clear (§4.5, §3) that a straight skeleton is NOT the Euclidean
   medial axis: it is built from angular bisectors, so it produces straight-line
   segments and will NOT curve correctly through a curved stroke, and it handles
   round caps quite differently. Expect it to be wrong for our purpose. The value
   is CHEAPLY CONFIRMING that with real numbers on the synthetic corpus rather than
   leaving it as an open question. Run cases 1-6 plus a cap case, show the geometry
   is systematically wrong, and stop. Do not invest in productionizing it.

3. POSTGIS CG_ApproximateMedialAxis (§6.11, Tier 3 rank 11) — OPTIONAL, ~10%,
   ONLY if the first two are done. The report calls it a convenient SQL surface but
   "too heavy and too straight-skeleton-oriented to recommend solely for this
   feature", and it shares CGAL's wrong-geometry problem via SFCGAL. Standing up
   PostGIS to confirm a known conclusion is a poor use of the session. If you skip
   it, say so explicitly in NOTES.md and cite the reasoning — a documented, reasoned
   skip is a valid outcome.

WHAT TO BUILD: for whichever engines you run, the same shape as every other track —
SVG -> flattened polygon (reuse Track 4's converter if it has pushed) -> engine ->
common graph model -> re-stroke -> metrics. Keep the front-end shared across all
three so the comparison is clean.

FIRST TARGET: synthetic cases 1-6, then the cap cases (7-9). Those alone will
settle the straight-skeleton question. Then inputs/house-wide.svg with Boost, and
up the ladder as far as time allows.

WATCH FOR: build tooling is the real risk here — C++ dependency wrangling can
consume the whole session for zero output. Timebox each build. Get ONE end-to-end
result from Boost on ONE synthetic shape before adding anything. Report §15 also
notes native kernels have their own determinism characteristics; record library
versions and any tolerance settings so results are reproducible.

SUCCESS: a real Boost.Polygon segment-Voronoi medial axis on at least the synthetic
corpus, with a clear statement of whether the numerical control justifies the
integration cost — plus a cheap, evidenced burial of the straight-skeleton
approaches so nobody spends a session on them later. Negative results delivered
cheaply are the point of this track.
```

---

## Track 8 — Width-Aware Pruning, Re-Stroke Scoring, and the Common Graph Layer

**Branch:** `claude/centerline-pruning-scoring` · **Slug:** `pruning-scoring` · Report §10, §11, §13 (Exp 3–4), §19 — **the shared semantic layer**

```text
Read docs/centerline-technique-handoffs.md § Common Setup and
docs/svg-centerline-stroke-recovery-report.md §10, §11, §13 and §19 first. Follow
Common Setup's environment, corpus, metrics, graph-model, branch, directory,
contact-sheet and working rules exactly. Your slug is `pruning-scoring`; branch
claude/centerline-pruning-scoring.

SUBJECT: not a backend — the layer every backend needs. The report calls
width-aware pruning "probably the most important custom logic" (§10) and
reconstruction-based validation "the single most valuable quality technique to
add" (§11). §19 says the most important architectural choice in the whole system is
the COMMON GRAPH LAYER, because once vector and raster extractors emit the same
nodes/edges/radius metadata, every hard semantic operation — pruning, branch
pairing, stroke grouping, ordering, validation — is shared and testable
independently of extraction.

You are building that layer. Tracks 1-7 are your data sources; you are their
scoring function. Start immediately — do not wait for them.

WHY IT MUST BE SEPARATE: a raw medial axis is hypersensitive to tiny boundary
irregularities, and generic length-based branch removal either deletes real detail
or keeps ugly artifacts. Every backend has this problem identically. Solving it
once, correctly, against a defined graph interface is worth more than seven
hand-tuned threshold sets.

WHAT TO BUILD:
1. THE GRAPH LIBRARY. Implement the §13 CenterlineNode/CenterlineEdge model as a
   real library with load/save/validate, plus graph ops (terminal branch
   enumeration, junction detection, branch merging, connected components). Publish
   the schema early and loudly in debug/pruning-scoring/NOTES.md — the other seven
   tracks are writing against it, so schema churn is expensive. Ship a validator
   they can run.

2. WIDTH-AWARE PRUNING (§10.1). For each terminal branch compute:
       L = arc length;  R_med = median local radius;
       R_parent = radius near the junction;  dR = radius variation;
       theta = tangent relationship to the parent path
   and the NORMALIZED features that make thresholds scale-free:
       L / (2 * R_med)        # length in units of local stroke width
       R_med / R_global       # branch scale vs dominant stroke
       std(R) / mean(R)       # width consistency
   The key insight: a spur 0.15 stroke widths long is categorically different from
   a branch 3 stroke widths long, regardless of absolute SVG units. Absolute
   thresholds are why previous attempts needed per-image tuning.

3. RE-STROKE SCORING (§11). Given centerline C and width w, generate
   S_reconstructed = stroke_to_fill(C, w) and compare against S_original:
   IoU, symmetric-difference area, boundary distance (median AND P95 — never max),
   centerline complexity, width error. Do this in VECTOR space where you can
   (Shapely buffer, or an SVG stroke-to-path conversion) and cross-check against
   the raster pixel-diff from src/compare.js. Where vector and raster scoring
   disagree, investigate and write it up — the other tracks are trusting these
   numbers.

4. PRUNING AS MODEL SELECTION (§10.2) — the most valuable single deliverable.
   Instead of one hand-tuned threshold, generate candidate skeletons at SEVERAL
   pruning strengths, re-stroke each, and select the Pareto-optimal result
   balancing reconstruction fidelity, total centerline length, branch count,
   control-point count, and width consistency. Then §13 Experiment 4: select the
   SIMPLEST graph that stays within a chosen reconstruction tolerance. This turns a
   fiddly hand-tuned constant into an automatic, defensible choice, and it is what
   lets every backend be evaluated at ITS OWN best setting rather than at whatever
   threshold someone happened to pick.

5. THE SHARED HARNESS. Since you own scoring, own the leaderboard too: a command
   that ingests every track's graph JSON from its branch and emits one comparison
   table plus a cross-backend contact sheet (same image, one column per backend).
   That artifact is how this whole parallel effort gets read at the end.

6. NOT YET: branch pairing, stroke grouping, direction and order are §13
   Experiment 5 and explicitly come AFTER centerline geometry is stable. Build the
   interfaces so they can slot in; do not implement them unless everything above is
   solid. (Track 5 may bring stroke-ordering logic from Tegaki — coordinate.)

FIRST TARGET: you need input graphs before any backend has pushed, so bootstrap
from the incumbent — run src/convert_filled_svg_to_stroked_lines.py on
inputs/house-wide.svg and convert its output into the graph model. That gives you a
real graph on day one, and its known scores (0.02% dinosaur, 0.73% landscape) are a
control your scoring must reproduce. Then pull in whichever track has pushed first.
Validate pruning on synthetic case 20 (noisy vectorized boundary) — it exists
precisely to generate spurious branches with a known-correct answer.

WATCH FOR: over-pruning that scores well on IoU while deleting real strokes — IoU
is forgiving of small missing marks. Weight complexity metrics against it and
always look at the render. Also beware fitting your thresholds to the ten real
inputs; the synthetic corpus is your held-out check.

SUCCESS: a documented, versioned graph schema the other tracks actually write to; a
re-stroke scorer everyone trusts; automatic Pareto pruning that beats hand-tuned
thresholds on at least two backends; and a cross-backend leaderboard. If this track
works, the project's answer stops depending on which backend anyone happened to
tune hardest.
```

---

## Coordination notes

The tracks are deliberately independent and none should block on another. Three
couplings are worth knowing about:

- **Track 8 is everyone's scoring function.** It publishes the graph schema and the
  re-stroke scorer. Every other track emits the graph model regardless of whether
  Track 8 has pushed yet — that is what makes the results add up rather than
  becoming seven incomparable experiments.
- **Tracks 3 and 6 are a controlled comparison** (Euclidean medial axis vs
  morphological thinning). They must use identical rasterization settings for the
  comparison to mean anything; whichever pushes first records its settings in
  `NOTES.md` and the other matches them.
- **Track 5 (Tegaki) produces reusable algorithm knowledge** — its pruning, width
  estimation, and stroke ordering are the only working reference implementations of
  those stages we have found. Its written algorithm map is a deliverable for
  Tracks 3, 6, and 8, not just for itself.

Two report conclusions worth carrying into every session: the final architecture is
expected to be **hybrid** (§19 — flo-mat when it produces a clean vector skeleton,
raster fallback when MAT topology scores poorly, choosing per shape by
reconstruction metrics), so a backend that wins on *some* shapes is a success, not a
loser. And the report's §8 warning applies throughout: Potrace, VTracer and
ImageTracer solve the wrong problem — they trace boundaries, not centerlines. Do not
let one drift into an evaluation as if it were a candidate.
