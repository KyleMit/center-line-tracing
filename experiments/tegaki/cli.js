#!/usr/bin/env node
// CLI for the adapted Tegaki pipeline.
//   node experiments/tegaki/cli.js <input.svg> <output.svg> [--opt value ...]

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { convert, renderNormalized, DEFAULTS } from './pipeline.js';
import { validateGraph } from './graph.js';

const NUMERIC = new Set([
  'scale',
  'resolution',
  'spurWidthRatio',
  'spurMinLength',
  'rdpTolerance',
  'bezierTolerance',
  'lookback',
  'curvatureBias',
  'thinMaxIterations',
  'junctionCleanupIterations',
  'voronoiSamplingInterval',
  'mergeRadiusFactor',
  'capExtend',
  'minStrokeLength',
  'graphSnap',
]);

export function parseArgs(argv) {
  const positional = [];
  const opts = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) {
      positional.push(a);
      continue;
    }
    const key = a.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) {
      opts[key] = true;
      continue;
    }
    opts[key] = NUMERIC.has(key) ? Number(next) : next === 'true' ? true : next === 'false' ? false : next;
    i++;
  }
  return { positional, opts };
}

function main() {
  const { positional, opts } = parseArgs(process.argv.slice(2));
  const [input, output] = positional;
  if (!input) {
    console.error('usage: cli.js <input.svg> [output.svg] [--skeleton zhang-suen|guo-hall|lee|thin|medial-axis|voronoi]');
    console.error(`options: ${Object.keys(DEFAULTS).join(', ')}, graph, normalized, quiet`);
    process.exit(1);
  }

  const svgText = readFileSync(input, 'utf8');
  const result = convert(svgText, opts);

  if (output) {
    mkdirSync(dirname(output), { recursive: true });
    writeFileSync(output, result.svg);
  }
  if (opts.graph) {
    const p = typeof opts.graph === 'string' ? opts.graph : output.replace(/\.svg$/, '.json');
    mkdirSync(dirname(p), { recursive: true });
    writeFileSync(p, JSON.stringify(result.graph, null, 1));
    const errs = validateGraph(result.graph);
    if (errs.length) console.error(`graph validation: ${errs.length} problem(s)\n  ${errs.slice(0, 5).join('\n  ')}`);
  }
  if (opts.normalized) {
    const p = typeof opts.normalized === 'string' ? opts.normalized : output.replace(/\.svg$/, '.normalized.svg');
    mkdirSync(dirname(p), { recursive: true });
    writeFileSync(p, renderNormalized(result.doc));
  }

  if (!opts.quiet) {
    const s = result.stats;
    console.log(
      `${input}: ${s.elements} elements -> ${s.strokes} strokes (${s.dots} dots), ` +
        `total length ${s.totalLength}, median width ${s.medianWidth}, ${s.ms}ms`,
    );
    if (opts.verbose) {
      for (const e of s.elementStats) console.log(`  ${JSON.stringify(e)}`);
    }
  }
}

if (import.meta.url === `file://${process.argv[1]}`) main();
