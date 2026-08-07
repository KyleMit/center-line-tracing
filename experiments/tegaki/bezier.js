// Ported from Tegaki packages/generator/src/processing/bezier.ts (MIT, see VENDOR.md).
// Adaptive de Casteljau flattening by midpoint-deviation, verbatim in behaviour.
//
// ADAPTED: Tegaki only ever sees opentype.js output, so it handles M/L/Q/C/Z with
// absolute coordinates and nothing else. Real SVG needs relative commands, H/V,
// the smooth forms S/T, and arcs — `A` appears 958 times across our ten inputs.
// Arc flattening (endpoint -> centre parameterization, then sampled) is ours.

import { BEZIER_TOLERANCE } from './constants.js';

function distSq(a, b) {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return dx * dx + dy * dy;
}

function midpoint(a, b) {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

function subdivideQuadratic(p0, p1, p2, tolerance, result) {
  const mid = {
    x: 0.25 * p0.x + 0.5 * p1.x + 0.25 * p2.x,
    y: 0.25 * p0.y + 0.5 * p1.y + 0.25 * p2.y,
  };
  if (distSq(mid, midpoint(p0, p2)) < tolerance * tolerance) {
    result.push(p2);
  } else {
    const q0 = midpoint(p0, p1);
    const q1 = midpoint(p1, p2);
    subdivideQuadratic(p0, q0, mid, tolerance, result);
    subdivideQuadratic(mid, q1, p2, tolerance, result);
  }
}

function subdivideCubic(p0, p1, p2, p3, tolerance, result) {
  const mid = {
    x: 0.125 * p0.x + 0.375 * p1.x + 0.375 * p2.x + 0.125 * p3.x,
    y: 0.125 * p0.y + 0.375 * p1.y + 0.375 * p2.y + 0.125 * p3.y,
  };
  if (distSq(mid, midpoint(p0, p3)) < tolerance * tolerance) {
    result.push(p3);
  } else {
    const q0 = midpoint(p0, p1);
    const q1 = midpoint(p1, p2);
    const q2 = midpoint(p2, p3);
    const r0 = midpoint(q0, q1);
    const r1 = midpoint(q1, q2);
    const s = midpoint(r0, r1);
    subdivideCubic(p0, q0, r0, s, tolerance, result);
    subdivideCubic(s, r1, q2, p3, tolerance, result);
  }
}

/** SVG endpoint-parameterized elliptical arc -> polyline. Appends to `result`. */
function flattenArc(p0, rx, ry, xAxisRotationDeg, largeArc, sweep, p1, tolerance, result) {
  if (rx === 0 || ry === 0) {
    result.push(p1);
    return;
  }
  rx = Math.abs(rx);
  ry = Math.abs(ry);
  const phi = (xAxisRotationDeg * Math.PI) / 180;
  const cosPhi = Math.cos(phi);
  const sinPhi = Math.sin(phi);

  const dx2 = (p0.x - p1.x) / 2;
  const dy2 = (p0.y - p1.y) / 2;
  const x1p = cosPhi * dx2 + sinPhi * dy2;
  const y1p = -sinPhi * dx2 + cosPhi * dy2;

  // Scale radii up if they are too small to span the chord (SVG F.6.6)
  const lambda = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry);
  if (lambda > 1) {
    const s = Math.sqrt(lambda);
    rx *= s;
    ry *= s;
  }

  const num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p;
  const den = rx * rx * y1p * y1p + ry * ry * x1p * x1p;
  let coef = den === 0 ? 0 : Math.sqrt(Math.max(0, num / den));
  if (largeArc === sweep) coef = -coef;
  const cxp = (coef * rx * y1p) / ry;
  const cyp = (-coef * ry * x1p) / rx;

  const cx = cosPhi * cxp - sinPhi * cyp + (p0.x + p1.x) / 2;
  const cy = sinPhi * cxp + cosPhi * cyp + (p0.y + p1.y) / 2;

  const angle = (ux, uy, vx, vy) => {
    const dot = ux * vx + uy * vy;
    const len = Math.sqrt(ux * ux + uy * uy) * Math.sqrt(vx * vx + vy * vy);
    let a = Math.acos(Math.max(-1, Math.min(1, len === 0 ? 1 : dot / len)));
    if (ux * vy - uy * vx < 0) a = -a;
    return a;
  };

  const theta1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry);
  let dTheta = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry);
  if (!sweep && dTheta > 0) dTheta -= 2 * Math.PI;
  else if (sweep && dTheta < 0) dTheta += 2 * Math.PI;

  // Segment count from the sagitta bound: err ~ R * (1 - cos(dt/2))
  const rMax = Math.max(rx, ry);
  const maxStep = 2 * Math.acos(Math.max(-1, Math.min(1, 1 - tolerance / Math.max(rMax, 1e-9))));
  const segments = Math.max(2, Math.ceil(Math.abs(dTheta) / Math.max(maxStep, 1e-3)));

  for (let i = 1; i <= segments; i++) {
    const t = theta1 + (dTheta * i) / segments;
    const ct = Math.cos(t);
    const st = Math.sin(t);
    result.push({
      x: cx + cosPhi * rx * ct - sinPhi * ry * st,
      y: cy + sinPhi * rx * ct + cosPhi * ry * st,
    });
  }
}

const NUMBER_RE = /[+-]?(?:\d*\.\d+|\d+\.?)(?:[eE][+-]?\d+)?/g;
const ARG_COUNT = { M: 2, L: 2, H: 1, V: 1, C: 6, S: 4, Q: 4, T: 2, A: 7, Z: 0 };

