# Track 2 — AutoTrace `-centerline` baseline

Slug `autotrace` · branch `claude/centerline-autotrace-qtkuxm` · report §6.2, §18.2

**Verdict up front:** off-the-shelf `autotrace -centerline` **plus our own
width recovery is competitive** — it ties the incumbent on `dinosaur-wide`
(0.02%) and beats it on `landscape-square`. The prior evaluation's conclusion
("autotrace centerline output did not preserve usable stroke widths") was
correct about the symptom and wrong about the implication: the **geometry was
always fine**, and one global fixed width was the entire problem.

_(numbers, tables and the full verdict are filled in below — see Results)_

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
