// A small analytic vector stroker used ONLY to build the synthetic ground-truth
// corpus (report §12.1): given a known centerline made of line and circular-arc
// pieces, produce the exact filled outline the centerline would have produced.
//
// Implemented as a boolean union of per-piece slabs + join wedges + cap shapes,
// which sidesteps offset self-intersection at corners. Paper.js does the union
// and emits cubic Beziers, so the corpus is genuinely curved vector geometry
// (not a densified polygon) — which is the input class flo-mat is designed for.

import paper from 'paper/dist/paper-core.js';

paper.setup(new paper.Size(2000, 2000));

const TAU = Math.PI * 2;

export const L = (p0, p1) => ({ type: 'line', p0, p1 });
/** Arc piece. Angles in degrees, measured in the SVG (y-down) frame. */
export const A = (cx, cy, r, a0, a1) => ({ type: 'arc', c: [cx, cy], r, a0: (a0 * Math.PI) / 180, a1: (a1 * Math.PI) / 180 });

const at = (c, r, a) => [c[0] + r * Math.cos(a), c[1] + r * Math.sin(a)];

export function pieceStart(p) { return p.type === 'line' ? p.p0 : at(p.c, p.r, p.a0); }
export function pieceEnd(p) { return p.type === 'line' ? p.p1 : at(p.c, p.r, p.a1); }

function unit(v) { const l = Math.hypot(v[0], v[1]) || 1; return [v[0] / l, v[1] / l]; }

export function pieceTangent(p, atEnd) {
  if (p.type === 'line') return unit([p.p1[0] - p.p0[0], p.p1[1] - p.p0[1]]);
  const a = atEnd ? p.a1 : p.a0;
  const s = p.a1 >= p.a0 ? 1 : -1;
  return [-Math.sin(a) * s, Math.cos(a) * s];
}

export function pieceLength(p) {
  return p.type === 'line'
    ? Math.hypot(p.p1[0] - p.p0[0], p.p1[1] - p.p0[1])
    : Math.abs(p.a1 - p.a0) * p.r;
}

export function samplePiece(p, n) {
  const out = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    out.push(p.type === 'line'
      ? [p.p0[0] + (p.p1[0] - p.p0[0]) * t, p.p0[1] + (p.p1[1] - p.p0[1]) * t]
      : at(p.c, p.r, p.a0 + (p.a1 - p.a0) * t));
  }
  return out;
}

/** Dense polyline of a whole centerline, for ground-truth distance metrics. */
export function sampleCenterline(pieces, spacing = 0.5) {
  const pts = [];
  pieces.forEach((p, i) => {
    const n = Math.max(2, Math.ceil(pieceLength(p) / spacing));
    const s = samplePiece(p, n);
    pts.push(...(i === 0 ? s : s.slice(1)));
  });
  return pts;
}

/* ------------------------------------------------------------- paper parts */

function paperArc(cx, cy, r, a0, a1) {
  const path = new paper.Path();
  path.moveTo(new paper.Point(at([cx, cy], r, a0)));
  appendArc(path, cx, cy, r, a0, a1);
  return path;
}

function appendArc(path, cx, cy, r, a0, a1) {
  const steps = Math.max(1, Math.ceil(Math.abs(a1 - a0) / (Math.PI / 2)));
  for (let i = 0; i < steps; i++) {
    const s = a0 + ((a1 - a0) * i) / steps;
    const e = a0 + ((a1 - a0) * (i + 1)) / steps;
    path.arcTo(new paper.Point(at([cx, cy], r, (s + e) / 2)), new paper.Point(at([cx, cy], r, e)));
  }
}

function slab(piece, h) {
  if (piece.type === 'line') {
    const t = pieceTangent(piece, false);
    const nrm = [-t[1], t[0]];
    const p = new paper.Path();
    p.moveTo(new paper.Point(piece.p0[0] + nrm[0] * h, piece.p0[1] + nrm[1] * h));
    p.lineTo(new paper.Point(piece.p1[0] + nrm[0] * h, piece.p1[1] + nrm[1] * h));
    p.lineTo(new paper.Point(piece.p1[0] - nrm[0] * h, piece.p1[1] - nrm[1] * h));
    p.lineTo(new paper.Point(piece.p0[0] - nrm[0] * h, piece.p0[1] - nrm[1] * h));
    p.closePath();
    return p;
  }
  const { c, r, a0, a1 } = piece;
  const p = new paper.Path();
  p.moveTo(new paper.Point(at(c, r + h, a0)));
  appendArc(p, c[0], c[1], r + h, a0, a1);
  p.lineTo(new paper.Point(at(c, r - h, a1)));
  appendArc(p, c[0], c[1], r - h, a1, a0);
  p.closePath();
  return p;
}

function disc(center, r) {
  return new paper.Path.Circle(new paper.Point(center), r);
}

function squareCap(p, dir, h) {
  const nrm = [-dir[1], dir[0]];
  const path = new paper.Path();
  path.moveTo(new paper.Point(p[0] + nrm[0] * h, p[1] + nrm[1] * h));
  path.lineTo(new paper.Point(p[0] + nrm[0] * h + dir[0] * h, p[1] + nrm[1] * h + dir[1] * h));
  path.lineTo(new paper.Point(p[0] - nrm[0] * h + dir[0] * h, p[1] - nrm[1] * h + dir[1] * h));
  path.lineTo(new paper.Point(p[0] - nrm[0] * h, p[1] - nrm[1] * h));
  path.closePath();
  return path;
}

