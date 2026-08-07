#!/usr/bin/env node
// One re-runnable bench command (Common Setup §Metrics).
//
//   node experiments/tegaki/bench.js synth [--skeleton ...] [--tag name]
//   node experiments/tegaki/bench.js real  [--skeleton ...] [--tag name]
//   node experiments/tegaki/bench.js ab                     # skeletonizer A/B
//   node experiments/tegaki/bench.js prune                  # pruner A/B
//
// Writes debug/tegaki/metrics.json (accumulated, keyed by run tag) and prints a
// table. Also writes graph JSON to debug/tegaki/graphs/ and SVGs to
// debug/tegaki/out/.

import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync } from 'node:fs';
import { convert, DEFAULTS } from './pipeline.js';
import { scoreReconstruction, scoreCenterline, complexity } from './metrics.js';
import { validateGraph } from './graph.js';
import { parseArgs } from './cli.js';

const SYNTH_DIR = 'debug/tegaki/synth';
const OUT_DIR = 'debug/tegaki/out';
const GRAPH_DIR = 'debug/tegaki/graphs';
const METRICS = 'debug/tegaki/metrics.json';

export const REAL_LADDER = [
  'house-wide',
  'butterfly-wide',
  'boat-tall',
  'island-tall',
  'balloon-tall',
  'home-wide',
  'house-tall',
  'dinosaur-wide',
  'landscape-square',
  'sun-square',
];

function loadMetrics() {
  if (!existsSync(METRICS)) return { runs: {} };
  try {
    return JSON.parse(readFileSync(METRICS, 'utf8'));
  } catch {
    return { runs: {} };
  }
}

function saveMetrics(m) {
  mkdirSync('debug/tegaki', { recursive: true });
  writeFileSync(METRICS, JSON.stringify(m, null, 1));
}

function pad(s, n) {
  s = String(s);
  return s.length >= n ? s.slice(0, n) : s + ' '.repeat(n - s.length);
}
function rpad(s, n) {
  s = String(s);
  return s.length >= n ? s : ' '.repeat(n - s.length) + s;
}

export function runSynth(opts, tag) {
  const files = readdirSync(SYNTH_DIR)
    .filter((f) => f.endsWith('.svg'))
    .sort();
  const rows = [];
  for (const f of files) {
    const name = f.replace(/\.svg$/, '');
    const svgText = readFileSync(`${SYNTH_DIR}/${f}`, 'utf8');
    const truth = JSON.parse(readFileSync(`${SYNTH_DIR}/${name}.truth.json`, 'utf8'));
    let r;
    try {
      r = convert(svgText, opts);
    } catch (err) {
      rows.push({ name, error: String(err.message || err) });
      continue;
    }
    const recon = scoreReconstruction(r.doc, r.strokes, 4);
    const cl = scoreCenterline(
      truth.centerlines,
      r.strokes.map((s) => s.points),
    );
    const truthWidth = Array.isArray(truth.width) ? (truth.width[0] + truth.width[1]) / 2 : truth.width;
    const widthErr = r.strokes.length ? +(complexity(r.strokes).widthMean - truthWidth).toFixed(2) : null;
    rows.push({ name, ...recon, centerline: cl, ...complexity(r.strokes), truthWidth, widthErr, ms: r.stats.ms });

    mkdirSync(`${OUT_DIR}/synth`, { recursive: true });
    writeFileSync(`${OUT_DIR}/synth/${name}${tag ? `.${tag}` : ''}.svg`, r.svg);
  }
  return rows;
}

