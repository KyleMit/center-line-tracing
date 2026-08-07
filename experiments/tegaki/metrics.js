// Metrics (Common Setup §Metrics, report §11). Ours.
//
// Two families:
//   - RASTER re-stroke scoring: rasterize the original fill and the re-stroked
//     recovery on a common grid, then IoU / symmetric-difference / boundary
//     distance (median and P95 — never max). Uses our own deterministic
//     rasterizer so scores are reproducible (§15) and need no external binary.
//   - CENTERLINE error against the KNOWN source path — synthetic corpus only.
//     This is the measurement the real inputs cannot give us.

import { parseSvg } from './svg.js';
import { rasterize } from './raster.js';
import { computeDistanceTransform } from './dt.js';
import { strokeToFill } from './synth.js';

/** Rasterize a whole document's filled elements onto one shared grid. */
function rasterizeDoc(elements, bbox, scale) {
  const all = elements.flatMap((e) => e.subPaths);
  return rasterize(all, bbox, { scale, padding: 0 });
}

function unionBBox(...bboxes) {
  return bboxes.reduce((a, b) => ({
    x1: Math.min(a.x1, b.x1),
    y1: Math.min(a.y1, b.y1),
    x2: Math.max(a.x2, b.x2),
    y2: Math.max(a.y2, b.y2),
  }));
}

/**
 * Turn recovered strokes into filled outline rings so they can be rasterized.
 * Returns one GROUP per stroke, because a closed-loop stroke fills as an outer
 * ring minus an inner ring — rasterizing those two rings separately and OR-ing
 * them fills the hole, which read as a 130% symmetric difference on synthetic
 * case 06 until the grouping was fixed.
 */
function strokesToFillPaths(strokes) {
  return strokes.map((s) => {
    if (s.points.length === 1) {
      const p = s.points[0];
      const r = Math.max(s.width / 2, 0.01);
      const ring = [];
      for (let i = 0; i <= 24; i++) {
        const t = (i / 24) * 2 * Math.PI;
        ring.push({ x: p.x + Math.cos(t) * r, y: p.y + Math.sin(t) * r });
      }
      return [ring];
    }
    return strokeToFill(s.points, Math.max(s.width, 0.02), 'round', 'round');
  });
}

/**
 * Re-stroke scoring: IoU, symmetric-difference area, boundary distance.
 * `scale` is px per user unit for the comparison grid.
 */
export function scoreReconstruction(originalDoc, strokes, scale = 3) {
  const origBBox = originalDoc.elements.length
    ? unionBBox(...originalDoc.elements.map((e) => e.bbox))
    : { x1: 0, y1: 0, x2: 1, y2: 1 };
  const reconGroups = strokesToFillPaths(strokes);
  const reconRings = reconGroups.flat();
  const reconBBox = reconRings.length
    ? reconRings.reduce(
        (acc, r) => {
          for (const p of r) {
            acc.x1 = Math.min(acc.x1, p.x);
            acc.y1 = Math.min(acc.y1, p.y);
            acc.x2 = Math.max(acc.x2, p.x);
            acc.y2 = Math.max(acc.y2, p.y);
          }
          return acc;
        },
        { x1: Infinity, y1: Infinity, x2: -Infinity, y2: -Infinity },
      )
    : origBBox;

  const bbox = unionBBox(origBBox, reconBBox);
  const pad = 2 / scale;
  const grid = { x1: bbox.x1 - pad, y1: bbox.y1 - pad, x2: bbox.x2 + pad, y2: bbox.y2 + pad };

  // Elements are rasterized separately and OR-ed, so overlapping same-colour
  // elements do not cancel under the nonzero rule.
  const w = Math.ceil((grid.x2 - grid.x1) * scale);
  const h = Math.ceil((grid.y2 - grid.y1) * scale);
  const A = new Uint8Array(w * h);
  for (const e of originalDoc.elements) {
    const r = rasterize(e.subPaths, grid, { scale, padding: 0 });
    for (let i = 0; i < Math.min(A.length, r.bitmap.length); i++) if (r.bitmap[i]) A[i] = 1;
  }
  const B = new Uint8Array(w * h);
  for (const group of reconGroups) {
    const r = rasterize(group, grid, { scale, padding: 0 });
    for (let i = 0; i < Math.min(B.length, r.bitmap.length); i++) if (r.bitmap[i]) B[i] = 1;
  }

  let inter = 0;
  let union = 0;
  let aOnly = 0;
  let bOnly = 0;
  let aArea = 0;
  for (let i = 0; i < A.length; i++) {
    const a = A[i];
    const b = B[i];
    if (a) aArea++;
    if (a && b) inter++;
    if (a || b) union++;
    if (a && !b) aOnly++;
    if (!a && b) bOnly++;
  }

  // Boundary distance: for each boundary pixel of A, distance to the nearest
  // pixel of B's boundary, and vice versa; report the symmetric distribution.
  const bd = boundaryDistances(A, B, w, h);
  const px = 1 / scale;

  return {
    iou: union ? +(inter / union).toFixed(4) : 0,
    symDiffArea: +((aOnly + bOnly) * px * px).toFixed(2),
    symDiffFrac: aArea ? +((aOnly + bOnly) / aArea).toFixed(4) : 0,
    missingFrac: aArea ? +(aOnly / aArea).toFixed(4) : 0,
    extraFrac: aArea ? +(bOnly / aArea).toFixed(4) : 0,
    boundaryMedian: +(bd.median * px).toFixed(3),
    boundaryP95: +(bd.p95 * px).toFixed(3),
    gridScale: scale,
    gridSize: `${w}x${h}`,
  };
}

