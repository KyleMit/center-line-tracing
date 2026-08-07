#!/usr/bin/env node
// Zoomed crops of the worst-reconstructed regions (Common Setup asks for the
// two or three worst regions on the comparison sheet).
//
//   node experiments/flo-mat/zoom.mjs house-wide [n] [renderWidth]

import fs from 'node:fs';
import path from 'node:path';
import { PNG } from 'pngjs';
import { renderRGBA, drawText, fillRect, blit, compose } from './lib/sheet.mjs';

const name = process.argv[2] || 'house-wide';
const N = Number(process.argv[3] || 3);
const RW = Number(process.argv[4] || 2200);
const CROP = 240;          // source pixels per crop
const ZOOM = 2;

const inputSvg = fs.readFileSync(`inputs/${name}.svg`, 'utf8');
const outSvg = fs.readFileSync(`outputs/flo-mat/${name}.svg`, 'utf8');
const a = renderRGBA(inputSvg, RW);
const b = renderRGBA(outSvg, RW);

// score a coarse grid of tiles by symmetric difference
const TILE = 60;
const cols = Math.ceil(a.width / TILE); const rowsN = Math.ceil(a.height / TILE);
const score = new Float64Array(cols * rowsN);
for (let y = 0; y < a.height; y++) {
  for (let x = 0; x < a.width; x++) {
    const i = (y * a.width + x) * 4;
    const p = a.data[i + 3] > 127; const q = b.data[i + 3] > 127;
    if (p !== q) score[Math.floor(y / TILE) * cols + Math.floor(x / TILE)]++;
  }
}
// pick top N tiles, keeping them apart
const order = [...score.keys()].sort((i, j) => score[j] - score[i]);
const picks = [];
for (const idx of order) {
  if (picks.length >= N || score[idx] === 0) break;
  const cx = (idx % cols) * TILE + TILE / 2; const cy = Math.floor(idx / cols) * TILE + TILE / 2;
  if (picks.some((p) => Math.hypot(p.cx - cx, p.cy - cy) < CROP)) continue;
  picks.push({ cx, cy, score: score[idx] });
}

const crop = (img, cx, cy) => {
  const half = CROP / 2;
  const x0 = Math.max(0, Math.min(img.width - CROP, Math.round(cx - half)));
  const y0 = Math.max(0, Math.min(img.height - CROP, Math.round(cy - half)));
  const out = { width: CROP * ZOOM, height: CROP * ZOOM, data: Buffer.alloc(CROP * ZOOM * CROP * ZOOM * 4, 255) };
  for (let y = 0; y < CROP * ZOOM; y++) {
    for (let x = 0; x < CROP * ZOOM; x++) {
      const si = ((y0 + Math.floor(y / ZOOM)) * img.width + (x0 + Math.floor(x / ZOOM))) * 4;
      const di = (y * out.width + x) * 4;
      img.data.copy(out.data, di, si, si + 4);
    }
  }
  return out;
};

const W = CROP * ZOOM;
const png = compose(3 * (W + 8) + 8, picks.length * (W + 34) + 34);
fillRect(png, 0, 0, png.width, png.height, [246, 246, 248]);
drawText(png, `${name}  WORST REGIONS  INPUT / OUTPUT / OVERLAY`, 8, 10, 2, [60, 60, 70]);
picks.forEach((p, i) => {
  const y = 34 + i * (W + 34);
  const ca = crop(a, p.cx, p.cy); const cb = crop(b, p.cx, p.cy);
  for (let c = 0; c < 3; c++) fillRect(png, 8 + c * (W + 8), y, W, W, [255, 255, 255]);
  blit(png, ca, 8, y);
  blit(png, cb, 8 + (W + 8), y);
  blit(png, ca, 8 + 2 * (W + 8), y, { alpha: 0.35, tint: [120, 120, 120] });
  blit(png, cb, 8 + 2 * (W + 8), y, { tint: [220, 20, 20] });
  drawText(png, `${Math.round(p.cx)},${Math.round(p.cy)} @${RW}PX  DIFFPX ${p.score}`, 10, y + W + 6, 2, [70, 70, 90]);
});
const out = path.join('debug/flo-mat', `zoom-${name}.png`);
fs.writeFileSync(out, PNG.sync.write(png));
console.log(`-> ${out}  regions=${picks.map((p) => p.score).join(',')}`);
