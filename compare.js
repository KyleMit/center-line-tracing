#!/usr/bin/env node
// Render two SVGs to the same canvas and report pixel similarity.
// Usage: node compare.js a.svg b.svg [size] [diff.png] [side-by-side.png]
const sharp = require('sharp');
const { PNG } = require('pngjs');
const pixelmatch = require('pixelmatch').default || require('pixelmatch');

const A = process.argv[2] || 'inputs/landscape.svg';
const B = process.argv[3] || 'outputs/landscape.svg';
const SIZE = Number(process.argv[4] || 700);
const DIFF = process.argv[5] || 'scratch_diff.png';
const SIDE_BY_SIDE = process.argv[6];

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

  if (SIDE_BY_SIDE) {
    const sideBySide = new PNG({ width: SIZE * 2, height: SIZE });

    for (let y = 0; y < SIZE; y++) {
      for (let x = 0; x < SIZE; x++) {
        const sourceOffset = (y * SIZE + x) * 4;
        const leftOffset = (y * SIZE * 2 + x) * 4;
        const rightOffset = (y * SIZE * 2 + SIZE + x) * 4;

        a.copy(sideBySide.data, leftOffset, sourceOffset, sourceOffset + 4);
        b.copy(sideBySide.data, rightOffset, sourceOffset, sourceOffset + 4);
      }
    }

    require('fs').writeFileSync(SIDE_BY_SIDE, PNG.sync.write(sideBySide));
  }

  console.log(`${A} vs ${B} @ ${SIZE}px`);
  console.log(`differing pixels: ${mismatch}/${total} = ${pct.toFixed(2)}%`);
  console.log(`similarity: ${(100 - pct).toFixed(2)}%   diff -> ${DIFF}`);
  if (SIDE_BY_SIDE) console.log(`side-by-side -> ${SIDE_BY_SIDE}`);
}
main().catch(e => { console.error(e); process.exit(1); });
