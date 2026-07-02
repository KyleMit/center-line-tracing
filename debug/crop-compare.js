#!/usr/bin/env node
// Render two SVGs at high resolution, crop the same viewBox-space region from
// each, and write a magnified side-by-side PNG for close inspection of tips.
// Usage: node debug/crop-compare.js a.svg b.svg cx cy size out.png [renderPx]
const sharp = require('sharp');
const { PNG } = require('pngjs');
const fs = require('fs');

const [A, B, CX, CY, SIZE, OUT] = process.argv.slice(2);
const RENDER = Number(process.argv[8] || 2400);

async function renderCrop(file, cx, cy, size) {
  const svg = fs.readFileSync(file, 'utf8');
  const vb = svg.match(/viewBox\s*=\s*"([^"]+)"/i)[1].trim().split(/[\s,]+/).map(Number);
  const scale = RENDER / Math.max(vb[2], vb[3]);
  const px = Math.round((cx - size / 2 - vb[0]) * scale);
  const py = Math.round((cy - size / 2 - vb[1]) * scale);
  const pw = Math.round(size * scale);
  const buf = await sharp(file, { density: 96 * scale })
    .resize(Math.round(vb[2] * scale), Math.round(vb[3] * scale), { fit: 'fill' })
    .flatten({ background: '#fff' })
    .extract({
      left: Math.max(0, px),
      top: Math.max(0, py),
      width: pw,
      height: pw,
    })
    .ensureAlpha()
    .raw()
    .toBuffer();
  return { buf, pw };
}

async function main() {
  const cx = Number(CX), cy = Number(CY), size = Number(SIZE);
  const [a, b] = await Promise.all([renderCrop(A, cx, cy, size), renderCrop(B, cx, cy, size)]);
  const w = a.pw;
  const gap = 8;
  const out = new PNG({ width: w * 2 + gap, height: w });
  out.data.fill(220);
  for (let y = 0; y < w; y++) {
    for (let x = 0; x < w; x++) {
      const src = (y * w + x) * 4;
      a.buf.copy(out.data, (y * (w * 2 + gap) + x) * 4, src, src + 4);
      b.buf.copy(out.data, (y * (w * 2 + gap) + w + gap + x) * 4, src, src + 4);
    }
  }
  fs.writeFileSync(OUT, PNG.sync.write(out));
  console.log(`wrote ${OUT} (${w * 2 + gap}x${w})`);
}
main().catch((e) => { console.error(e); process.exit(1); });
