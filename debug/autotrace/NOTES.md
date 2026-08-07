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
