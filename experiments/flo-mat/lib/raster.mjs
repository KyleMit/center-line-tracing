// Deterministic rasterization (report §7.1 / §15) via resvg, plus the binary
// mask + distance-transform primitives the metrics need.

import fs from 'node:fs';
import { Resvg } from '@resvg/resvg-js';
import { PNG } from 'pngjs';

/** Render an SVG string to RGBA at a fixed pixel width. Deterministic. */
export function renderRGBA(svg, width) {
  const r = new Resvg(svg, {
    fitTo: { mode: 'width', value: Math.round(width) },
    background: 'rgba(255,255,255,0)',
    shapeRendering: 2,   // geometricPrecision
    imageRendering: 0,
  });
  const png = PNG.sync.read(Buffer.from(r.render().asPng()));
  return { data: png.data, width: png.width, height: png.height };
}

/** Alpha > 127 becomes 1. */
export function toMask(img) {
  const { data, width, height } = img;
  const m = new Uint8Array(width * height);
  for (let i = 0, p = 3; i < m.length; i++, p += 4) m[i] = data[p] > 127 ? 1 : 0;
  return { m, width, height };
}

export function renderMask(svg, width) {
  return toMask(renderRGBA(svg, width));
}

export function maskArea(mask) {
  let a = 0;
  for (let i = 0; i < mask.m.length; i++) a += mask.m[i];
  return a;
}

/** IoU + symmetric difference between two equal-size masks. */
export function maskCompare(a, b) {
  let inter = 0; let union = 0; let onlyA = 0; let onlyB = 0;
  const n = Math.min(a.m.length, b.m.length);
  for (let i = 0; i < n; i++) {
    const x = a.m[i]; const y = b.m[i];
    if (x && y) inter++;
    if (x || y) union++;
    if (x && !y) onlyA++;
    if (!x && y) onlyB++;
  }
  return {
    iou: union ? inter / union : 1,
    intersection: inter,
    union,
    symDiff: onlyA + onlyB,
    missing: onlyA,   // in original, not reconstructed
    extra: onlyB,     // in reconstruction, not original
  };
}

/* -------------------------------------------------- exact Euclidean distance
 * Felzenszwalb & Huttenlocher squared-EDT, O(n) per row/column.
 */
function edt1d(f, n) {
  const d = new Float64Array(n);
  const v = new Int32Array(n);
  const z = new Float64Array(n + 1);
  let k = 0;
  v[0] = 0; z[0] = -Infinity; z[1] = Infinity;
  for (let q = 1; q < n; q++) {
    let s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]);
    while (s <= z[k]) {
      k--;
      s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k]);
    }
    k++;
    v[k] = q; z[k] = s; z[k + 1] = Infinity;
  }
  k = 0;
  for (let q = 0; q < n; q++) {
    while (z[k + 1] < q) k++;
    d[q] = (q - v[k]) * (q - v[k]) + f[v[k]];
  }
  return d;
}

/** Distance (in pixels) from every pixel to the nearest pixel where seed==1. */
export function distanceTransform(seed, width, height) {
  const INF = 1e12;
  const f = new Float64Array(Math.max(width, height));
  const out = new Float64Array(width * height);
  for (let i = 0; i < out.length; i++) out[i] = seed[i] ? 0 : INF;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) f[x] = out[y * width + x];
    const d = edt1d(f, width);
    for (let x = 0; x < width; x++) out[y * width + x] = d[x];
  }
  for (let x = 0; x < width; x++) {
    for (let y = 0; y < height; y++) f[y] = out[y * width + x];
    const d = edt1d(f, height);
    for (let y = 0; y < height; y++) out[y * width + x] = Math.sqrt(d[y]);
  }
  return out;
}

/** Boundary pixels of a mask (4-connected edge). */
export function boundaryPixels(mask) {
  const { m, width, height } = mask;
  const b = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = y * width + x;
      if (!m[i]) continue;
      if (x === 0 || y === 0 || x === width - 1 || y === height - 1
        || !m[i - 1] || !m[i + 1] || !m[i - width] || !m[i + width]) b[i] = 1;
    }
  }
  return b;
}

function percentile(sorted, p) {
  if (!sorted.length) return 0;
  const i = Math.min(sorted.length - 1, Math.max(0, Math.round((p / 100) * (sorted.length - 1))));
  return sorted[i];
}

/**
 * Symmetric boundary distance between two masks, in *source units*.
 * Reports median and P95 (never max — report §11.1).
 */
export function boundaryDistance(a, b, unitsPerPixel = 1) {
  const ba = boundaryPixels(a);
  const bb = boundaryPixels(b);
  const da = distanceTransform(ba, a.width, a.height);
  const db = distanceTransform(bb, b.width, b.height);
  const vals = [];
  for (let i = 0; i < ba.length; i++) {
    if (ba[i]) vals.push(db[i]);
    if (bb[i]) vals.push(da[i]);
  }
  vals.sort((p, q) => p - q);
  return {
    median: percentile(vals, 50) * unitsPerPixel,
    p95: percentile(vals, 95) * unitsPerPixel,
    mean: (vals.reduce((s, v) => s + v, 0) / (vals.length || 1)) * unitsPerPixel,
    count: vals.length,
  };
}

export function writePng(path, img) {
  const png = new PNG({ width: img.width, height: img.height });
  Buffer.from(img.data).copy(png.data);
  fs.writeFileSync(path, PNG.sync.write(png));
}
