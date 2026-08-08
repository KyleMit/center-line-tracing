# center-line-tracing

Turn **filled** SVG artwork into **stroked centerline** SVG — the drawing redrawn
as pen strokes with a width, instead of as outlines with a fill.

The product goal, in the owner's words, is the acceptance criterion:

> "Smooth consistent lines as if drawn by a kid on a digital coloring app. I'd
> like them to closely follow the input design, but not at the expense of tiny
> micro optimizations that look unnatural."

The engine is scikit-image's Euclidean `medial_axis` for the skeleton, [Skan] for
the branch graph, and Schneider Bézier fitting for the strokes, with an automatic
width-aware pruning pass that decides how much skeleton noise to delete. It was
picked over seven alternatives on measured accuracy *and* measured smoothness;
one configuration handles all ten drawings with no per-image tuning.

[Skan]: https://skeleton-analysis.org/

## Look at the output first

**[`docs/contact-sheet.html`](docs/contact-sheet.html)** — open it in a browser.
Every drawing, source against traced output, with a drag-to-wipe comparison and a
difference view. It is self-contained; no server, no build step. That sheet is the
fastest way to decide whether this is good enough for what you need.

## Run it

```bash
pip3 install -r requirements.txt
npm install

python3 src/run.py                                  # inputs/ -> outputs/skimage-skan/
python3 src/run.py --images house-wide              # just one
python3 src/run.py --in-dir mydrawings --out-dir /tmp/trace
```

Roughly 25 s per drawing. Full details, including how to rebuild the contact
sheet, are in **[docs/runbook.md](docs/runbook.md)**.

## What you get

| drawing | scale | λ | error | wobble | pts/width | strokes | out | source |
|---|---|---|---|---|---|---|---|---|
| `house-wide` | 8 | 1.0 | 0.0178 | 0.0217 | 2.10 | 68 | 14 K | 20 K |
| `butterfly-wide` | 8 | 0.5 | 0.0131 | 0.0154 | 2.54 | 39 | 12 K | 21 K |
| `boat-tall` | 8 | 0.5 | 0.0139 | 0.0163 | 1.41 | 100 | 19 K | 28 K |
| `island-tall` | 8 | 1.0 | 0.0190 | 0.0204 | 1.74 | 70 | 19 K | 34 K |
| `balloon-tall` | 8 | 1.5 | 0.0188 | 0.0198 | 1.54 | 95 | 19 K | 30 K |
| `home-wide` | 8 | 0.0 | 0.0225 | 0.0167 | 1.76 | 141 | 24 K | 30 K |
| `house-tall` | 8 | 0.0 | 0.0176 | 0.0199 | 2.22 | 151 | 27 K | 51 K |
| `dinosaur-wide` | 8 | 0.0 | 0.0157 | 0.0107 | 1.32 | 162 | 30 K | 42 K |
| `landscape-square` | 2 | 0.5 | 0.0244 | 0.0219 | 3.10 | 297 | 63 K | 54 K |
| `sun-square` | 2 | 1.5 | 0.0246 | 0.0186 | 3.95 | 53 | 10 K | 17 K |

Medians: error **0.0183**, wobble **0.0192**, **1.93** control points per stroke
width. Nine of ten outputs are smaller than the source SVG.

- **error** — symmetric difference between the re-stroked output and the source
  fill, as a fraction of source ink. Lower is better.
- **wobble** — RMS deviation from the path's own one-stroke-width low-pass, with
  the curvature bias removed, in stroke radii. An exact straight line scores
  0.000 and an exact circular arc 0.002, so ~0.02 is "drawn in one motion". This
  is the axis that tracks the product goal; **error alone will mislead you**,
  because it rewards a path that wiggles along the outline.
- **λ** — the pruning strength the selector chose, in local stroke widths.

## What is in here

| path | |
|---|---|
| `inputs/` | the ten source drawings |
| `outputs/skimage-skan/` | traced output: one SVG per drawing, the same drawing as a graph under `graphs/`, and `manifest.json` recording the config and score of each |
| `docs/contact-sheet.html` | the reviewable before/after sheet |
| `docs/` | runbook, pipeline, tuning guide, lessons, graph schema |
| `src/` | everything executable — see [docs/pipeline.md](docs/pipeline.md) for the file map |
| `runs/` | the measured record: `metrics.json`, `scale-sweep.md`, the ground-truth corpus, and the sheets from the last full bench |
| `target/dinosaur-wide.svg` | a hand-authored reference of the look being aimed at; not produced by this pipeline and not scored against |

## Read next

- **[docs/runbook.md](docs/runbook.md)** — install, run, rebuild the sheet, verify.
- **[docs/tuning.md](docs/tuning.md)** — the two knobs that matter, what each is
  measured to do, and the loop for refining one drawing that came out wrong.
- **[docs/pipeline.md](docs/pipeline.md)** — how it works, stage by stage, and
  which file owns which stage.
- **[docs/lessons.md](docs/lessons.md)** — the traps. Every one of these cost real
  time; several produced confident wrong numbers.
- **[docs/graph-schema.md](docs/graph-schema.md)** — `centerline-graph/1`, the
  intermediate representation, if you want the geometry rather than the SVG.

## Known limits

Stated up front so they are not discovered as surprises. Detail in
[docs/pipeline.md § What this cannot do](docs/pipeline.md#what-this-cannot-do).

- **Butt and square caps cannot be reproduced.** Output uses
  `stroke-linecap="round"`; SVG has one linecap per path. Recovering cap *style*
  is unimplemented.
- **Variable-width strokes are approximated** by piecewise-constant runs. SVG 1.1
  has no variable-width stroke short of emitting an outline, which defeats the
  purpose.
- **Crossings stay ambiguous.** A degree-4 node is left as a node; nothing decides
  which pair of arms is one continuous stroke.
- **T-junction blobs are the main visible defect.** The medial axis forks into a Y
  before the stem reaches the bar, and the two short arms get round caps that
  render slightly past the bar's edge.
- **Pruning does not keep up with raster resolution.** Measured, with a known
  correct answer, in [docs/tuning.md](docs/tuning.md#the-open-problem). It is why
  the default is scale 8 and not something finer.