/** Tokenize a path `d` string into [{ cmd, args }]. */
export function parsePathData(d) {
  const out = [];
  const re = /([MmLlHhVvCcSsQqTtAaZz])([^MmLlHhVvCcSsQqTtAaZz]*)/g;
  let m;
  while ((m = re.exec(d)) !== null) {
    const cmd = m[1];
    const nums = (m[2].match(NUMBER_RE) || []).map(Number);
    const n = ARG_COUNT[cmd.toUpperCase()];
    if (n === 0) {
      out.push({ cmd, args: [] });
      continue;
    }
    // Repeated argument sets: implicit repeat (M becomes L, m becomes l)
    let first = true;
    for (let i = 0; i + n <= nums.length; i += n) {
      let c = cmd;
      if (!first && cmd === 'M') c = 'L';
      else if (!first && cmd === 'm') c = 'l';
      out.push({ cmd: c, args: nums.slice(i, i + n) });
      first = false;
    }
  }
  return out;
}

/**
 * Flatten an SVG path `d` into closed/open polyline sub-paths.
 * Mirrors Tegaki's flattenPath: `Z` pushes an explicit copy of the sub-path
 * start, so every closed ring satisfies first === last (the rasterizer relies
 * on this).
 */
export function flattenPathData(d, tolerance = BEZIER_TOLERANCE) {
  const cmds = parsePathData(d);
  const subPaths = [];
  let current = [];
  let cursor = { x: 0, y: 0 };
  let subPathStart = { x: 0, y: 0 };
  let lastCubicCtl = null;
  let lastQuadCtl = null;

  const push = (p) => {
    current.push(p);
    cursor = p;
  };

  for (const { cmd, args: a } of cmds) {
    const rel = cmd === cmd.toLowerCase() && cmd !== 'Z' && cmd !== 'z';
    const C = cmd.toUpperCase();
    const rx = rel ? cursor.x : 0;
    const ry = rel ? cursor.y : 0;
    let isCubic = false;
    let isQuad = false;

    switch (C) {
      case 'M': {
        if (current.length > 0) subPaths.push(current);
        current = [];
        const p = { x: a[0] + rx, y: a[1] + ry };
        current.push(p);
        cursor = p;
        subPathStart = { ...p };
        break;
      }
      case 'L':
        push({ x: a[0] + rx, y: a[1] + ry });
        break;
      case 'H':
        push({ x: a[0] + rx, y: cursor.y });
        break;
      case 'V':
        push({ x: cursor.x, y: a[0] + ry });
        break;
      case 'C': {
        const c1 = { x: a[0] + rx, y: a[1] + ry };
        const c2 = { x: a[2] + rx, y: a[3] + ry };
        const end = { x: a[4] + rx, y: a[5] + ry };
        subdivideCubic(cursor, c1, c2, end, tolerance, current);
        cursor = end;
        lastCubicCtl = c2;
        isCubic = true;
        break;
      }
      case 'S': {
        const c1 = lastCubicCtl ? { x: 2 * cursor.x - lastCubicCtl.x, y: 2 * cursor.y - lastCubicCtl.y } : { ...cursor };
        const c2 = { x: a[0] + rx, y: a[1] + ry };
        const end = { x: a[2] + rx, y: a[3] + ry };
        subdivideCubic(cursor, c1, c2, end, tolerance, current);
        cursor = end;
        lastCubicCtl = c2;
        isCubic = true;
        break;
      }
      case 'Q': {
        const c1 = { x: a[0] + rx, y: a[1] + ry };
        const end = { x: a[2] + rx, y: a[3] + ry };
        subdivideQuadratic(cursor, c1, end, tolerance, current);
        cursor = end;
        lastQuadCtl = c1;
        isQuad = true;
        break;
      }
      case 'T': {
        const c1 = lastQuadCtl ? { x: 2 * cursor.x - lastQuadCtl.x, y: 2 * cursor.y - lastQuadCtl.y } : { ...cursor };
        const end = { x: a[0] + rx, y: a[1] + ry };
        subdivideQuadratic(cursor, c1, end, tolerance, current);
        cursor = end;
        lastQuadCtl = c1;
        isQuad = true;
        break;
      }
      case 'A': {
        const end = { x: a[5] + rx, y: a[6] + ry };
        flattenArc(cursor, a[0], a[1], a[2], a[3] !== 0, a[4] !== 0, end, tolerance, current);
        cursor = end;
        break;
      }
      case 'Z': {
        if (current.length > 0) {
          current.push({ ...subPathStart });
          subPaths.push(current);
          current = [];
        }
        cursor = { ...subPathStart };
        break;
      }
    }
    if (!isCubic) lastCubicCtl = null;
    if (!isQuad) lastQuadCtl = null;
  }

  if (current.length > 0) subPaths.push(current);
  return subPaths.filter((p) => p.length >= 2);
}

export function computePathBBox(subPaths) {
  let x1 = Infinity;
  let y1 = Infinity;
  let x2 = -Infinity;
  let y2 = -Infinity;
  for (const path of subPaths) {
    for (const p of path) {
      if (p.x < x1) x1 = p.x;
      if (p.y < y1) y1 = p.y;
      if (p.x > x2) x2 = p.x;
      if (p.y > y2) y2 = p.y;
    }
  }
  return { x1, y1, x2, y2 };
}
