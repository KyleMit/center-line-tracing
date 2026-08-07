#!/usr/bin/env node
// Does cap calibration (march to the outline apex, step back one radius) help
// on real artwork, and does it interact with SAT pruning?
import fs from 'node:fs';
import { normalizeSvg } from './lib/normalize.mjs';
import { runDocumentAsync } from './lib/pipeline.mjs';
import { comparePixelDiff } from './lib/metrics.mjs';

const names = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const list = names.length ? names : ['sun-square', 'house-wide', 'landscape-square', 'dinosaur-wide'];
const out = [];
for (const name of list) {
  const src = `inputs/${name}.svg`;
  const doc = normalizeSvg(fs.readFileSync(src, 'utf8'));
  for (const caps of ['none', 'apex']) {
    for (const sat of [null, 1.3]) {
      const r = await runDocumentAsync(doc, { caps, satSweep: sat }, { timeoutMs: 25000 });
      const f = `debug/flo-mat/recon/abl-${name}-${caps}-${sat}.svg`;
      fs.writeFileSync(f, r.svg);
      const c = await comparePixelDiff(src, f, 1200);
      const line = `${name.padEnd(17)} caps=${caps.padEnd(5)} sat=${String(sat).padEnd(5)}`
        + ` compare.js=${c.pct.toFixed(3)}%  strokes=${r.complexity.strokes}`
        + ` len=${r.complexity.totalLength.toFixed(0)}`
        + ` failedEl=${r.perElement.filter((p) => p.error).length}`;
      out.push(line);
      console.log(line);
    }
  }
}
fs.writeFileSync('debug/flo-mat/cap-ablation.txt', `${out.join('\n')}\n`);
console.log('-> debug/flo-mat/cap-ablation.txt');
