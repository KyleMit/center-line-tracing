#!/usr/bin/env node
// Deterministic SVG -> RGBA raster via resvg (report §7.1, §15).
//
// Reads newline-delimited JSON jobs on stdin, one per line:
//   {"svg": "<svg .../>", "width": 1234, "height": 567, "out": "/path/to.raw"}
// Writes a raw RGBA8 buffer to `out` and echoes {"out":..,"w":..,"h":..} per job.
// Kept as a long-lived process so a 40-element drawing costs one node startup.
import { Resvg } from '@resvg/resvg-js';
import fs from 'fs';
import readline from 'readline';

const rl = readline.createInterface({ input: process.stdin });
for await (const line of rl) {
  const s = line.trim();
  if (!s) continue;
  const job = JSON.parse(s);
  const r = new Resvg(job.svg, {
    fitTo: { mode: 'width', value: job.width },
    background: 'rgba(0,0,0,0)',
    shapeRendering: 2, // geometricPrecision
  });
  const img = r.render();
  fs.writeFileSync(job.out, Buffer.from(img.pixels));
  process.stdout.write(JSON.stringify({ out: job.out, w: img.width, h: img.height }) + '\n');
}
