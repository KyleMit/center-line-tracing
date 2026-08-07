// Rasterize one SVG to a PNG at a fixed pixel width, for contact sheets.
// Kept separate from rasterize.mjs so the mask-rasterization contract in that
// file stays exactly what the pipeline consumes and nothing else.
//
// usage: node render_one.mjs <width>   (job JSON on stdin, same shape as rasterize.mjs)

import { createRequire } from 'node:module';
import { writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

const require = createRequire(import.meta.url);
const { Resvg } = require('@resvg/resvg-js');

const width = Number(process.argv[2] ?? 900);
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const job = JSON.parse(Buffer.concat(chunks).toString('utf8'));

mkdirSync(job.outDir, { recursive: true });
for (const item of job.jobs) {
  const resvg = new Resvg(item.svg, {
    fitTo: { mode: 'width', value: width },
    font: { loadSystemFonts: false },
  });
  writeFileSync(join(job.outDir, `${item.id}.png`), resvg.render().asPng());
}
process.stdout.write('{"ok":true}');
