#!/usr/bin/env node
// SAT sweep on real artwork: does flo-mat's built-in pruning remove the
// full-width bumps that short MAT corner branches produce at squared stroke
// ends, and at what cost in real detail?
//
//   node experiments/flo-mat/real-sat-sweep.mjs house-wide butterfly-wide

import fs from 'node:fs';
import path from 'node:path';
import { normalizeSvg } from './lib/normalize.mjs';
import { runDocumentAsync } from './lib/pipeline.mjs';
import { scoreReconstruction } from './lib/metrics.mjs';
import { progressSheet, writeSheet } from './lib/sheet.mjs';

const SCALES = [null, 1.1, 1.3, 1.5, 2, 3];
const images = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const names = images.length ? images : ['house-wide'];
const OUT = 'debug/flo-mat';
const all = {};

for (const name of names) {
  const svg = fs.readFileSync(`inputs/${name}.svg`, 'utf8');
  const doc = normalizeSvg(svg);
  const rows = [];
  const tiles = [];
  for (const s of SCALES) {
    const t = Date.now();
    const r = await runDocumentAsync(doc, { satSweep: s }, { timeoutMs: 20000 });
    const rec = scoreReconstruction(svg, r.svg, { width: 1200, units: doc.viewBox.w / 1200 });
    rows.push({
      s,
      iou: rec.iou,
      pixelDiffPct: rec.pixelDiffPct,
      symDiffFrac: rec.symDiffFrac,
      missingFrac: rec.missingFrac,
      extraFrac: rec.extraFrac,
      boundaryP95: rec.boundaryP95,
      ...r.complexity,
      ms: Date.now() - t,
    });
    tiles.push({
      svg: r.svg,
      tag: s === null ? 'RAW MAT' : `SAT S=${s}`,
      score: `IOU ${rec.iou.toFixed(4)} PIX ${rec.pixelDiffPct.toFixed(2)}% STR ${r.complexity.strokes} EDG ${r.complexity.edges}`,
    });
    console.log(`${name} s=${String(s).padEnd(5)} IoU=${rec.iou.toFixed(4)} pix=${rec.pixelDiffPct.toFixed(2)}%`
      + ` sym=${(rec.symDiffFrac * 100).toFixed(1)}% miss=${(rec.missingFrac * 100).toFixed(1)}%`
      + ` extra=${(rec.extraFrac * 100).toFixed(1)}% str=${r.complexity.strokes} edges=${r.complexity.edges}`
      + ` len=${r.complexity.totalLength.toFixed(0)}`);
    if (s !== null) fs.writeFileSync(path.join(OUT, 'recon', `${name}-sat${s}.svg`), r.svg);
  }
  all[name] = rows;
  writeSheet(path.join(OUT, `sat-progress-${name}.png`), progressSheet(tiles, { tile: 460, cols: 3 }));
  console.log(`-> ${OUT}/sat-progress-${name}.png`);
}
fs.writeFileSync(path.join(OUT, 'real-sat-sweep.json'), JSON.stringify(all, null, 1));
console.log(`-> ${OUT}/real-sat-sweep.json`);