function joinShape(v, tIn, tOut, h, join) {
  const cross = tIn[0] * tOut[1] - tIn[1] * tOut[0];
  if (Math.abs(cross) < 1e-9) return null;           // smooth joint
  if (join === 'round') return disc(v, h);
  const s = cross > 0 ? -1 : 1;                       // outer side
  const n1 = [-tIn[1] * s, tIn[0] * s];
  const n2 = [-tOut[1] * s, tOut[0] * s];
  const o1 = [v[0] + n1[0] * h, v[1] + n1[1] * h];
  const o2 = [v[0] + n2[0] * h, v[1] + n2[1] * h];
  const path = new paper.Path();
  path.moveTo(new paper.Point(v));
  path.lineTo(new paper.Point(o1));
  if (join === 'miter') {
    // intersection of the two outer offset lines
    const d = tIn[0] * tOut[1] - tIn[1] * tOut[0];
    const bx = o2[0] - o1[0]; const by = o2[1] - o1[1];
    const k = (bx * tOut[1] - by * tOut[0]) / d;
    path.lineTo(new paper.Point(o1[0] + tIn[0] * k, o1[1] + tIn[1] * k));
  }
  path.lineTo(new paper.Point(o2));
  path.closePath();
  return path;
}

/**
 * Stroke a centerline (array of line/arc pieces) into a filled outline.
 * @returns {{d:string, area:number}}
 */
export function strokeToOutline(pieces, width, { cap = 'round', join = 'round', closed = false } = {}) {
  const h = width / 2;
  const parts = pieces.map((p) => slab(p, h));

  for (let i = 0; i < pieces.length - 1; i++) {
    const j = joinShape(pieceEnd(pieces[i]), pieceTangent(pieces[i], true), pieceTangent(pieces[i + 1], false), h, join);
    if (j) parts.push(j);
  }
  if (closed) {
    const last = pieces[pieces.length - 1];
    const j = joinShape(pieceEnd(last), pieceTangent(last, true), pieceTangent(pieces[0], false), h, join);
    if (j) parts.push(j);
  } else if (cap !== 'butt') {
    const first = pieces[0];
    const last = pieces[pieces.length - 1];
    const t0 = pieceTangent(first, false);
    const t1 = pieceTangent(last, true);
    if (cap === 'round') {
      parts.push(disc(pieceStart(first), h), disc(pieceEnd(last), h));
    } else if (cap === 'square') {
      parts.push(squareCap(pieceStart(first), [-t0[0], -t0[1]], h), squareCap(pieceEnd(last), t1, h));
    }
  }
  return unionParts(parts);
}

/** Union an array of paper paths and return `{d, area}`; input paths are consumed. */
export function unionParts(parts) {
  let acc = parts[0];
  for (let i = 1; i < parts.length; i++) {
    const next = acc.unite(parts[i]);
    acc.remove(); parts[i].remove();
    acc = next;
  }
  const d = acc.pathData;
  const area = Math.abs(acc.area);
  acc.remove();
  return { d, area };
}

/** Union of several already-built outline `d` strings (for merged crossings). */
export function unionPathDs(ds) {
  return unionParts(ds.map((d) => new paper.CompoundPath(d)));
}

/** Straight stroke whose width varies linearly from w0 to w1. */
export function taperedStroke(p0, p1, w0, w1) {
  const t = unit([p1[0] - p0[0], p1[1] - p0[1]]);
  const n = [-t[1], t[0]];
  const h0 = w0 / 2; const h1 = w1 / 2;
  const body = new paper.Path();
  body.moveTo(new paper.Point(p0[0] + n[0] * h0, p0[1] + n[1] * h0));
  body.lineTo(new paper.Point(p1[0] + n[0] * h1, p1[1] + n[1] * h1));
  body.lineTo(new paper.Point(p1[0] - n[0] * h1, p1[1] - n[1] * h1));
  body.lineTo(new paper.Point(p0[0] - n[0] * h0, p0[1] - n[1] * h0));
  body.closePath();
  return unionParts([body, disc(p0, h0), disc(p1, h1)]);
}

/** Deterministic radial noise applied to an outline, for the "noisy" case. */
export function noisifyPathD(d, amplitude, seed = 12345, samples = 720) {
  const src = new paper.CompoundPath(d);
  const out = [];
  let s = seed >>> 0;
  const rnd = () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  for (const child of (src.children.length ? src.children : [src])) {
    const n = Math.max(24, Math.round(child.length / (child.length / samples)));
    const pts = [];
    // smooth pseudo-noise: sum of two frequencies with random phase
    const ph1 = rnd() * TAU; const ph2 = rnd() * TAU;
    for (let i = 0; i < n; i++) {
      const loc = child.getLocationAt((i / n) * child.length);
      if (!loc) continue;
      const nrm = loc.normal.normalize();
      const u = i / n;
      const w = Math.sin(u * TAU * 23 + ph1) * 0.6 + Math.sin(u * TAU * 57 + ph2) * 0.4;
      pts.push([loc.point.x + nrm.x * w * amplitude, loc.point.y + nrm.y * w * amplitude]);
    }
    out.push(`M${pts.map((p) => `${p[0].toFixed(4)} ${p[1].toFixed(4)}`).join('L')}Z`);
  }
  src.remove();
  return out.join('');
}

export { paper };
