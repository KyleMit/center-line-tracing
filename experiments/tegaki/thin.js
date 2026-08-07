// Ported from Tegaki packages/generator/src/processing/skeletonize/*.ts
// (MIT, see VENDOR.md). All five raster skeletonizers, behind one signature,
// which is what makes Tegaki a ready-made internal A/B.

/** 8-connected neighbour offsets, clockwise from N. */
export const DX = [0, 1, 1, 1, 0, -1, -1, -1];
export const DY = [-1, -1, 0, 1, 1, 1, 0, -1];

export function degree(x, y, skel, w, h) {
  let count = 0;
  for (let i = 0; i < 8; i++) {
    const nx = x + DX[i];
    const ny = y + DY[i];
    if (nx >= 0 && nx < w && ny >= 0 && ny < h && skel[ny * w + nx]) count++;
  }
  return count;
}

// ── Zhang-Suen (1984) ──────────────────────────────────────────────────────
export function zhangSuenThin(bitmap, width, height) {
  const result = new Uint8Array(bitmap);
  const get = (x, y) => (x < 0 || x >= width || y < 0 || y >= height ? 0 : result[y * width + x]);

  let changed = true;
  while (changed) {
    changed = false;
    for (const sub of [0, 1]) {
      const toDelete = [];
      for (let y = 1; y < height - 1; y++) {
        for (let x = 1; x < width - 1; x++) {
          if (result[y * width + x] === 0) continue;
          const p2 = get(x, y - 1);
          const p3 = get(x + 1, y - 1);
          const p4 = get(x + 1, y);
          const p5 = get(x + 1, y + 1);
          const p6 = get(x, y + 1);
          const p7 = get(x - 1, y + 1);
          const p8 = get(x - 1, y);
          const p9 = get(x - 1, y - 1);
          const B = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9;
          if (B < 2 || B > 6) continue;
          const seq = [p2, p3, p4, p5, p6, p7, p8, p9];
          let A = 0;
          for (let i = 0; i < 8; i++) if (seq[i] === 0 && seq[(i + 1) % 8] === 1) A++;
          if (A !== 1) continue;
          if (sub === 0) {
            if (p2 * p4 * p6 !== 0) continue;
            if (p4 * p6 * p8 !== 0) continue;
          } else {
            if (p2 * p4 * p8 !== 0) continue;
            if (p2 * p6 * p8 !== 0) continue;
          }
          toDelete.push(y * width + x);
        }
      }
      for (const idx of toDelete) {
        result[idx] = 0;
        changed = true;
      }
    }
  }
  return result;
}

// ── Guo-Hall (1989) ────────────────────────────────────────────────────────
// Paired-neighbour counting: N = min(N1, N2). Comment in Tegaki claims thinner
// diagonals and different junction topology than Zhang-Suen.
export function guoHallThin(bitmap, width, height) {
  const result = new Uint8Array(bitmap);
  const get = (x, y) => (x < 0 || x >= width || y < 0 || y >= height ? 0 : result[y * width + x]);

  let changed = true;
  while (changed) {
    changed = false;
    for (const sub of [0, 1]) {
      const toDelete = [];
      for (let y = 1; y < height - 1; y++) {
        for (let x = 1; x < width - 1; x++) {
          if (result[y * width + x] === 0) continue;
          const p2 = get(x, y - 1);
          const p3 = get(x + 1, y - 1);
          const p4 = get(x + 1, y);
          const p5 = get(x + 1, y + 1);
          const p6 = get(x, y + 1);
          const p7 = get(x - 1, y + 1);
          const p8 = get(x - 1, y);
          const p9 = get(x - 1, y - 1);

          // Guo-Hall naming: p2=N, p3=NE, p4=E, p5=SE, p6=S, p7=SW, p8=W, p9=NW.
          // These four conditions are transcribed from the reference formulation
          // (as in OpenCV's ximgproc thinning). Getting the C-term grouping
          // wrong — pairing !p4 with (p3|p5) instead of !p2 with (p3|p4) —
          // produced a skeleton that scored 0.62 mean IoU on the synthetic
          // corpus, so this is worth checking rather than eyeballing.
          const C =
            (!p2 && (p3 || p4) ? 1 : 0) +
            (!p4 && (p5 || p6) ? 1 : 0) +
            (!p6 && (p7 || p8) ? 1 : 0) +
            (!p8 && (p9 || p2) ? 1 : 0);
          if (C !== 1) continue;

          const N1 = (p9 || p2 ? 1 : 0) + (p3 || p4 ? 1 : 0) + (p5 || p6 ? 1 : 0) + (p7 || p8 ? 1 : 0);
          const N2 = (p2 || p3 ? 1 : 0) + (p4 || p5 ? 1 : 0) + (p6 || p7 ? 1 : 0) + (p8 || p9 ? 1 : 0);
          const N = Math.min(N1, N2);
          if (N < 2 || N > 3) continue;

          const m = sub === 0 ? (p6 || p7 || !p9) && p8 : (p2 || p3 || !p5) && p4;
          if (m) continue;
          toDelete.push(y * width + x);
        }
      }
      for (const idx of toDelete) {
        result[idx] = 0;
        changed = true;
      }
    }
  }
  return result;
}

