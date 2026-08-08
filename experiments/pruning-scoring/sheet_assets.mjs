// Render the input drawing and the recommended skimage-skan output to matched
// WebP pairs, for the before/after contact sheet.
//
//   node experiments/pruning-scoring/sheet_assets.mjs
//
// Both sides go through the SAME rasterizer at the SAME pixel size on the same
// white ground. A wipe comparison is only honest if the two halves differ by the
// thing being compared and nothing else — a different fit or background would
// show up as a seam at the wipe line and read as a difference in the output.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { Resvg } from '@resvg/resvg-js';
import sharp from 'sharp';

const REPO = new URL('../../', import.meta.url).pathname;
const DEBUG = `${REPO}debug/pruning-scoring`;
const LONG_EDGE = 820;

const manifest = JSON.parse(readFileSync(`${DEBUG}/recommended/manifest.json`, 'utf8'));

async function raster(svgPath, width, height) {
  const r = new Resvg(readFileSync(svgPath), {
    fitTo: { mode: 'width', value: width },
    background: 'white',
  });
  const png = r.render().asPng();
  const webp = await sharp(png).resize(width, height, { fit: 'fill' })
    .webp({ quality: 84, effort: 6 }).toBuffer();
  return `data:image/webp;base64,${webp.toString('base64')}`;
}

const out = [];
for (const rec of manifest) {
  const [, , vbw, vbh] = rec.viewBox;
  const ratio = vbw / vbh;
  const width = Math.round(ratio >= 1 ? LONG_EDGE : LONG_EDGE * ratio);
  const height = Math.round(width / ratio);

  const before = await raster(`${REPO}${rec.source}`, width, height);
  const after = await raster(`${REPO}${rec.svg}`, width, height);
  out.push({ ...rec, width, height, before, after });
  const kb = n => Math.round((n.length * 3) / 4 / 1024);
  console.log(`  ${rec.image.padEnd(18)} ${width}x${height}  ` +
              `before ${kb(before)} KB  after ${kb(after)} KB`);
}

mkdirSync(`${DEBUG}/recommended`, { recursive: true });
writeFileSync(`${DEBUG}/recommended/assets.json`, JSON.stringify(out));
const total = out.reduce((a, r) => a + r.before.length + r.after.length, 0);
console.log(`\n${out.length} pairs -> assets.json (${Math.round(total / 1024 / 1024 * 0.75)} MB of image data)`);
