#!/usr/bin/env node
// Progress sheet for the focus image: one tile per iteration of this track, in
// the order the changes were actually made, each reproducible from flags.
//
//   node experiments/flo-mat/progress.mjs sun-square

import fs from 'node:fs';
import path from 'node:path';
import { normalizeSvg } from './lib/normalize.mjs';
import { runDocumentAsync } from './lib/pipeline.mjs';
import { scoreReconstruction, comparePixelDiff } from './lib/metrics.mjs';
import { progressSheet, writeSheet } from './lib/sheet.mjs';

const name = process.argv[2] || 'sun-square';
const OUT = 'debug/flo-mat';

// chronological: each row is the state of the pipeline after one change
const STEPS = [
  ['1 RAW MAT, NODE WIDTH', { contractEps: 0, widthMode: 'chain', caps: 'none' }],
  ['2 + NODE/EDGE MERGE', { widthMode: 'chain', caps: 'none' }],
  ['3 + MEASURED WIDTH', { widthMode: 'measured', caps: 'none' }],
  ['4 + CAP CALIBRATION', { widthMode: 'measured', caps: 'apex' }],
  ['5 + SAT S=1.3', { widthMode: 'measured', caps: 'apex', satSweep: 1.3 }],
];

const src = `inputs/${name}.svg`;
const svg = fs.readFileSync(src, 'utf8');
const doc = normalizeSvg(svg);
fs.mkdirSync(path.join(OUT, 'recon'), { recursive: true });

const tiles = [];
let stepIndex = 0;
for (const [tag, opts] of STEPS) {
  const r = await runDocumentAsync(doc, opts, { timeoutMs: 20000 });
  // unique path per step: sharp/libvips caches decoded images by filename
  const tmp = path.join(OUT, 'recon', `${name}-step${stepIndex++}.svg`);
  fs.writeFileSync(tmp, r.svg);
  const cmp = await comparePixelDiff(src, tmp, 1200);
  const recon = scoreReconstruction(svg, r.svg, { width: 900 });
  tiles.push({
    svg: r.svg,
    tag,
    score: `COMPAREJS ${cmp.pct.toFixed(2)}% IOU ${recon.iou.toFixed(4)} STR ${r.complexity.strokes} EDG ${r.complexity.edges}`,
  });
  console.log(`${tag.padEnd(42)} compare.js=${cmp.pct.toFixed(2)}% IoU=${recon.iou.toFixed(4)}`
    + ` strokes=${r.complexity.strokes} edges=${r.complexity.edges} len=${r.complexity.totalLength.toFixed(0)}`);
}
writeSheet(path.join(OUT, `progress-${name}.png`), progressSheet(tiles, { tile: 460, cols: 3 }));
console.log(`-> ${OUT}/progress-${name}.png`);
