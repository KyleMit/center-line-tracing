// Contact sheets: HTML (for reading) + PNG (for viewing without a browser).
// Columns: input | output | diff | overlay.

import fs from 'node:fs';
import { PNG } from 'pngjs';
import { renderRGBA } from './raster.mjs';

function compose(w, h) {
  const png = new PNG({ width: w, height: h });
  png.data.fill(255);
  return png;
}

function blit(dst, src, ox, oy, { alpha = 1, tint = null, onWhite = true } = {}) {
  for (let y = 0; y < src.height; y++) {
    const dy = oy + y;
    if (dy < 0 || dy >= dst.height) continue;
    for (let x = 0; x < src.width; x++) {
      const dx = ox + x;
      if (dx < 0 || dx >= dst.width) continue;
      const si = (y * src.width + x) * 4;
      const di = (dy * dst.width + dx) * 4;
      let r = src.data[si]; let g = src.data[si + 1]; let b = src.data[si + 2];
      let a = (src.data[si + 3] / 255) * alpha;
      if (tint) { r = tint[0]; g = tint[1]; b = tint[2]; }
      if (onWhite) {
        // src is premultiplied-over-white already if it came from renderRGBA
      }
      dst.data[di] = Math.round(dst.data[di] * (1 - a) + r * a);
      dst.data[di + 1] = Math.round(dst.data[di + 1] * (1 - a) + g * a);
      dst.data[di + 2] = Math.round(dst.data[di + 2] * (1 - a) + b * a);
      dst.data[di + 3] = 255;
    }
  }
}

/* ------------------------------------------------------------- tiny 5x7 font */
const GLYPHS = {
  ' ': '00000,00000,00000,00000,00000,00000,00000',
  '0': '01110,10001,10011,10101,11001,10001,01110',
  '1': '00100,01100,00100,00100,00100,00100,01110',
  '2': '01110,10001,00001,00010,00100,01000,11111',
  '3': '11111,00010,00100,00010,00001,10001,01110',
  '4': '00010,00110,01010,10010,11111,00010,00010',
  '5': '11111,10000,11110,00001,00001,10001,01110',
  '6': '00110,01000,10000,11110,10001,10001,01110',
  '7': '11111,00001,00010,00100,01000,01000,01000',
  '8': '01110,10001,10001,01110,10001,10001,01110',
  '9': '01110,10001,10001,01111,00001,00010,01100',
  '.': '00000,00000,00000,00000,00000,01100,01100',
  ',': '00000,00000,00000,00000,01100,01100,11000',
  '%': '11001,11010,00010,00100,01000,01011,10011',
  '-': '00000,00000,00000,11111,00000,00000,00000',
  '=': '00000,00000,11111,00000,11111,00000,00000',
  ':': '00000,01100,01100,00000,01100,01100,00000',
  '/': '00001,00010,00010,00100,01000,01000,10000',
  '(': '00010,00100,01000,01000,01000,00100,00010',
  ')': '01000,00100,00010,00010,00010,00100,01000',
  '+': '00000,00100,00100,11111,00100,00100,00000',
  '_': '00000,00000,00000,00000,00000,00000,11111',
  A: '01110,10001,10001,11111,10001,10001,10001',
  B: '11110,10001,10001,11110,10001,10001,11110',
  C: '01110,10001,10000,10000,10000,10001,01110',
  D: '11100,10010,10001,10001,10001,10010,11100',
  E: '11111,10000,10000,11110,10000,10000,11111',
  F: '11111,10000,10000,11110,10000,10000,10000',
  G: '01110,10001,10000,10111,10001,10001,01111',
  H: '10001,10001,10001,11111,10001,10001,10001',
  I: '01110,00100,00100,00100,00100,00100,01110',
  J: '00111,00010,00010,00010,00010,10010,01100',
  K: '10001,10010,10100,11000,10100,10010,10001',
  L: '10000,10000,10000,10000,10000,10000,11111',
  M: '10001,11011,10101,10101,10001,10001,10001',
  N: '10001,11001,10101,10011,10001,10001,10001',
  O: '01110,10001,10001,10001,10001,10001,01110',
  P: '11110,10001,10001,11110,10000,10000,10000',
  Q: '01110,10001,10001,10001,10101,10010,01101',
  R: '11110,10001,10001,11110,10100,10010,10001',
  S: '01111,10000,10000,01110,00001,00001,11110',
  T: '11111,00100,00100,00100,00100,00100,00100',
  U: '10001,10001,10001,10001,10001,10001,01110',
  V: '10001,10001,10001,10001,10001,01010,00100',
  W: '10001,10001,10001,10101,10101,11011,10001',
  X: '10001,10001,01010,00100,01010,10001,10001',
  Y: '10001,10001,01010,00100,00100,00100,00100',
  Z: '11111,00001,00010,00100,01000,10000,11111',
};

