#!/usr/bin/env node
// Raw MAT vs. toScaleAxis(mat, s) over a sweep of s (report §12.3 / brief step 4).
// SAT is flo-mat's built-in pruning; this finds where it helps and where it eats
// real detail. No hand-rolled pruning anywhere — that is Track 8's job.

import fs from 'node:fs';
import path from 'node:path';
import { CORPUS, corpusSvg, truthPoints } from './lib/corpus.mjs';
import { normalizeSvg } from './lib/normalize.mjs';
import { runDocument } from './lib/pipeline.mjs';
import { scoreReconstruction, centerlineError } from './lib/metrics.mjs';
import { chainPoints } from './lib/graph.mjs';
import { progressSheet, writeSheet } from './lib/sheet.mjs';

const OUT = 'debug/flo-mat';
fs.mkdirSync(OUT, { recursive: true });

const SCALES = [null, 1.05, 1.1, 1.2, 1.3, 1.5, 2, 3];
const FOCUS = process.argv[2] || '20-noisy-boundary';

const results = {};
for (const c of CORPUS) {
  const svg = corpusSvg(c);
  const doc = normalizeSvg(svg);
  results[c.id] = [];
  for (const s of SCALES) {
    let r; let ok = true;
    try {
      r = runDocument(doc, { satSweep: s });
    } catch (e) { ok = false; results[c.id].push({ s, error: String(e.message) }); }
    if (!ok) continue;
    const recon = scoreReconstruction(svg, r.svg, { width: 900, units: c.viewBox.w / 900 });
    const cerr = centerlineError(chainPoints(r.chains, 0.4), truthPoints(c));
    results[c.id].push({
      s,
      iou: recon.iou,
      symDiffFrac: recon.symDiffFrac,
      missingFrac: recon.missingFrac,
      extraFrac: recon.extraFrac,
      boundaryP95: recon.boundaryP95,
      edges: r.complexity.edges,
      strokes: r.complexity.strokes,
      terminals: r.complexity.terminals,
      totalLength: r.complexity.totalLength,
      clP95: cerr.p95,
      coverP95: cerr.coverP95,
      svg: c.id === FOCUS ? r.svg : undefined,
    });
  }
}

// table
const head = ['case', ...SCALES.map((s) => (s === null ? 'raw' : `s=${s}`))];
const pad = (v, n) => String(v).padEnd(n);
console.log(`\n${pad(head[0], 24)}${head.slice(1).map((h) => pad(h, 16)).join('')}`);
console.log('IoU / edges');
for (const c of CORPUS) {
  const cells = results[c.id].map((r) => (r.error ? 'ERR' : `${r.iou.toFixed(4)}/${r.edges}`));
  console.log(pad(c.id, 24) + cells.map((x) => pad(x, 16)).join(''));
}

fs.writeFileSync(path.join(OUT, 'sat-sweep.json'), JSON.stringify(
  Object.fromEntries(Object.entries(results).map(([k, v]) => [k, v.map(({ svg, ...rest }) => rest)])),
  null, 1,
));

const focus = results[FOCUS];
if (focus && focus.some((f) => f.svg)) {
  const png = progressSheet(focus.filter((f) => f.svg).map((f) => ({
    svg: f.svg,
    underlay: corpusSvg(CORPUS.find((c) => c.id === FOCUS)),
    tint: [220, 20, 20],
    tag: f.s === null ? 'RAW MAT' : `SAT S=${f.s}`,
    score: `IOU ${f.iou.toFixed(4)} EDG ${f.edges} STR ${f.strokes}`,
  })), { tile: 420, cols: 4 });
  writeSheet(path.join(OUT, `sat-progress-${FOCUS}.png`), png);
  console.log(`\n-> ${OUT}/sat-progress-${FOCUS}.png`);
}
console.log(`-> ${OUT}/sat-sweep.json`);