export function runReal(opts, tag, only) {
  const rows = [];
  for (const name of only ?? REAL_LADDER) {
    const path = `inputs/${name}.svg`;
    if (!existsSync(path)) continue;
    const svgText = readFileSync(path, 'utf8');
    let r;
    try {
      r = convert(svgText, opts);
    } catch (err) {
      rows.push({ name, error: String(err.message || err) });
      continue;
    }
    const recon = scoreReconstruction(r.doc, r.strokes, 2);
    const es = r.stats.elementStats;
    const sum = (k) => es.reduce((a, e) => a + (e[k] ?? 0), 0);
    rows.push({
      name,
      ...recon,
      ...complexity(r.strokes),
      pruned: sum('prunedCount'),
      prunedLength: +sum('prunedLength').toFixed(1),
      droppedSingles: sum('droppedSingles'),
      crossingsSeen: sum('crossingsSeen'),
      crossingsStopped: sum('crossingsStopped'),
      ms: r.stats.ms,
    });

    mkdirSync(OUT_DIR, { recursive: true });
    mkdirSync(GRAPH_DIR, { recursive: true });
    writeFileSync(`${OUT_DIR}/${name}${tag ? `.${tag}` : ''}.svg`, r.svg);
    const errs = validateGraph(r.graph);
    if (errs.length) console.error(`  ! ${name} graph: ${errs.slice(0, 3).join('; ')}`);
    writeFileSync(`${GRAPH_DIR}/${name}${tag ? `.${tag}` : ''}.json`, JSON.stringify(r.graph, null, 1));
  }
  return rows;
}

function printSynth(rows, title) {
  console.log(`\n${title}`);
  console.log(
    pad('case', 24) + rpad('IoU', 7) + rpad('symDiff%', 10) + rpad('bdP95', 8) + rpad('cl_med', 8) + rpad('cl_P95', 8) + rpad('cl_Hd', 8) + rpad('strokes', 8) + rpad('wErr', 7),
  );
  for (const r of rows) {
    if (r.error) {
      console.log(pad(r.name, 24) + ' ERROR ' + r.error.slice(0, 60));
      continue;
    }
    console.log(
      pad(r.name, 24) +
        rpad(r.iou, 7) +
        rpad((r.symDiffFrac * 100).toFixed(1), 10) +
        rpad(r.boundaryP95, 8) +
        rpad(r.centerline.median ?? '-', 8) +
        rpad(r.centerline.p95 ?? '-', 8) +
        rpad(r.centerline.hausdorff ?? '-', 8) +
        rpad(r.strokeCount, 8) +
        rpad(r.widthErr ?? '-', 7),
    );
  }
  const ok = rows.filter((r) => !r.error && r.centerline.p95 !== null);
  if (ok.length) {
    const meanIoU = ok.reduce((s, r) => s + r.iou, 0) / ok.length;
    const medP95 = [...ok.map((r) => r.centerline.p95)].sort((a, b) => a - b)[ok.length >> 1];
    console.log(`  mean IoU ${meanIoU.toFixed(4)}   median centerline P95 ${medP95}`);
  }
}

function printReal(rows, title) {
  console.log(`\n${title}`);
  console.log(pad('image', 20) + rpad('IoU', 7) + rpad('symDiff%', 10) + rpad('miss%', 8) + rpad('extra%', 8) + rpad('bdMed', 7) + rpad('bdP95', 8) + rpad('strokes', 8) + rpad('pts', 7) + rpad('wCV', 7) + rpad('pruned', 8) + rpad('ms', 8));
  for (const r of rows) {
    if (r.error) {
      console.log(pad(r.name, 20) + ' ERROR ' + r.error.slice(0, 60));
      continue;
    }
    console.log(
      pad(r.name, 20) +
        rpad(r.iou, 7) +
        rpad((r.symDiffFrac * 100).toFixed(1), 10) +
        rpad((r.missingFrac * 100).toFixed(1), 8) +
        rpad((r.extraFrac * 100).toFixed(1), 8) +
        rpad(r.boundaryMedian, 7) +
        rpad(r.boundaryP95, 8) +
        rpad(r.strokeCount, 8) +
        rpad(r.pointCount, 7) +
        rpad(r.widthCV, 7) +
        rpad(r.pruned ?? '-', 8) +
        rpad(r.ms, 8),
    );
  }
  const ok = rows.filter((r) => !r.error);
  if (ok.length) console.log(`  mean IoU ${(ok.reduce((s, r) => s + r.iou, 0) / ok.length).toFixed(4)}`);
}

