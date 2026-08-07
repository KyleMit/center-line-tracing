// Ported from Tegaki packages/generator/src/processing/width.ts (MIT, see VENDOR.md).
// Both transforms are ported because Tegaki's choice between them is itself a
// finding: it ships the APPROXIMATE chamfer transform by default, on the stated
// grounds that the exact EDT's sharper ridges make the argmax in junction-cluster
// cleanup noisier. See debug/tegaki/NOTES.md.

export function computeDistanceTransform(bitmap, width, height, method = 'chamfer') {
  return method === 'chamfer' ? computeChamferDT(bitmap, width, height) : computeEuclideanDT(bitmap, width, height);
}

function computeChamferDT(bitmap, width, height) {
  const dist = new Float32Array(width * height);
  const INF = width + height;
  for (let i = 0; i < bitmap.length; i++) dist[i] = bitmap[i] ? 0 : INF;

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = y * width + x;
      if (dist[idx] === 0) continue;
      if (y > 0) dist[idx] = Math.min(dist[idx], dist[(y - 1) * width + x] + 1);
      if (x > 0) dist[idx] = Math.min(dist[idx], dist[y * width + (x - 1)] + 1);
      if (y > 0 && x > 0) dist[idx] = Math.min(dist[idx], dist[(y - 1) * width + (x - 1)] + Math.SQRT2);
      if (y > 0 && x < width - 1) dist[idx] = Math.min(dist[idx], dist[(y - 1) * width + (x + 1)] + Math.SQRT2);
    }
  }
  for (let y = height - 1; y >= 0; y--) {
    for (let x = width - 1; x >= 0; x--) {
      const idx = y * width + x;
      if (dist[idx] === 0) continue;
      if (y < height - 1) dist[idx] = Math.min(dist[idx], dist[(y + 1) * width + x] + 1);
      if (x < width - 1) dist[idx] = Math.min(dist[idx], dist[y * width + (x + 1)] + 1);
      if (y < height - 1 && x < width - 1) dist[idx] = Math.min(dist[idx], dist[(y + 1) * width + (x + 1)] + Math.SQRT2);
      if (y < height - 1 && x > 0) dist[idx] = Math.min(dist[idx], dist[(y + 1) * width + (x - 1)] + Math.SQRT2);
    }
  }
  return dist;
}

/** Exact EDT, Felzenszwalb & Huttenlocher lower-envelope-of-parabolas. */
function computeEuclideanDT(bitmap, width, height) {
  const INF = 1e20;
  const size = width * height;
  const d = new Float32Array(size);
  for (let i = 0; i < size; i++) d[i] = bitmap[i] ? 0 : INF;

  const maxDim = Math.max(width, height);
  const v = new Int32Array(maxDim);
  const z = new Float32Array(maxDim + 1);
  const f = new Float32Array(maxDim);
  const out = new Float32Array(maxDim);

  for (let x = 0; x < width; x++) {
    for (let y = 0; y < height; y++) f[y] = d[y * width + x];
    edt1d(f, out, height, v, z);
    for (let y = 0; y < height; y++) d[y * width + x] = out[y];
  }
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) f[x] = d[y * width + x];
    edt1d(f, out, width, v, z);
    for (let x = 0; x < width; x++) d[y * width + x] = out[x];
  }
  for (let i = 0; i < size; i++) d[i] = Math.sqrt(d[i]);
  return d;
}

function edt1d(f, out, n, v, z) {
  v[0] = 0;
  z[0] = -1e20;
  z[1] = 1e20;
  let k = 0;
  for (let q = 1; q < n; q++) {
    let s;
    while (true) {
      const vk = v[k];
      s = (f[q] + q * q - (f[vk] + vk * vk)) / (2 * q - 2 * vk);
      if (s > z[k]) break;
      k--;
    }
    k++;
    v[k] = q;
    z[k] = s;
    z[k + 1] = 1e20;
  }
  k = 0;
  for (let q = 0; q < n; q++) {
    while (z[k + 1] < q) k++;
    const vk = v[k];
    const dq = q - vk;
    out[q] = dq * dq + f[vk];
  }
}

/** Distance from each inside pixel to the nearest outside pixel = local inscribed radius. */
export function computeInverseDistanceTransform(bitmap, width, height, method = 'chamfer') {
  const inverted = new Uint8Array(bitmap.length);
  for (let i = 0; i < bitmap.length; i++) inverted[i] = bitmap[i] ? 0 : 1;
  return computeDistanceTransform(inverted, width, height, method);
}

/** Tegaki's width lookup: diameter at a skeleton pixel, from the inverse DT. */
export function getStrokeWidth(x, y, inverseDT, width, height) {
  const rx = Math.min(width - 1, Math.max(0, Math.round(x)));
  const ry = Math.min(height - 1, Math.max(0, Math.round(y)));
  return (inverseDT[ry * width + rx] ?? 0) * 2;
}

/** Bilinear sample of the radius field — sub-pixel, used for cap extension. */
export function sampleRadius(x, y, inverseDT, width, height) {
  const x0 = Math.floor(x);
  const y0 = Math.floor(y);
  const fx = x - x0;
  const fy = y - y0;
  const at = (ix, iy) => {
    const cx = Math.min(width - 1, Math.max(0, ix));
    const cy = Math.min(height - 1, Math.max(0, iy));
    return inverseDT[cy * width + cx] ?? 0;
  };
  return (
    at(x0, y0) * (1 - fx) * (1 - fy) + at(x0 + 1, y0) * fx * (1 - fy) + at(x0, y0 + 1) * (1 - fx) * fy + at(x0 + 1, y0 + 1) * fx * fy
  );
}
