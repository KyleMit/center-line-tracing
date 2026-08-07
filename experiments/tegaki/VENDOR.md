# Vendored / ported from Tegaki

Source: <https://github.com/gkurt/tegaki>, `packages/generator/src/`, `main`
branch, cloned 2026-08-07.

License: **MIT**, Copyright (c) 2026 Gokhan Kurt. Verified against the repository's
own `LICENSE` file (the report's §6.9 claim is correct). The full text is
reproduced in `LICENSE.tegaki` alongside this file.

Nothing here is a copy of Tegaki's TypeScript. Every file in this directory is a
re-implementation in plain ES-module JavaScript, written from a read of the
original, with our adaptations marked `ADAPTED:` in comments. Correspondence:

| ours | Tegaki original |
|---|---|
| `bezier.js` | `processing/bezier.ts` (plus SVG arc/relative-command support we added) |
| `raster.js` | `processing/rasterize.ts` |
| `dt.js` | `processing/width.ts` |
| `thin.js` | `processing/skeletonize/{zhang-suen,guo-hall,lee,morphological,medial-axis}.ts` |
| `cleanup.js` | `processing/skeletonize/cleanup.ts` |
| `trace.js` | `processing/trace.ts` |
| `voronoi.js` | `processing/voronoi-medial-axis.ts` |
| `order.js` | `processing/stroke-order.ts`, `processing/font-units.ts` |
| `constants.js` | `constants.ts` |

`svg.js`, `graph.js`, `pipeline.js`, `bench.js`, `synth.js` and `sheet.js` are
ours and have no Tegaki counterpart.

The algorithm map in `debug/tegaki/NOTES.md` describes the original in detail.
