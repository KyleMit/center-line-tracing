// Ray/bezier intersection — used to march a terminal MAT branch out to the
// shape boundary so the cap can be placed one radius behind the outline apex
// (the incumbent's `--calibrate-caps` rule, docs/current-attempt-handoff.md).

import { bezierAt } from './mat.mjs';

const EPS = 1e-9;

/** Real roots of a t^3 + b t^2 + c t + d = 0 in [0,1]. */
export function cubicRoots(a, b, c, d) {
  const out = [];
  const push = (t) => { if (t >= -1e-7 && t <= 1 + 1e-7) out.push(Math.min(1, Math.max(0, t))); };
  if (Math.abs(a) < EPS) {
    if (Math.abs(b) < EPS) {
      if (Math.abs(c) < EPS) return out;
      push(-d / c);
      return out;
    }
    const disc = c * c - 4 * b * d;
    if (disc < 0) return out;
    const s = Math.sqrt(disc);
    push((-c + s) / (2 * b));
    push((-c - s) / (2 * b));
    return out;
  }
  const A = b / a; const B = c / a; const C = d / a;
  const Q = (3 * B - A * A) / 9;
  const R = (9 * A * B - 27 * C - 2 * A * A * A) / 54;
  const D = Q * Q * Q + R * R;
  if (D >= 0) {
    const sq = Math.sqrt(D);
    const S = Math.cbrt(R + sq);
    const T = Math.cbrt(R - sq);
    push(-A / 3 + (S + T));
    if (Math.abs(S - T) < EPS) push(-A / 3 - (S + T) / 2);
  } else {
    const th = Math.acos(R / Math.sqrt(-(Q * Q * Q)));
    const r2 = 2 * Math.sqrt(-Q);
    push(-A / 3 + r2 * Math.cos(th / 3));
    push(-A / 3 + r2 * Math.cos((th + 2 * Math.PI) / 3));
    push(-A / 3 + r2 * Math.cos((th + 4 * Math.PI) / 3));
  }
  return out;
}

/** Bezier control points -> power-basis coefficients [c3,c2,c1,c0] per axis. */
function powerBasis(b) {
  if (b.length === 2) {
    return [
      [0, 0, b[1][0] - b[0][0], b[0][0]],
      [0, 0, b[1][1] - b[0][1], b[0][1]],
    ];
  }
  if (b.length === 3) {
    return [
      [0, b[0][0] - 2 * b[1][0] + b[2][0], 2 * (b[1][0] - b[0][0]), b[0][0]],
      [0, b[0][1] - 2 * b[1][1] + b[2][1], 2 * (b[1][1] - b[0][1]), b[0][1]],
    ];
  }
  return [
    [-b[0][0] + 3 * b[1][0] - 3 * b[2][0] + b[3][0], 3 * b[0][0] - 6 * b[1][0] + 3 * b[2][0], -3 * b[0][0] + 3 * b[1][0], b[0][0]],
    [-b[0][1] + 3 * b[1][1] - 3 * b[2][1] + b[3][1], 3 * b[0][1] - 6 * b[1][1] + 3 * b[2][1], -3 * b[0][1] + 3 * b[1][1], b[0][1]],
  ];
}

/**
 * Distance from `p` along unit direction `dir` to the first boundary crossing
 * of `loops`. Returns Infinity when the ray never leaves through a boundary.
 */
export function rayToBoundary(loops, p, dir, maxDist = Infinity) {
  // ray-local frame: u along dir, v perpendicular. Boundary crossing == v==0.
  const nx = -dir[1]; const ny = dir[0];
  let best = Infinity;
  for (const loop of loops) {
    for (const bez of loop) {
      const [cx, cy] = powerBasis(bez);
      // v(t) = n . (B(t) - p)
      const a = nx * cx[0] + ny * cy[0];
      const b = nx * cx[1] + ny * cy[1];
      const c = nx * cx[2] + ny * cy[2];
      const d = nx * (cx[3] - p[0]) + ny * (cy[3] - p[1]);
      for (const t of cubicRoots(a, b, c, d)) {
        const q = bezierAt(bez, t);
        const u = dir[0] * (q[0] - p[0]) + dir[1] * (q[1] - p[1]);
        if (u > 1e-7 && u < best && u <= maxDist) best = u;
      }
    }
  }
  return best;
}

/* ------------------------------------------------------- boundary distance
 * flo-mat gives an exact maximal-disk radius at every CpNode, but with
 * `simplify: true` those nodes can be 100+ units apart, so interpolating
 * between them badly overestimates the width near a junction bulge. Measuring
 * distance-to-boundary directly along the branch gives a dense, honest radius
 * profile. The boundary is flattened once and queried through a uniform grid.
 */
export function boundarySampler(loops, spacing = 0.4) {
  const pts = [];
  for (const loop of loops) {
    for (const bez of loop) {
      let len = 0; let prev = bez[0];
      for (let k = 1; k <= 16; k++) {
        const p = bezierAt(bez, k / 16);
        len += Math.hypot(p[0] - prev[0], p[1] - prev[1]); prev = p;
      }
      const n = Math.max(2, Math.ceil(len / spacing));
      for (let k = 0; k < n; k++) pts.push(bezierAt(bez, k / n));
    }
  }
  const cell = Math.max(spacing * 8, 1e-6);
  const grid = new Map();
  for (const p of pts) {
    const k = `${Math.floor(p[0] / cell)},${Math.floor(p[1] / cell)}`;
    let a = grid.get(k);
    if (!a) { a = []; grid.set(k, a); }
    a.push(p);
  }
  return {
    count: pts.length,
    /** Distance from `p` to the nearest sampled boundary point. */
    distance(p) {
      const gx = Math.floor(p[0] / cell); const gy = Math.floor(p[1] / cell);
      let best = Infinity;
      for (let ring = 0; ring < 256; ring++) {
        let any = false;
        for (let dx = -ring; dx <= ring; dx++) {
          for (let dy = -ring; dy <= ring; dy++) {
            if (ring > 0 && Math.abs(dx) !== ring && Math.abs(dy) !== ring) continue;
            const arr = grid.get(`${gx + dx},${gy + dy}`);
            if (!arr) continue;
            any = true;
            for (const q of arr) {
              const d = Math.hypot(q[0] - p[0], q[1] - p[1]);
              if (d < best) best = d;
            }
          }
        }
        if (any && best <= ring * cell) break;
        if (ring > 4 && best < Infinity && best <= (ring - 1) * cell) break;
      }
      return best;
    },
  };
}

/** Even-odd/nonzero-agnostic point-in-loops test by ray casting. */
export function pointInLoops(loops, p) {
  let crossings = 0;
  const dir = [1, 0];
  for (const loop of loops) {
    for (const bez of loop) {
      const [cx, cy] = powerBasis(bez);
      const a = -cy[0]; const b = -cy[1]; const c = -cy[2]; const d = -(cy[3] - p[1]);
      for (const t of cubicRoots(a, b, c, d)) {
        const q = bezierAt(bez, t);
        if (q[0] - p[0] > 1e-9) crossings++;
      }
    }
  }
  return crossings % 2 === 1;
}
