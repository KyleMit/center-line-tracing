# Track 2 — AutoTrace `-centerline` baseline

Slug `autotrace` · branch `claude/centerline-autotrace-qtkuxm` · report §6.2, §18.2

**Verdict up front:** off-the-shelf `autotrace -centerline` **plus our own
width recovery is competitive with the incumbent** — `dinosaur-wide` 0.03% vs
the incumbent's 0.02%, and `landscape-square` **0.39% vs the incumbent's
0.73%**. Both clear the prior autotrace numbers (0.17% / 1.79%) by roughly 5×.

The prior evaluation's diagnosis ("raw autotrace centerline output did not
preserve usable stroke widths") was correct about the symptom and wrong about
the implication. The **geometry was always fine**; the failures were feeding
autotrace an antialiased colour raster instead of a binary mask, and guessing
one global width for a whole drawing.

Full numbers in [Results](#results--the-full-ladder), reasoning in
[Verdict](#verdict).

## Getting the tool

`autotrace` has no apt candidate on this image, so it was built from source:

```bash
git clone --depth 1 https://github.com/autotrace/autotrace
apt-get install -y autoconf automake libtool pkg-config libglib2.0-dev \
                   libpng-dev libexif-dev intltool gettext autopoint \
                   libmagickcore-dev libmagickwand-dev
cd autotrace && sh autogen.sh && ./configure --prefix=/usr/local --without-pstoedit && make -j4
# -> ./autotrace, "AutoTrace version 0.40.0"
```

Three things cost time and are worth writing down:

1. `autogen.sh` only runs `autoreconf`; it does **not** run `configure`.
2. `autopoint` is a separate apt package from `gettext`; without it `autogen.sh`
   dies at `autopoint: not found`.
3. `configure` hard-fails on a missing `pstoedit >= 3.32.0`. `--without-pstoedit`
   is required and costs nothing (it only affects extra output formats).

Total build time was a few minutes. This is not a serious barrier.

### Licensing (report §6.2)

**The report is out of date here, in our favour.** §6.2 says "CLI GPL-2.0;
library LGPL-2.1". In the version actually built (0.40.0), `src/main.c` — the
CLI entry point — carries `SPDX-License-Identifier: LGPL-2.1-or-later`, as does
the SVG writer `src/output-svg.c`. The repo still ships both `COPYING` (GPL) and
`COPYING.LIB` (LGPL), so **this should be confirmed with counsel before
shipping**, but the "the CLI is GPL so we can only shell out, never link"
constraint the report assumes may no longer apply.

This track shells out to the CLI binary and does not link `libautotrace`, which
is the conservative choice under either reading.

## What the pipeline does

```
input SVG
  -> enumerate filled elements (inherited fill, accumulated ancestor transforms)
  -> per element: crop to its bbox, render BLACK ON TRANSPARENT via resvg at
     `scale` px per user unit, threshold alpha >= 128  ->  binary mask
  -> write a 1-bit PBM (no palette, no antialiasing) and run
     `autotrace -centerline -background-color FFFFFF -input-format pbm`
  -> parse the SVG it writes back (M/L/C only, y already flipped by its writer)
  -> map pixel coords back into ORIGINAL user space
  -> width recovery: EDT of the source mask, sampled along each traced path
  -> cap extension, then emit
     <path fill="none" stroke=<source fill> stroke-width=2r stroke-linecap="round">
```

Code in `experiments/autotrace/`: `svgio.py` (parse / sub-SVG / resvg),
`atrace.py` (run + parse autotrace), `width.py` (EDT width recovery),
`pipeline.py` (orchestration + graph model), `metrics.py`, `bench.py`,
`synth.py` (synthetic corpus), `width_ab.py` (the controlled A/B),
`sheets.py` (contact sheets), `inspect_mixed.py` (outline-vs-centerline audit).

Reproduce the promoted result:

```bash
python3 experiments/autotrace/bench.py --all --label final \
    --mode element --scale 4 --cap-extend --stat trimmed --quad --graph
```

### The coordinate round-trip

The handoff warns this is the most common source of misleadingly bad scores, so
it is isolated in one object (`svgio.Frame`) and verified visually before any
number was believed. Two things matter:

* AutoTrace's SVG writer emits `height - y`, so its output is **already
  top-down** in the same frame as the mask. No flip is needed — adding one
  silently mirrors everything.
* `resvg` fits to width, so the achieved height can differ from `round(bh*scale)`
  by a rounding unit. The frame therefore takes its scale from the pixel buffer
  that actually came back, never from the requested scale.

`debug/autotrace/hw-first-overlay.png` is the check: traced centerlines in red
over the source fill in grey, before any scoring. They sit on the strokes.

### Why the earlier evaluation saw "no usable stroke widths"

Not a width bug in autotrace — autotrace simply **does not emit widths at all**.
Its centerline output is `style="stroke:#rrggbb; fill:none;"` with no
`stroke-width`, so the SVG default of 1 user unit applies. At a raster scale of
4 on a 1662-unit-wide drawing, that renders as a hairline roughly 1/40th of the
true stroke width. The geometry was never the problem.

## The controlled A/B — was it really the width?

Yes. `experiments/autotrace/width_ab.py` holds the traced geometry **completely
fixed** and varies only how stroke width is assigned: one global width for the
whole drawing (swept over 13 values spanning the widths actually present),
versus per-path width measured from the source distance transform.

| image | per-path EDT width | best single global width | ratio | true widths present |
|---|---|---|---|---|
| `house-wide` | **0.05%** | 0.05% @ w=21.1 | 1.00× | 17.1 – 26.8 |
| `dinosaur-wide` | **0.03%** | 0.04% @ w=14.1 | 1.33× | 9.1 – 24.2 |
| `landscape-square` | **0.39%** | 1.50% @ w=21.9 | **3.85×** | 16.6 – 29.4 |

Two things to read off this table.

* Our own best-global-width number on `landscape-square` (1.50%) lands close to
  the prior evaluation's recorded best fixed-width result (1.79%). The geometry
  in the two evaluations is therefore comparable, and **the width policy really
  is what separates them**.
* The benefit of per-path width is entirely a function of how much width
  *variation* a drawing contains. `house-wide` is nearly uniform, so one global
  width is already optimal and width recovery buys exactly nothing. The gain
  appears on drawings whose strokes genuinely differ in weight.

That last point is the honest caveat on the headline: this is not a universal
3.85× — it is 1× on easy art and 3.85× on the hardest image in the set.

## Raster resolution — this backend's structural weakness, quantified

Measured on the synthetic corpus, where true centerline error is knowable
(`debug/autotrace/synthetic.json`, `experiments/autotrace/synth.py`):

| raster scale (px per user unit) | median centerline error (user units) | error expressed in raster pixels |
|---|---|---|
| 1 | 1.065 | 1.07 px |
| 2 | 0.578 | 1.16 px |
| 3 | 0.390 | 1.17 px |
| 4 | 0.317 | 1.27 px |
| 6 | 0.236 | 1.42 px |

The finding is in the third column: **autotrace's centerline error is
essentially a constant ~1.1–1.4 raster pixels, independent of resolution.**
It does not converge to the true centerline as you spend more pixels — it
converges to "about one pixel", so error in the drawing's own units is purely
a function of resolution and nothing else. Doubling the raster halves the error
and roughly quadruples the cost, forever.

That is the precise shape of the `raster quantization` failure for this
backend, and it is the structural argument for a vector-native backend: a
vector MAT has no such floor. It also means every accuracy number in this
document is really a statement about the raster budget, and should be quoted
with its scale.

Recovered stroke radius degrades the same way but far more gently — median
absolute radius error is 4.2% at scale 1, 1.7% at scale 3, and 1.0% at scale 6.
Width recovery is much more robust to coarse rasterisation than geometry is,
because the distance transform averages over the whole path.

## Results — the full ladder

Config: `--mode element --scale 4 --cap-extend --stat trimmed`, one config for
all ten images (no per-image tuning). Diff % is `src/compare.js` at 1200px, kept
verbatim for continuity with the incumbent's recorded numbers.

| image | diff % | IoU | boundary P95 (user) | strokes | src elems | runtime | reference |
|---|---|---|---|---|---|---|---|
| `house-wide` | 0.05% | 0.9613 | 1.39 | 25 | 19 | 14s | |
| `butterfly-wide` | 0.12% | 0.9494 | 1.33 | 19 | 17 | 23s | |
| `boat-tall` | 0.03% | 0.9578 | 1.08 | 28 | 20 | 17s | |
| `island-tall` | 0.06% | 0.9523 | 1.20 | 32 | 22 | 10s | |
| `balloon-tall` | 0.04% | 0.9562 | 1.21 | 47 | 24 | 14s | |
| `home-wide` | 0.03% | 0.9462 | 1.28 | 32 | 26 | 9s | |
| `house-tall` | 0.10% | 0.9518 | 1.19 | 39 | 27 | 13s | |
| `dinosaur-wide` | **0.03%** | 0.9512 | 1.89 | 52 | 29 | 29s | incumbent 0.02% · prior autotrace 0.17% / 3.10% raw |
| `landscape-square` | **0.39%** | 0.9339 | 3.30 | 92 | 17 | 57s | incumbent 0.73% · prior autotrace 1.79% / 15.61% raw |
| `sun-square` | 3.25% | 0.9028 | 4.63 | 17 | 2 | 4s | reference ~4.2% raster / ~6.3% vector |

Against the bar the handoff set:

* **Bar (beat prior autotrace 0.17% / 1.79%): cleared by 5.7× and 4.6×.**
* **Stretch goal (beat incumbent 0.02% / 0.73%): cleared on `landscape-square`
  (0.39% vs 0.73%), missed by one hundredth of a point on `dinosaur-wide`**
  (0.03% vs 0.02%). With `--stat median` instead of `trimmed`, `dinosaur-wide`
  hits 0.02% exactly — but the same swap costs `landscape-square` 0.43% vs
  0.39%. That is a genuine trade, not a tuning win, and the table above reports
  the single config rather than cherry-picking per image.
* `sun-square` at 3.25% also beats both recorded references for that image.

The incumbent needs eight tuned flags (`--trace-mode paired --tip-mode corner
--overlap-spur-max 80 --tip-spur-max 150 --calibrate-caps --stroke-scale 1.07`
and so on). This is `autotrace -centerline` plus a distance transform.

## Failure modes observed (report §13, Experiment 2 taxonomy)

| tag | where | notes |
|---|---|---|
| `raster quantization` | everywhere, structurally | ~1.1–1.4 raster px of centerline error at every scale — see the table above. The defining weakness of this backend. |
| `missing narrow segment` | `butterfly-wide`, `island-tall` (1 element each) | **two distinct causes, see below.** |
| `crossing ambiguity` | synthetic case 14 (unioned X) | 3 subpaths where 2 strokes exist, centerline P95 2.89u vs 0.53u for the same X kept as separate shapes — a **5.5× penalty for merged source elements**, exactly as report §2.5 predicts. Left for Track 8. |
| `join artifact` | synthetic case 12 (miter join) | the acute corner is split into 2 subpaths rather than traced through; P95 1.27u. |
| `excessive curve complexity` | `landscape-square` at scale 1 | 204 strokes vs 92 at scale 4 for the same drawing — coarse rasterisation fragments long strokes. |
| `cap artifact` | all free ends, before cap extension | median endpoint error 1.147u, cut to 0.280u by extending each terminal end to the mask edge and back one radius. |

### The mixed outline/centerline check — negative result

The handoff warns that some tracers emit centerlines for thin structures and
outlines for thick ones, silently mixing both. **On this corpus, autotrace does
not do that.** `experiments/autotrace/inspect_mixed.py` audits every element of
a drawing by comparing each traced subpath's median EDT against the element's
own thickness, and dumps a picture of anything it flags.

On `dinosaur-wide` the detector fires on 2 subpaths out of 29 elements. Looking
at the dump (`debug/autotrace/mixed/dinosaur-wide/e011.png`) **both are false
positives**: they are short bridging segments across the notches of a
party-hat outline, where the stroke is locally thinner than the element average,
so a whole-element thickness reference is the wrong yardstick for them (12.4px
and 11.5px against a 12.8px threshold — borderline by design). They run down the
middle of the stroke like every other traced path.

So: the failure the handoff asks about did not occur, the detector that would
have caught it exists and is checked in, and its known bias is that it should
compare against **local** thickness rather than a per-element average. Reported
rather than silently measured, as asked.

## Where the remaining error actually is

`sun-square` (3.25%) is the one image where the residual is **not** a geometry
problem. The overlay shows the traced centerlines running correctly down the
middle of every scribble stroke; the reconstruction is wrong because those
strokes **taper**, and one constant width per path cannot represent a taper.

The graph JSON measures this directly. Taking the ratio of max to min radius
along each individual path:

| drawing | median within-path max/min radius ratio |
|---|---|
| `house-wide` | 1.09× |
| `sun-square` | **2.05×** |

A path whose true radius doubles along its length is being re-stroked at one
width, which necessarily over-fills the needle ends and under-fills the belly.
This is synthetic case 19 (`19-variable-width`, the worst synthetic geometry
result at 1.08u) showing up in real artwork.

The per-vertex radius profile needed to fix it is **already recorded** in
`debug/autotrace/graphs/<image>.json` as `radiusProfile` on every edge. What is
missing is an output representation: a variable-width stroke is not expressible
as `<path stroke-width>`, and emitting it means generating a filled ribbon,
which leaves the output shape this project specified. Flagged for Track 8
rather than solved here.

## What did NOT help

Negative results, recorded because they are cheap for other tracks to re-derive
otherwise:

* **Width statistic barely matters, and the best choice is image-dependent.**
  Across `median` / `p60` / `p75` / `mean` / `trimmed`, `house-wide` sat at 0.05%
  for every single one. `trimmed` and `mean` tie at the best `landscape-square`
  value (0.39%); `median` is best on `dinosaur-wide` (0.02%). Spread across the
  whole sweep is 0.39–0.52%. Do not spend time here.
* **`--stroke-scale` fudge factors hurt.** The incumbent uses `--stroke-scale
  1.07`. Applying the same idea here made things worse at every value tried
  (0.96/0.98/1.02/1.04/1.05 all ≥ the unscaled result; 1.05 gave 0.57% against
  0.53%). That is a good sign — it means the EDT is already measuring the true
  radius rather than a biased one that needs correcting.
* **`--mode raw` (the literal one-command baseline) is not merely inaccurate,
  it is impractical.** Rasterising the whole drawing in full colour makes
  antialiasing produce ~100 distinct colour bands (verified: 100+ distinct
  stroke colours in the output of a single `house-wide` trace), and autotrace
  then traces every band. It took 130s for `house-wide` alone at scale 4 against
  14s for the entire element-wise pipeline, and produces hairline output with no
  width information (IoU 0.0000 as scored). **Binary masks are not an
  optimisation here, they are the difference between working and not working.**

### `missing narrow segment` has two different causes — one is not fixable by resolution

I initially assumed both were raster quantization. Only one is.

**Cause 1 — quantization (fixable).** At `--scale 1`, `dinosaur-wide` loses an
element that scale 2 and above recovers. Ordinary under-sampling.

**Cause 2 — degenerate medial axis (NOT fixable by resolution).** In
`butterfly-wide`, element `e004` is a solid `<circle>` — one of the two dots at
the antenna tips. A disc's medial axis is a **single point**, so there is no
centerline to trace, and autotrace returns nothing at all:

| raster scale | element radius in mask | subpaths emitted for `e004` | for its twin `e005` |
|---|---|---|---|
| 4 | 26.7px | **0** | 1 |
| 8 | 53.1px | **0** | 1 |

Doubling the resolution changes nothing, which is the proof that this is not
quantization. The two identical dots do not even behave the same way — one
yields nothing, its twin yields a degenerate stub — so autotrace's behaviour on
a disc is essentially arbitrary. This is visible in the contact sheet as the
missing antenna tips in `butterfly-wide`.

This is a real limitation of centerline tracing as a formulation, not a bug:
a filled dot is not a stroke, it is a cap with no stroke attached. The fix is a
pre-pass that detects near-circular components and emits a zero-length
round-capped stroke for them, which belongs with Track 8's semantic layer rather
than here.

## The common graph model

Every run writes `debug/autotrace/graphs/<image>.json` in the shared shape from
Common Setup §13, so Track 8 can consume this backend's output without knowing
anything about autotrace:

```json
{"nodes": [{"id": "e003/0:a", "x": 402.3, "y": 118.7, "radius": 10.9}],
 "edges": [{"id": "e003/0", "from": "e003/0:a", "to": "e003/0:b",
            "geometry": [[402.3, 118.7], ...],
            "length": 214.6, "medianRadius": 10.9,
            "radiusProfile": [10.2, 10.7, 11.1, ...],
            "sourceElementId": "e003", "closed": false, "outlineLike": false}]}
```

Two additions beyond the required interface, both of which cost nothing to
ignore:

* `radiusProfile` — 24 evenly spaced radius samples along the edge. This is what
  a variable-width re-stroke would need, and it is what proves `sun-square` is a
  width-model problem (see above).
* `outlineLike` — the outline-vs-centerline verdict, so a consumer can filter or
  audit rather than having to re-derive it.

Nodes are currently per-edge endpoints and are **not merged at junctions** —
this backend emits disconnected subpaths and topology recovery is deliberately
left to Track 8, per the "do not implement sophisticated pruning early"
instruction. Consumers that need real junction nodes should merge by proximity;
`radius` on each node gives the natural merge tolerance.

## Resolution on real artwork — more pixels is NOT monotonically better

The synthetic corpus says error falls smoothly with resolution. Real artwork
does not agree, and this was the most surprising result of the track:

| `--scale` | `house-wide` | `dinosaur-wide` | `landscape-square` | landscape strokes | landscape runtime |
|---|---|---|---|---|---|
| 1 | 0.10% | 0.07% | 0.58% | 204 | 4s |
| 2 | 0.05% | **0.02%** | 0.48% | 131 | 11s |
| 3 | 0.05% | 0.03% | 0.41% | 103 | 23s |
| 4 | 0.05% | 0.03% | **0.39%** | 92 | 44s |
| 6 | 0.05% | **0.02%** | 0.49% | 89 | 132s |
| 8 | 0.05% | **0.02%** | 0.46% | 93 | 273s |

Three things worth carrying to other tracks:

1. **`landscape-square` is best at scale 4 and gets WORSE above it** — 0.39% at
   scale 4, 0.49% at scale 6, 0.46% at scale 8, for 3× and 6× the time. The
   regression is not a one-off sample: every scale above 4 is worse than 4.
   The synthetic corpus never shows this,
   because synthetic shapes have clean boundaries. On real art a finer raster
   resolves genuine boundary irregularity, and autotrace faithfully follows it
   into the merged hatching corridors instead of averaging it away. Coarser
   rasterisation is acting as a low-pass filter, and some of that filtering is
   load-bearing.
2. **`house-wide` is converged by scale 2.** Spending 4× the pixels buys
   literally nothing (0.05% at every scale from 2 to 8). Resolution should be
   chosen per drawing from its stroke width, not set globally.
3. **Stroke count is the tell.** 204 strokes at scale 1 versus 92 at scale 4 for
   the same drawing: at low resolution autotrace fragments long strokes, and the
   `mixed outline/centerline` detector fires 75 times (against 0 at scale 4)
   because fragments are short and locally thin. Stroke count is a cheap
   proxy for "is my raster too coarse".

Runtime scales roughly with pixel count, i.e. quadratically in `--scale`
(landscape: 4s → 11s → 23s → 44s → 132s). Scale 3–4 is the sweet spot for this
corpus and there is no reason to go past it.

## Verdict

**Is off-the-shelf tracing plus our own width recovery competitive? Yes — and
that is a genuinely uncomfortable answer for the other seven tracks.**

The number every other track should measure itself against:

> **`autotrace -centerline` on per-element binary masks, with per-path stroke
> width recovered from the source distance transform and one cap-extension
> rule, scores 0.03% on `dinosaur-wide` and 0.39% on `landscape-square`.**
> (`--mode element --scale 4 --cap-extend --stat trimmed`, `src/compare.js` at
> 1200px.)

Against the targets set for this track:

| target | result |
|---|---|
| beat prior autotrace 0.17% / 1.79% | **cleared, 5.7× and 4.6×** |
| beat incumbent 0.02% / 0.73% (stretch) | **cleared on landscape** (0.39% vs 0.73%); dinosaur 0.03% vs 0.02% |

The honest framing of the whole track: **the prior evaluation was not wrong
about autotrace, it was wrong about which half of the problem was broken.**
Its diagnosis said "raw autotrace centerline output did not preserve usable
stroke widths". True — autotrace emits no widths whatsoever. But the conclusion
drawn from it, that autotrace was therefore a weak backend, does not follow. The
geometry was good the whole time. Two changes recover it:

1. feed binary masks, not antialiased colour rasters (this is the difference
   between working and not working, not a tuning knob);
2. measure width per path from the source instead of guessing one number for the
   whole drawing (worth up to 3.85× on drawings with real width variation, and
   nothing at all on drawings without).

### What this means for the other tracks

* **A backend that cannot beat 0.39% on `landscape-square` is not buying its
  complexity.** That is now a shell command, a distance transform, and ~600
  lines of adapter, against the incumbent's eight tuned heuristic flags.
* **The width-recovery post-pass is backend-independent and should be lifted
  out.** It takes a mask and a polyline and returns a radius; nothing about it
  is specific to autotrace. Any track producing centerlines can adopt
  `experiments/autotrace/width.py` directly and should, before reporting a
  width-sensitive score. Several tracks will otherwise repeat exactly the
  mistake this one was sent to correct.
* **Cap extension is likewise universal.** Every medial-axis method inherits the
  one-radius shortfall at free ends (report §2.3); it cost 1.147u → 0.280u of
  endpoint error here for about 30 lines.

### Where it genuinely loses, and why a vector backend may still win

1. **Resolution dependence is structural and does not go away.** Centerline
   error is a flat ~1.1–1.4 raster pixels at every scale tested. There is no
   setting at which this converges to the true centerline — accuracy is bought
   with pixels, quadratically, forever. `flo-mat` (Track 1) computes the MAT on
   the Béziers directly and has no such floor. **If Track 1 works at all, it
   should beat these numbers, and if it does not, that is a strong signal.**
2. **Merged source elements cost 5.5×.** Synthetic case 13 (X as two shapes)
   scores 0.53u P95; case 14 (the same X as one mask) scores 2.89u. This
   pipeline leans hard on per-element separation, which the report's §9.1
   "preserve source semantics" already recommends — but it means the numbers
   above would degrade substantially on artwork that arrives pre-flattened.
3. **Degenerate shapes are silently dropped** (the solid-disc case above).
4. **Tapered strokes need a width model this output format cannot express**
   (`sun-square`).

### Recommendation

Keep it, as the report asks — but promote it from "baseline we keep honest" to
**"the thing to beat, and the source of two components everyone else should
reuse"**. It is not obviously the production architecture: the resolution floor
and the merged-element penalty are real, and a working vector MAT should win on
both. But on today's evidence it is competitive with the incumbent at a small
fraction of the complexity, and no track should ship a more complicated backend
without showing it beats 0.03% / 0.39%.

## Synthetic ground-truth corpus

20 cases generated by stroking known centerlines (`experiments/autotrace/synth.py`),
at `--scale 4 --stat trimmed --cap-extend`. Unlike the real artwork these have a
known answer, so the columns are true centerline error, not reconstruction error.

| case | traced subpaths | centerline med (u) | centerline P95 (u) | endpoint med (u) | true r | recovered r | radius err |
|---|---|---|---|---|---|---|---|
| `01-horizontal-line` | 1 | 0.32 | 0.51 | 0.28 | 10.00 | 9.88 | -1.2% |
| `02-diagonal-line` | 1 | 0.26 | 0.57 | 0.23 | 10.00 | 9.90 | -1.0% |
| `03-circular-arc` | 1 | 0.57 | 1.16 | 0.90 | 10.00 | 9.77 | -2.3% |
| `04-s-curve` | 1 | 0.37 | 0.97 | 0.22 | 10.00 | 9.85 | -1.5% |
| `05-tight-u` | 1 | 0.20 | 0.67 | 0.06 | 10.00 | 9.95 | -0.5% |
| `06-closed-loop` | 1 | 0.45 | 0.84 | 103.49 | 10.00 | 9.79 | -2.1% |
| `07-round-cap` | 1 | 0.30 | 0.49 | 0.28 | 10.00 | 9.88 | -1.2% |
| `08-butt-cap` | 1 | 0.31 | 0.51 | 9.88 | 10.00 | 9.88 | -1.2% |
| `09-square-cap` | 1 | 0.30 | 0.49 | 0.28 | 10.00 | 9.88 | -1.2% |
| `10-round-join` | 1 | 0.20 | 0.53 | 0.13 | 10.00 | 9.95 | -0.5% |
| `11-bevel-join` | 1 | 0.20 | 0.53 | 0.13 | 10.00 | 9.95 | -0.5% |
| `12-miter-join` | 2 | 0.26 | 1.27 | 0.14 | 10.00 | 9.89 | -1.1% |
| `13-x-crossing-separate` | 2 | 0.26 | 0.53 | 0.24 | 10.00 | 9.87 | -1.4% |
| `14-x-crossing-unioned` | 3 | 0.40 | 2.89 | 0.23 | 10.00 | 9.43 | -5.7% |
| `15-t-junction` | 2 | 0.26 | 0.46 | 0.14 | 10.00 | 9.94 | -0.6% |
| `16-y-junction` | 2 | 0.35 | 1.05 | 1.47 | 10.00 | 9.77 | -2.3% |
| `17-near-parallel` | 2 | 0.32 | 0.51 | 0.28 | 10.00 | 9.88 | -1.2% |
| `18-self-overlap` | 1 | 0.33 | 0.76 | 0.30 | 10.00 | 9.83 | -1.7% |
| `19-variable-width` | 1 | 1.08 | 2.46 | 51.05 | 9.50 | 9.64 | +1.5% |
| `20-noisy-boundary` | 1 | 0.60 | 1.27 | 0.60 | 10.00 | 10.55 | +5.5% |

Reading this table:

* **Width recovery is accurate to 1–2% on every clean case.** That is the core
  validation of the idea: sampling the source EDT along a traced path recovers
  the true stroke radius, without any calibration constant.
* **Three endpoint numbers are anomalies, not results**, and are called out so
  nobody quotes them:
  * `06-closed-loop` (103.49u) — a closed loop has no endpoints; the metric is
    comparing an arbitrary seam point against an unrelated one. Meaningless by
    construction.
  * `19-variable-width` (51.05u) — this case is built as 39 stacked segments to
    fake a width ramp, so it has 78 "ground-truth endpoints" that are really
    interior points. Also meaningless by construction.
  * `08-butt-cap` (9.88u) — **this one is a real defect.** 9.88u is almost
    exactly one stroke radius (10.0u). Cap extension steps back one radius from
    the mask edge because it assumes a *round* cap; for a butt cap the
    centerline should reach the edge itself. Round (0.28u) and square (0.28u)
    caps are fine, butt caps are short by exactly r. Our corpus is round-capped
    pen art so this does not affect any real number here, but any consumer of
    `pipeline._cap_extend` on butt-capped art needs to know.
* **The two worst geometry cases are the two the report predicted**:
  `14-x-crossing-unioned` (P95 2.89u, and the only case where recovered radius
  is off by more than 2.5%) and `19-variable-width` (median 1.08u). Both are
  ambiguity, not inaccuracy — see the failure-mode table.
* `12-miter-join` traces an acute corner as 2 subpaths rather than 1. The
  geometry is right; the topology is not. That is Track 8's problem by design.
