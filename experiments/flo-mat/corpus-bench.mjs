#!/usr/bin/env node
// Go/no-go harness: run the whole synthetic corpus through flo-mat.
//
//   node experiments/flo-mat/corpus-bench.mjs [--sat 1.5] [--caps none] [--only 14]

import fs from 'node:fs';
import path from 'node:path';
import { CORPUS, corpusSvg, truthPoints } from './lib/corpus.mjs';
import { normalizeSvg, elementsToSvg } from './lib/normalize.mjs';
import { runDocument, toGraphJson } from './lib/pipeline.mjs';
import { scoreReconstruction, centerlineError } from './lib/metrics.mjs';
import { chainPoints } from './lib/graph.mjs';
import { comparisonSheet, writeSheet } from './lib/sheet.mjs';

const argv = process.argv.slice(2);
const arg = (k, d) => {
  const i = argv.indexOf(`--${k}`);
  return i >= 0 ? argv[i + 1] : d;
};

const OUT = 'debug/flo-mat';
const CORP = path.join(OUT, 'corpus');
fs.mkdirSync(CORP, { recursive: true });
fs.mkdirSync(path.join(OUT, 'graphs'), { recursive: true });
fs.mkdirSync(path.join(OUT, 'recon'), { recursive: true });

const only = arg('only', null);
const label = arg('label', 'default');
const opts = {
  applySat: arg('applySat', 'false') === 'true',
  satScale: Number(arg('satScale', 2)),
  simplify: arg('simplify', 'true') === 'true',
  satSweep: arg('sat', null) ? Number(arg('sat')) : null,
  caps: arg('caps', 'apex'),
  capK: Number(arg('capK', 1)),
  widthMode: arg('widthMode', 'measured'),
};

const rows = [];
const sheetRows = [];
for (const c of CORPUS) {
  if (only && !c.id.startsWith(String(only).padStart(2, '0')) && c.name !== only) continue;
  const svg = corpusSvg(c);
  fs.writeFileSync(path.join(CORP, `${c.id}.svg`), svg);

  const t0 = Date.now();
  const doc = normalizeSvg(svg);

  // normalization round-trip check (brief: verify BEFORE running any MAT)
  const normSvg = elementsToSvg(doc);
  const normScore = scoreReconstruction(svg, normSvg, { width: 600 });

  let result; let err = null;
  try {
    result = runDocument(doc, opts);
  } catch (e) { err = e; }
  const ms = Date.now() - t0;

  if (err || !result) {
    rows.push({ id: c.id, error: String(err && err.message || err) });
    console.log(`${c.id.padEnd(24)} ERROR ${err && err.message}`);
    continue;
  }

  fs.writeFileSync(path.join(OUT, 'recon', `${c.id}.svg`), result.svg);
  fs.writeFileSync(
    path.join(OUT, 'graphs', `${c.id}.json`),
    JSON.stringify(toGraphJson(result, { image: c.id, source: `debug/flo-mat/corpus/${c.id}.svg` }), null, 1),
  );

  const recon = scoreReconstruction(svg, result.svg, { width: 900, units: c.viewBox.w / 900 });
  const cerr = centerlineError(chainPoints(result.chains, 0.4), truthPoints(c));

  sheetRows.push({
    label: c.id,
    inputSvg: svg,
    outputSvg: result.svg,
    note: `IOU ${recon.iou.toFixed(4)} SYM ${(recon.symDiffFrac * 100).toFixed(2)}% CL.P95 ${cerr.p95.toFixed(2)}`
      + ` STR ${result.complexity.strokes} EDG ${result.complexity.edges}`,
  });

  rows.push({
    id: c.id,
    num: c.num,
    normIoU: normScore.iou,
    ...recon,
    centerline: cerr,
    complexity: result.complexity,
    width: result.width,
    caps: result.capReports,
    ms,
    matMs: result.timing.matMs,
  });

  console.log(
    `${c.id.padEnd(24)} norm=${normScore.iou.toFixed(4)} IoU=${recon.iou.toFixed(4)}`
    + ` sym=${(recon.symDiffFrac * 100).toFixed(2)}% cl.med=${cerr.median.toFixed(2)} cl.p95=${cerr.p95.toFixed(2)}`
    + ` cov.p95=${cerr.coverP95.toFixed(2)} n=${result.complexity.nodes} e=${result.complexity.edges}`
    + ` str=${result.complexity.strokes} deg3=${result.complexity.deg3} deg4=${result.complexity.deg4}`
    + ` ${ms}ms`,
  );
}

const suffix = label === 'default' ? '' : `-${label}`;
const outFile = path.join(OUT, `corpus-metrics${suffix}.json`);
fs.writeFileSync(outFile, JSON.stringify({ options: opts, rows }, null, 1));

if (sheetRows.length && arg('sheet', 'true') === 'true') {
  const png = comparisonSheet(sheetRows, { tile: 420 });
  const sheetFile = path.join(OUT, `corpus-sheet${suffix}.png`);
  writeSheet(sheetFile, png);
  console.log(`-> ${sheetFile}`);
}
console.log(`-> ${outFile}`);