function main() {
  const { positional, opts } = parseArgs(process.argv.slice(2));
  const mode = positional[0] || 'synth';
  const tag = opts.tag || '';
  const runOpts = { ...DEFAULTS };
  for (const k of Object.keys(opts)) if (k in DEFAULTS) runOpts[k] = opts[k];

  const metrics = loadMetrics();
  const stamp = () => ({ options: runOpts, at: new Date().toISOString() });

  if (mode === 'synth') {
    const rows = runSynth(runOpts, tag);
    printSynth(rows, `synthetic corpus — ${tag || 'default'} (${runOpts.skeleton}/${runOpts.dt}/${runOpts.prune})`);
    metrics.runs[`synth:${tag || 'default'}`] = { ...stamp(), rows };
  } else if (mode === 'real') {
    const only = opts.only ? String(opts.only).split(',') : null;
    const rows = runReal(runOpts, tag, only);
    printReal(rows, `real ladder — ${tag || 'default'} (${runOpts.skeleton}/${runOpts.dt}/${runOpts.prune})`);
    metrics.runs[`real:${tag || 'default'}`] = { ...stamp(), rows };
  } else if (mode === 'ab') {
    // Tegaki's ready-made internal A/B: five skeletonizers on identical rasters.
    for (const sk of ['zhang-suen', 'guo-hall', 'lee', 'medial-axis', 'voronoi']) {
      const o = { ...runOpts, skeleton: sk };
      const rows = runSynth(o, sk);
      printSynth(rows, `synthetic — skeleton=${sk}`);
      metrics.runs[`synth:skeleton-${sk}`] = { options: o, at: new Date().toISOString(), rows };
    }
  } else if (mode === 'prune') {
    // The synthetic corpus is too clean to separate the pruners — there are
    // almost no spurious branches to remove. The A/B has to run on the real
    // ladder, where the medial axis actually sprouts them.
    const only = opts.only ? String(opts.only).split(',') : null;
    for (const p of ['none', 'tegaki-length', 'tegaki-width']) {
      const o = { ...runOpts, prune: p };
      const rows = runReal(o, `prune-${p}`, only);
      printReal(rows, `real — prune=${p}`);
      metrics.runs[`real:prune-${p}`] = { options: o, at: new Date().toISOString(), rows };
    }
  } else if (mode === 'prune-sweep') {
    // Pruning as model selection (report §10.2): sweep the width-aware
    // threshold and look at the fidelity/complexity trade-off.
    const only = opts.only ? String(opts.only).split(',') : null;
    for (const ratio of [0, 0.5, 1, 1.5, 2, 3, 4, 6]) {
      const o = { ...runOpts, prune: ratio === 0 ? 'none' : 'tegaki-width', spurWidthRatio: ratio };
      const rows = runReal(o, `sweep-${ratio}`, only);
      printReal(rows, `real — L/(2R) < ${ratio}`);
      metrics.runs[`real:sweep-${ratio}`] = { options: o, at: new Date().toISOString(), rows };
    }
  } else if (mode === 'ab-real') {
    const only = opts.only ? String(opts.only).split(',') : null;
    for (const sk of ['zhang-suen', 'guo-hall', 'lee', 'medial-axis', 'voronoi']) {
      const o = { ...runOpts, skeleton: sk };
      const rows = runReal(o, sk, only);
      printReal(rows, `real — skeleton=${sk}`);
      metrics.runs[`real:skeleton-${sk}`] = { options: o, at: new Date().toISOString(), rows };
    }
  } else {
    console.error(`unknown mode ${mode}`);
    process.exit(1);
  }

  saveMetrics(metrics);
  console.log(`\nwrote ${METRICS}`);
}

if (import.meta.url === `file://${process.argv[1]}`) main();
