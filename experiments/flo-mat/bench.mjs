#!/usr/bin/env node
// The one re-runnable bench command for the real escalation ladder.
//
//   node experiments/flo-mat/bench.mjs                       # whole ladder
//   node experiments/flo-mat/bench.mjs house-wide            # one image
//   node experiments/flo-mat/bench.mjs --sat 1.3 --label sat13
//
// Writes debug/flo-mat/metrics.json, debug/flo-mat/graphs/<image>.json,
// outputs/flo-mat/<image>.svg and a comparison contact sheet.

import fs from 'node:fs';
import path from 'node:path';
import { normalizeSvg, elementsToSvg } from './lib/normalize.mjs';
import { runDocumentAsync, toGraphJson } from './lib/pipeline.mjs';
import { scoreReconstruction, comparePixelDiff } from './lib/metrics.mjs';
import { comparisonSheet, writeSheet, htmlSheet } from './lib/sheet.mjs';

const LADDER = [
  'house-wide', 'butterfly-wide', 'boat-tall', 'island-tall', 'balloon-tall',
  'home-wide', 'house-tall', 'dinosaur-wide', 'landscape-square', 'sun-square',
];
// incumbent Python pipeline scores, for the rows we have them for
const INCUMBENT = { 'dinosaur-wide': 0.02, 'landscape-square': 0.73, 'sun-square': 4.2 };

const argv = process.argv.slice(2);
const arg = (k, d) => { const i = argv.indexOf(`--${k}`); return i >= 0 ? argv[i + 1] : d; };
const names = argv.filter((a) => !a.startsWith('--') && !argv[argv.indexOf(a) - 1]?.startsWith('--'));
const images = names.length ? names : LADDER;

const label = arg('label', 'default');
const suffix = label === 'default' ? '' : `-${label}`;
const opts = {
  satSweep: arg('sat', null) ? Number(arg('sat')) : null,
  applySat: arg('applySat', 'false') === 'true',
  satScale: Number(arg('satScale', 2)),
  simplify: arg('simplify', 'true') === 'true',
  caps: arg('caps', 'apex'),
  capK: Number(arg('capK', 1)),
  widthMode: arg('widthMode', 'measured'),
  variableWidth: Number(arg('variableWidth', 0)),
  minChainLength: Number(arg('minChainLength', 0)),
};

const OUT = 'debug/flo-mat';
fs.mkdirSync(path.join(OUT, 'graphs'), { recursive: true });
fs.mkdirSync('outputs/flo-mat', { recursive: true });

const rows = [];
const sheetRows = [];
for (const name of images) {
  const src = `inputs/${name}.svg`;
  if (!fs.existsSync(src)) { console.log(`skip ${name} (missing)`); continue; }
  const svg = fs.readFileSync(src, 'utf8');

  const t0 = Date.now();
  const doc = normalizeSvg(svg);
  const normSvg = elementsToSvg(doc);
  const normScore = scoreReconstruction(svg, normSvg, { width: 900 });

  let result; let error = null;
  try {
    result = await runDocumentAsync(doc, opts, { timeoutMs: Number(arg('timeout', 20000)) });
  } catch (e) { error = e; }
  const ms = Date.now() - t0;
  if (error || !result) {
    rows.push({ image: name, error: String(error && error.message) });
    console.log(`${name.padEnd(18)} ERROR ${error && error.message}`);
    continue;
  }

  const outFile = `outputs/flo-mat/${name}.svg`;
  fs.writeFileSync(outFile, result.svg);
  fs.writeFileSync(path.join(OUT, 'graphs', `${name}${suffix}.json`),
    JSON.stringify(toGraphJson(result, { image: name, source: src }), null, 1));

  const recon = scoreReconstruction(svg, result.svg, { width: 1200, units: doc.viewBox.w / 1200 });
  // incumbent-compatible number, so this row can be read next to the Python
  // pipeline's 0.02% / 0.73% in docs/current-attempt-handoff.md
  const incumbentMetric = await comparePixelDiff(src, outFile, 1200);
  const failed = result.perElement.filter((p) => p.error);

  rows.push({
    image: name,
    normIoU: normScore.iou,
    elements: doc.elements.length,
    failedElements: failed.length,
    ...recon,
    comparePct: incumbentMetric.pct,
    complexity: result.complexity,
    width: result.width,
    contracted: result.contracted,
    ms,
    matMs: result.timing.matMs,
    msPerElement: result.timing.matMs / Math.max(1, doc.elements.length),
    incumbentPixelDiffPct: INCUMBENT[name],
  });

  sheetRows.push({
    label: name,
    inputSvg: svg,
    outputSvg: result.svg,
    note: `IOU ${recon.iou.toFixed(4)} COMPAREJS ${incumbentMetric.pct.toFixed(2)}% SYM ${(recon.symDiffFrac * 100).toFixed(1)}%`
      + ` BD.P95 ${recon.boundaryP95.toFixed(2)} STR ${result.complexity.strokes} EDG ${result.complexity.edges}`
      + (failed.length ? ` FAILED-EL ${failed.length}` : ''),
  });

  console.log(
    `${name.padEnd(18)} norm=${normScore.iou.toFixed(4)} IoU=${recon.iou.toFixed(4)}`
    + ` compare.js=${incumbentMetric.pct.toFixed(2)}% sym=${(recon.symDiffFrac * 100).toFixed(1)}%`
    + ` bdP95=${recon.boundaryP95.toFixed(2)} el=${doc.elements.length}${failed.length ? `(${failed.length} failed)` : ''}`
    + ` n=${result.complexity.nodes} e=${result.complexity.edges} str=${result.complexity.strokes}`
    + ` ${(ms / 1000).toFixed(1)}s`,
  );
}

fs.writeFileSync(path.join(OUT, `metrics${suffix}.json`), JSON.stringify({ options: opts, rows }, null, 1));
if (sheetRows.length && arg('sheet', 'true') === 'true') {
  writeSheet(path.join(OUT, `comparison-sheet${suffix}.png`), comparisonSheet(sheetRows, { tile: 460 }));
  console.log(`-> ${OUT}/comparison-sheet${suffix}.png`);
}
console.log(`-> ${OUT}/metrics${suffix}.json`);