// ── Lee (1994) / morphological, via a shared 256-entry removal LUT ─────────
export const BORDER_DIRS = [
  { dx: 0, dy: -1 },
  { dx: 0, dy: 1 },
  { dx: 1, dy: 0 },
  { dx: -1, dy: 0 },
  { dx: 1, dy: -1 },
  { dx: -1, dy: 1 },
  { dx: 1, dy: 1 },
  { dx: -1, dy: -1 },
];

export const REMOVAL_LUT = (() => {
  const lut = new Uint8Array(256);
  for (let i = 0; i < 256; i++) {
    const p = [];
    for (let b = 0; b < 8; b++) p.push((i >> b) & 1);
    const B = p.reduce((a, b) => a + b, 0);
    if (B < 2 || B > 6) continue;
    let A = 0;
    for (let j = 0; j < 8; j++) if (p[j] === 0 && p[(j + 1) % 8] === 1) A++;
    if (A === 1) lut[i] = 1;
  }
  return lut;
})();

export function encodeNeighborhood(x, y, bmp, width, height) {
  const get = (nx, ny) => (nx < 0 || nx >= width || ny < 0 || ny >= height ? 0 : bmp[ny * width + nx]);
  // P2..P9 -> bits 0..7, clockwise from N
  return (
    get(x, y - 1) |
    (get(x + 1, y - 1) << 1) |
    (get(x + 1, y) << 2) |
    (get(x + 1, y + 1) << 3) |
    (get(x, y + 1) << 4) |
    (get(x - 1, y + 1) << 5) |
    (get(x - 1, y) << 6) |
    (get(x - 1, y - 1) << 7)
  );
}

export function morphologicalThin(bitmap, width, height, maxIterations) {
  const result = new Uint8Array(bitmap);
  for (let iter = 0; iter < maxIterations; iter++) {
    let changed = false;
    for (const dir of BORDER_DIRS) {
      const toDelete = [];
      for (let y = 1; y < height - 1; y++) {
        for (let x = 1; x < width - 1; x++) {
          const idx = y * width + x;
          if (result[idx] === 0) continue;
          const nx = x + dir.dx;
          const ny = y + dir.dy;
          if (nx >= 0 && nx < width && ny >= 0 && ny < height && result[ny * width + nx] !== 0) continue;
          if (REMOVAL_LUT[encodeNeighborhood(x, y, result, width, height)]) toDelete.push(idx);
        }
      }
      for (const idx of toDelete) {
        result[idx] = 0;
        changed = true;
      }
    }
    if (!changed) break;
  }
  return result;
}

export function leeThin(bitmap, width, height) {
  return morphologicalThin(bitmap, width, height, Infinity);
}

// ── Distance-ordered homotopic thinning ("medial-axis") ───────────────────
// The most transferable ~30 lines in the repository: turns any distance field
// into a medial-axis-accurate skeleton. Removes pixels boundary-inward ordered
// by DT ascending, keeping only simple points (crossing number A(P) == 1), so
// high-DT (medial) pixels are the last to be considered and survive.
export function medialAxisThin(bitmap, dt, width, height) {
  const result = new Uint8Array(bitmap);
  const pixels = [];
  for (let i = 0; i < result.length; i++) if (result[i]) pixels.push(i);
  pixels.sort((a, b) => dt[a] - dt[b]);

  for (const idx of pixels) {
    if (!result[idx]) continue;
    const x = idx % width;
    const y = (idx - x) / width;
    if (degree(x, y, result, width, height) <= 1) continue; // never delete endpoints
    if (isSimplePoint(x, y, result, width, height)) result[idx] = 0;
  }
  return result;
}

function isSimplePoint(x, y, bitmap, width, height) {
  const get = (nx, ny) => (nx < 0 || nx >= width || ny < 0 || ny >= height ? 0 : bitmap[ny * width + nx]);
  const seq = [
    get(x, y - 1),
    get(x + 1, y - 1),
    get(x + 1, y),
    get(x + 1, y + 1),
    get(x, y + 1),
    get(x - 1, y + 1),
    get(x - 1, y),
    get(x - 1, y - 1),
  ];
  let transitions = 0;
  for (let i = 0; i < 8; i++) if (seq[i] === 0 && seq[(i + 1) % 8] === 1) transitions++;
  return transitions === 1;
}
