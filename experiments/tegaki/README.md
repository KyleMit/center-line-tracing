# Track 5 — Tegaki generator, adapted

A port of the centerline pipeline inside [gkurt/tegaki](https://github.com/gkurt/tegaki)
(MIT — see `VENDOR.md` and `LICENSE.tegaki`), adapted from font glyphs to
arbitrary filled SVG artwork.

**Read `debug/tegaki/NOTES.md` first** — it contains the algorithm map of the
original, what was changed and why, the results, and the verdict.

Plain ES-module JavaScript, Node 22, no Bun and no TypeScript. `d3-delaunay` is
the only runtime dependency beyond what the repo already had (`sharp`,
`@resvg/resvg-js`).

## Files

| file | what |
|---|---|
| `constants.js` | Tegaki's tunables, with ours marked `ADAPTED` |
| `bezier.js` | adaptive de Casteljau flattening + SVG arc/relative-command support |
| `svg.js` | SVG normalization: transforms, groups, shape→path, filled-element extraction |
| `raster.js` | scanline nonzero-winding fill; binary, no AA, deterministic |
| `dt.js` | chamfer and exact (Felzenszwalb–Huttenlocher) distance transforms |
| `thin.js` | Zhang-Suen, Guo-Hall, Lee/LUT, partial morphological, distance-ordered medial axis |
| `cleanup.js` | junction-cluster collapse, erased-component restoration, labelling |
| `trace.js` | skeleton → polylines, curvature look-ahead, T-vs-X rule, RDP, **both pruners** |
| `voronoi.js` | sampled-boundary Voronoi medial axis with the width-aware spur pruner |
| `order.js` | orientation, dot classification/deferral, arc-length `t`, width profile |
| `graph.js` | common graph model + stroke-order extension + validator |
| `pipeline.js` | orchestration, cap extension, SVG output |
| `metrics.js` | IoU, symmetric difference, boundary distance, centerline error, complexity |
| `synth.js` | the 20-case synthetic ground-truth corpus generator |
| `bench.js` | the one re-runnable bench command |
| `sheet.js` | comparison / progress / synthetic / crop contact sheets |
| `render.js` | deterministic SVG→PNG and the red-on-grey overlay |
| `order-sheet.js` | stroke order/direction visualization (viridis ramp + pen-down/pen-up markers) |
| `cli.js` | single-file conversion |

## Usage

```bash
# one file
node experiments/tegaki/cli.js inputs/house-wide.svg out.svg \
     --graph out.json --skeleton zhang-suen --prune tegaki-width --verbose

# corpus, benches, sheets
node experiments/tegaki/synth.js
node experiments/tegaki/bench.js synth --tag baseline
node experiments/tegaki/bench.js real  --tag final
node experiments/tegaki/bench.js prune                                    # pruner A/B
node experiments/tegaki/bench.js prune-sweep --only dinosaur-wide         # §10.2 model selection
node experiments/tegaki/bench.js ab                                       # 5 skeletonizers
node experiments/tegaki/bench.js ab-real --only house-wide,dinosaur-wide
node experiments/tegaki/sheet.js comparison --tag final
node experiments/tegaki/sheet.js progress --image landscape-square
node experiments/tegaki/order-sheet.js                                    # stroke order/direction
```

Key options (`DEFAULTS` in `pipeline.js`): `--scale` px per user unit (2), or
`--resolution N` for Tegaki's aspect-fit mode; `--skeleton` one of
`zhang-suen|guo-hall|lee|thin|medial-axis|voronoi`; `--dt chamfer|euclidean`;
`--prune tegaki-width|tegaki-length|none`; `--spur-width-ratio` (1.5);
`--cap-style round|ink|none`; `--merge-mode radius|tegaki|off`.