export function drawText(png, text, x, y, scale = 2, color = [20, 20, 20]) {
  let cx = x;
  for (const ch of String(text)) {
    const g = GLYPHS[ch.toUpperCase()] || GLYPHS[' '];
    const rows = g.split(',');
    for (let r = 0; r < rows.length; r++) {
      for (let c = 0; c < rows[r].length; c++) {
        if (rows[r][c] !== '1') continue;
        for (let sy = 0; sy < scale; sy++) {
          for (let sx = 0; sx < scale; sx++) {
            const px = cx + c * scale + sx; const py = y + r * scale + sy;
            if (px < 0 || py < 0 || px >= png.width || py >= png.height) continue;
            const i = (py * png.width + px) * 4;
            png.data[i] = color[0]; png.data[i + 1] = color[1]; png.data[i + 2] = color[2]; png.data[i + 3] = 255;
          }
        }
      }
    }
    cx += (5 + 1) * scale;
  }
}

function fillRect(png, x, y, w, h, color) {
  for (let j = y; j < y + h; j++) {
    if (j < 0 || j >= png.height) continue;
    for (let i = x; i < x + w; i++) {
      if (i < 0 || i >= png.width) continue;
      const o = (j * png.width + i) * 4;
      png.data[o] = color[0]; png.data[o + 1] = color[1]; png.data[o + 2] = color[2]; png.data[o + 3] = 255;
    }
  }
}

/** Red/blue diff image of two rendered alphas. */
function diffImage(a, b) {
  const out = { width: a.width, height: a.height, data: Buffer.alloc(a.width * a.height * 4, 255) };
  for (let i = 0, p = 0; i < a.width * a.height; i++, p += 4) {
    const x = a.data[p + 3] > 127; const y = b.data[p + 3] > 127;
    if (x && y) { out.data[p] = 220; out.data[p + 1] = 220; out.data[p + 2] = 220; }
    else if (x) { out.data[p] = 214; out.data[p + 1] = 40; out.data[p + 2] = 40; }     // missing
    else if (y) { out.data[p] = 40; out.data[p + 1] = 90; out.data[p + 2] = 214; }     // extra
    out.data[p + 3] = 255;
  }
  return out;
}

/**
 * Build a comparison sheet PNG.
 * @param rows [{label, inputSvg, outputSvg, note}]
 */
