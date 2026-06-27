#!/usr/bin/env node
// Render two SVGs to the same canvas and report pixel similarity.
// Usage: node compare.js a.svg b.svg [size] [diff.png]
const sharp = require('sharp');
const { PNG } = require('pngjs');
const pixelmatch = require('pixelmatch').default || require('pixelmatch');

const A = process.argv[2] || 'input.svg';
const B = process.argv[3] || 'output.svg';
const SIZE = Number(process.argv[4] || 700);
const DIFF = process.argv[5] || 'scratch_diff.png';

async function render(file) {
  const buf = await sharp(file, { density: 96 })
    .resize(SIZE, SIZE, { fit: 'contain', background: '#fff' })
    .flatten({ background: '#fff' })
    .ensureAlpha()
    .raw()
    .toBuffer();
  return buf;
}

async function main() {
  const [a, b] = await Promise.all([render(A), render(B)]);
  const diff = new PNG({ width: SIZE, height: SIZE });
  const mismatch = pixelmatch(a, b, diff.data, SIZE, SIZE, {
    threshold: 0.1,
    diffColor: [255, 0, 0],
  });
  const total = SIZE * SIZE;
  const pct = (mismatch / total) * 100;
  PNG.sync.write(diff); // ensure buffer valid
  require('fs').writeFileSync(DIFF, PNG.sync.write(diff));
  console.log(`${A} vs ${B} @ ${SIZE}px`);
  console.log(`differing pixels: ${mismatch}/${total} = ${pct.toFixed(2)}%`);
  console.log(`similarity: ${(100 - pct).toFixed(2)}%   diff -> ${DIFF}`);
}
main().catch(e => { console.error(e); process.exit(1); });
