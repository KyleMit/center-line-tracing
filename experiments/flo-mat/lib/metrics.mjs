// Reconstruction + centerline metrics (report §11).

import { renderMask, maskArea, maskCompare, boundaryDistance } from './raster.mjs';

/** Render both SVGs onto the same canvas and score the reconstruction. */
export function scoreReconstruction(originalSvg, reconSvg, { width = 1200, units = 1 } = {}) {
  const a = renderMask(originalSvg, width);
  const b = renderMask(reconSvg, width);
  const cmp = maskCompare(a, b);
  const areaA = maskArea(a);
  const bd = boundaryDistance(a, b, units);
  return {
    iou: cmp.iou,
    symDiffPx: cmp.symDiff,
    symDiffFrac: areaA ? cmp.symDiff / areaA : 0,
    missingFrac: areaA ? cmp.missing / areaA : 0,
    extraFrac: areaA ? cmp.extra / areaA : 0,
    pixelDiffPct: (cmp.symDiff / (a.width * a.height)) * 100,
    boundaryMedian: bd.median,
    boundaryP95: bd.p95,
    rasterWidth: a.width,
    rasterHeight: a.height,
  };
}

/* -------------------------------------------------- centerline vs. truth */

function buildGrid(points, cell) {
  const grid = new Map();
  for (const p of points) {
    const k = `${Math.floor(p[0] / cell)},${Math.floor(p[1] / cell)}`;
    let a = grid.get(k);
    if (!a) { a = []; grid.set(k, a); }
    a.push(p);
  }
  return { grid, cell };
}

function nearest(gridObj, p) {
  const { grid, cell } = gridObj;
  const gx = Math.floor(p[0] / cell); const gy = Math.floor(p[1] / cell);
  let best = Infinity;
  for (let ring = 0; ring < 64; ring++) {
    let found = false;
    for (let dx = -ring; dx <= ring; dx++) {
      for (let dy = -ring; dy <= ring; dy++) {
        if (ring > 0 && Math.abs(dx) !== ring && Math.abs(dy) !== ring) continue;
        const arr = grid.get(`${gx + dx},${gy + dy}`);
        if (!arr) continue;
        found = true;
        for (const q of arr) {
          const d = Math.hypot(q[0] - p[0], q[1] - p[1]);
          if (d < best) best = d;
        }
      }
    }
    if (found && best <= ring * cell) break;
  }
  return best;
}

const pct = (sorted, p) => (sorted.length
  ? sorted[Math.min(sorted.length - 1, Math.max(0, Math.round((p / 100) * (sorted.length - 1))))]
  : 0);

/**
 * Directed and symmetric distance between the recovered centerline points and
 * the known source path (synthetic corpus only).
 *   recoveredToTruth — "did we draw anything that isn't a real centerline?"
 *   truthToRecovered — "did we cover the whole real centerline?"
 */
export function centerlineError(recovered, truth) {
  if (!recovered.length || !truth.length) {
    return { median: NaN, p95: NaN, hausdorff: NaN, coverMedian: NaN, coverP95: NaN };
  }
  const cell = 8;
  const gt = buildGrid(truth, cell);
  const gr = buildGrid(recovered, cell);
  const a = recovered.map((p) => nearest(gt, p)).sort((x, y) => x - y);
  const b = truth.map((p) => nearest(gr, p)).sort((x, y) => x - y);
  return {
    median: pct(a, 50),
    p95: pct(a, 95),
    max: a[a.length - 1],
    coverMedian: pct(b, 50),
    coverP95: pct(b, 95),
    hausdorff: Math.max(a[a.length - 1], b[b.length - 1]),
  };
}