function boundaryOf(M, w, h) {
  const b = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      if (!M[i]) continue;
      const edge =
        x === 0 || x === w - 1 || y === 0 || y === h - 1 || !M[i - 1] || !M[i + 1] || !M[i - w] || !M[i + w];
      if (edge) b[i] = 1;
    }
  }
  return b;
}

function boundaryDistances(A, B, w, h) {
  const bA = boundaryOf(A, w, h);
  const bB = boundaryOf(B, w, h);
  const dA = computeDistanceTransform(bA, w, h, 'euclidean');
  const dB = computeDistanceTransform(bB, w, h, 'euclidean');
  const vals = [];
  for (let i = 0; i < w * h; i++) {
    if (bA[i]) vals.push(dB[i]);
    if (bB[i]) vals.push(dA[i]);
  }
  if (vals.length === 0) return { median: 0, p95: 0 };
  vals.sort((a, b) => a - b);
  return { median: vals[vals.length >> 1], p95: vals[Math.floor(vals.length * 0.95)] };
}

// ── Centerline error vs a known source path (synthetic only) ──────────────
function densify(pts, step = 0.5) {
  const out = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i];
    const b = pts[i + 1];
    const len = Math.hypot(b.x - a.x, b.y - a.y);
    const n = Math.max(1, Math.ceil(len / step));
    for (let k = 0; k < n; k++) out.push({ x: a.x + ((b.x - a.x) * k) / n, y: a.y + ((b.y - a.y) * k) / n });
  }
  out.push(pts[pts.length - 1]);
  return out;
}

function nearestDist(p, pts) {
  let best = Infinity;
  for (const q of pts) {
    const d = (p.x - q.x) ** 2 + (p.y - q.y) ** 2;
    if (d < best) best = d;
  }
  return Math.sqrt(best);
}

/**
 * Symmetric centerline error against the known truth: median, P95 and Hausdorff
 * (= max) of nearest-point distance in both directions. P95 is the headline;
 * max is reported only because the handoff asks for Hausdorff explicitly.
 */
export function scoreCenterline(truthPolylines, recoveredPolylines) {
  if (recoveredPolylines.length === 0 || truthPolylines.length === 0) {
    return { median: null, p95: null, hausdorff: null, note: 'no geometry' };
  }
  const T = truthPolylines.flatMap((p) => densify(p));
  const R = recoveredPolylines.flatMap((p) => densify(p));
  const d1 = T.map((p) => nearestDist(p, R));
  const d2 = R.map((p) => nearestDist(p, T));
  const all = [...d1, ...d2].sort((a, b) => a - b);
  return {
    median: +all[all.length >> 1].toFixed(3),
    p95: +all[Math.floor(all.length * 0.95)].toFixed(3),
    hausdorff: +all[all.length - 1].toFixed(3),
    truthToRecovered95: +[...d1].sort((a, b) => a - b)[Math.floor(d1.length * 0.95)].toFixed(3),
    recoveredToTruth95: +[...d2].sort((a, b) => a - b)[Math.floor(d2.length * 0.95)].toFixed(3),
  };
}

export function complexity(strokes) {
  const pts = strokes.reduce((s, x) => s + x.points.length, 0);
  const widths = strokes.map((s) => s.width).filter((w) => w > 0);
  const mean = widths.reduce((a, b) => a + b, 0) / (widths.length || 1);
  const sd = Math.sqrt(widths.reduce((a, b) => a + (b - mean) ** 2, 0) / (widths.length || 1));
  return {
    strokeCount: strokes.length,
    pointCount: pts,
    totalLength: +strokes.reduce((s, x) => s + x.length, 0).toFixed(2),
    widthMean: +mean.toFixed(3),
    widthCV: +(mean ? sd / mean : 0).toFixed(4),
  };
}

export { parseSvg };
