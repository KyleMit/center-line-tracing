#!/usr/bin/env node
// Per-image SAT scale selection, then promote the winners to outputs/flo-mat/.
//
// The rule is report §13 Experiment 4 applied to the ONE knob flo-mat gives us:
// take the SIMPLEST graph (fewest strokes) whose reconstruction is within
// `--tol` percentage points of the best reconstruction over the sweep. This is
// SAT-scale selection only — the general width-aware pruning + Pareto model
// selection is Track 8's job and consumes the graph JSON written here.
//
//   node experiments/flo-mat/promote.mjs [--tol 0.03]

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
const INCUMBENT = { 'dinosaur-wide': 0.02, 'landscape-square': 0.73, 'sun-square': 4.2 };
const SCALES = [null, 1.1, 1.3, 1.5, 2];

const argv = process.argv.slice(2);
const arg = (k, d) => { const i = argv.indexOf(`--${k}`); return i >= 0 ? argv[i + 1] : d; };
const TOL = Number(arg('tol', 0.03));
const images = argv.filter((a, i) => !a.startsWith('--') && !argv[i - 1]?.startsWith('--'));
const list = images.length ? images : LADDER;

const OUT = 'debug/flo-mat';
fs.mkdirSync(path.join(OUT, 'graphs'), { recursive: true });
fs.mkdirSync(path.join(OUT, 'recon'), { recursive: true });
fs.mkdirSync('outputs/flo-mat', { recursive: true });

const rows = [];
const sheetRows = [];
for (const name of list) {
  const src = `inputs/${name}.svg`;
  const svg = fs.readFileSync(src, 'utf8');
  const doc = normalizeSvg(svg);
  const normScore = scoreReconstruction(svg, elementsToSvg(doc), { width: 900 });

  const candidates = [];
  for (const s of SCALES) {
    const t0 = Date.now();
    const r = await runDocumentAsync(doc, { satSweep: s }, { timeoutMs: 20000 });
    // A UNIQUE path per candidate: sharp/libvips caches decoded images by
    // filename, so reusing one scratch file silently scores every candidate
    // with the first candidate's pixels.
    const tmp = path.join(OUT, 'recon', `${name}-sat-${s === null ? 'raw' : s}.svg`);
    fs.writeFileSync(tmp, r.svg);
    const cmp = await comparePixelDiff(src, tmp, 1200);
    const recon = scoreReconstruction(svg, r.svg, { width: 1200, units: doc.viewBox.w / 1200 });
    candidates.push({ s, r, cmp: cmp.pct, recon, ms: Date.now() - t0 });
    console.log(`  ${name} s=${String(s).padEnd(4)} compare.js=${cmp.pct.toFixed(3)}%`
      + ` IoU=${recon.iou.toFixed(4)} str=${r.complexity.strokes} edges=${r.complexity.edges}`);
  }

  const best = Math.min(...candidates.map((c) => c.cmp));
  const eligible = candidates.filter((c) => c.cmp <= best + TOL);
  const pick = eligible.reduce((a, b) => (b.r.complexity.strokes < a.r.complexity.strokes ? b : a));

  const outFile = `outputs/flo-mat/${name}.svg`;
  fs.writeFileSync(outFile, pick.r.svg);
  fs.writeFileSync(path.join(OUT, 'graphs', `${name}.json`), JSON.stringify(
    toGraphJson(pick.r, { image: name, source: src, satScale: pick.s }), null, 1,
  ));

  const failed = pick.r.perElement.filter((p) => p.error);
  rows.push({
    image: name,
    satScale: pick.s,
    normIoU: normScore.iou,
    elements: doc.elements.length,
    failedElements: failed.length,
    comparePct: pick.cmp,
    bestComparePct: best,
    incumbentPixelDiffPct: INCUMBENT[name],
    ...pick.recon,
    complexity: pick.r.complexity,
    width: pick.r.width,
    contracted: pick.r.contracted,
    matMs: pick.r.timing.matMs,
    msPerElement: pick.r.timing.matMs / Math.max(1, doc.elements.length),
    sweep: candidates.map((c) => ({
      s: c.s, comparePct: c.cmp, iou: c.recon.iou, strokes: c.r.complexity.strokes, edges: c.r.complexity.edges,
    })),
  });

  const tag = pick.s === null ? 'RAW MAT' : `SAT S=${pick.s}`;
  sheetRows.push({
    label: name,
    inputSvg: svg,
    outputSvg: pick.r.svg,
    note: `${tag}  COMPAREJS ${pick.cmp.toFixed(2)}%  IOU ${pick.recon.iou.toFixed(4)}`
      + `  BD.P95 ${pick.recon.boundaryP95.toFixed(2)}  STR ${pick.r.complexity.strokes}`
      + `  EDG ${pick.r.complexity.edges}  EL ${doc.elements.length}`
      + (INCUMBENT[name] !== undefined ? `  INCUMBENT ${INCUMBENT[name]}%` : ''),
  });
  console.log(`${name.padEnd(18)} PICK ${tag}  compare.js=${pick.cmp.toFixed(2)}%`
    + ` (best ${best.toFixed(2)}%)  strokes=${pick.r.complexity.strokes}\n`);
}

fs.writeFileSync(path.join(OUT, 'metrics-final.json'), JSON.stringify({ tol: TOL, scales: SCALES, rows }, null, 1));
writeSheet(path.join(OUT, 'comparison-sheet-final.png'), comparisonSheet(sheetRows, { tile: 460 }));
fs.writeFileSync(path.join(OUT, 'comparison-sheet-final.html'), htmlSheet(
  'flo-mat — promoted results',
  rows.map((r) => ({
    label: `${r.image} (${r.satScale === null ? 'raw MAT' : `SAT s=${r.satScale}`})`,
    input: `../../inputs/${r.image}.svg`,
    output: `../../outputs/flo-mat/${r.image}.svg`,
    diff: `../../inputs/${r.image}.svg`,
    overlay: `../../outputs/flo-mat/${r.image}.svg`,
    metrics: [
      `compare.js   ${r.comparePct.toFixed(2)}%`,
      `incumbent    ${r.incumbentPixelDiffPct ?? '-'}`,
      `IoU          ${r.iou.toFixed(4)}`,
      `symdiff      ${(r.symDiffFrac * 100).toFixed(2)}%`,
      `boundary med ${r.boundaryMedian.toFixed(2)}`,
      `boundary P95 ${r.boundaryP95.toFixed(2)}`,
      `strokes      ${r.complexity.strokes}`,
      `edges        ${r.complexity.edges}`,
      `beziers      ${r.complexity.beziers}`,
      `total length ${r.complexity.totalLength.toFixed(0)}`,
      `width CV     ${r.width.perChainCv.toFixed(3)}`,
      `MAT ms/elem  ${r.msPerElement.toFixed(0)}`,
      `failed elems ${r.failedElements}`,
    ].join('\n'),
  })),
));
console.log(`-> ${OUT}/metrics-final.json`);
console.log(`-> ${OUT}/comparison-sheet-final.png`);