export function comparisonSheet(rows, { tile = 420, pad = 8, header = 30 } = {}) {
  const cols = 4;
  const rendered = rows.map((row) => ({
    row,
    inImg: renderRGBA(row.inputSvg, tile),
    outImg: renderRGBA(row.outputSvg, tile),
  }));
  const heights = rendered.map((r) => Math.max(r.inImg.height, r.outImg.height) + 30);
  const total = heights.reduce((a, b) => a + b + pad, 0);
  const png = compose(cols * (tile + pad) + pad, total + header + pad);
  fillRect(png, 0, 0, png.width, png.height, [246, 246, 248]);
  drawText(png, 'INPUT', pad + 4, 8, 2, [90, 90, 100]);
  drawText(png, 'OUTPUT', pad + tile + pad + 4, 8, 2, [90, 90, 100]);
  drawText(png, 'DIFF  RED=MISSING BLUE=EXTRA', pad + 2 * (tile + pad) + 4, 8, 2, [90, 90, 100]);
  drawText(png, 'OVERLAY  RED=RECOVERED', pad + 3 * (tile + pad) + 4, 8, 2, [90, 90, 100]);

  let y = header;
  rendered.forEach(({ row, inImg, outImg }, ri) => {
    const h = heights[ri] - 30;
    for (let c = 0; c < cols; c++) fillRect(png, pad + c * (tile + pad), y, tile, h, [255, 255, 255]);
    blit(png, inImg, pad, y);
    blit(png, outImg, pad + (tile + pad), y);
    blit(png, diffImage(inImg, outImg), pad + 2 * (tile + pad), y);
    blit(png, inImg, pad + 3 * (tile + pad), y, { alpha: 0.4, tint: [120, 120, 120] });
    blit(png, outImg, pad + 3 * (tile + pad), y, { alpha: 1, tint: [220, 20, 20] });
    drawText(png, row.label, pad + 2, y + h + 2, 2);
    if (row.note) drawText(png, row.note, pad + 2, y + h + 15, 2, [70, 70, 90]);
    y += heights[ri] + pad;
  });
  return png;
}

export function writeSheet(file, png) {
  fs.writeFileSync(file, PNG.sync.write(png));
}

/** Progress sheet: one tile per iteration, chronological. */
export function progressSheet(items, { tile = 420, pad = 8, cols = 4 } = {}) {
  const rows = Math.ceil(items.length / cols);
  const rowH = tile + 34;
  const png = compose(cols * (tile + pad) + pad, rows * rowH + pad);
  fillRect(png, 0, 0, png.width, png.height, [246, 246, 248]);
  items.forEach((it, i) => {
    const cx = pad + (i % cols) * (tile + pad);
    const cy = pad + Math.floor(i / cols) * rowH;
    const img = renderRGBA(it.svg, tile);
    fillRect(png, cx, cy, tile, Math.min(tile, img.height), [255, 255, 255]);
    if (it.underlay) blit(png, renderRGBA(it.underlay, tile), cx, cy, { alpha: 0.35, tint: [130, 130, 130] });
    blit(png, img, cx, cy, it.tint ? { tint: it.tint } : {});
    drawText(png, it.tag, cx + 2, cy + Math.min(tile, img.height) + 4, 2);
    if (it.score) drawText(png, it.score, cx + 2, cy + Math.min(tile, img.height) + 16, 2, [70, 70, 90]);
  });
  return png;
}

export function htmlSheet(title, rows) {
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  return `<!doctype html><meta charset="utf-8"><title>${esc(title)}</title>
<style>
body{font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;background:#f6f6f8;color:#222;margin:16px}
h1{font-size:16px}
table{border-collapse:collapse}
td,th{border:1px solid #ddd;padding:4px;vertical-align:top;background:#fff}
img{display:block;width:420px;background:#fff}
.lbl{font-weight:700}
.m{color:#555;font-size:12px;white-space:pre}
</style>
<h1>${esc(title)}</h1>
<table><tr><th>case</th><th>input</th><th>output</th><th>diff</th><th>overlay</th><th>metrics</th></tr>
${rows.map((r) => `<tr><td class="lbl">${esc(r.label)}</td>
<td><img src="${r.input}"></td><td><img src="${r.output}"></td>
<td><img src="${r.diff}"></td><td><img src="${r.overlay}"></td>
<td class="m">${esc(r.metrics)}</td></tr>`).join('\n')}
</table>`;
}

export { renderRGBA, diffImage, blit, fillRect, compose };
