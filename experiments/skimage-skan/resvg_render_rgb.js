#!/usr/bin/env node
// Same protocol as resvg_render.js but writes a PNG, for contact sheets.
const fs = require('fs');
const { Resvg } = require('@resvg/resvg-js');

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (c) => (data += c));
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

async function main() {
  const { jobs } = JSON.parse(await readStdin());
  const out = [];
  for (const job of jobs) {
    const resvg = new Resvg(job.svg, {
      fitTo: { mode: 'width', value: job.width },
      background: '#ffffff',
      shapeRendering: 2,
    });
    fs.writeFileSync(job.out, resvg.render().asPng());
    out.push({ out: job.out });
  }
  process.stdout.write(JSON.stringify({ results: out }));
}

main().catch((e) => {
  process.stderr.write(String((e && e.stack) || e));
  process.exit(1);
});
