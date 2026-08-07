// flo-mat driver: bezier loops -> MAT/SAT -> the common centerline graph model
// (docs/centerline-technique-handoffs.md § "Emit the common graph model").
//
// Two things about flo-mat@4.1.0 that the report/handoff get wrong and that
// change results materially:
//
//  1. `findMats(loops, 3)` — the second argument is a MatOptions OBJECT, not a
//     number. A bare `3` is silently ignored, so you get the DEFAULTS, which are
//     `applySat: true, satScale: 2, simplify: true`. i.e. the "raw MAT" in the
//     report's example is already Scale-Axis-pruned at s=2. To get a genuinely
//     raw MAT you must pass `{ applySat: false }`.
//  2. `node.cp` does not exist. The maximal disk is `node.pointOnShape.circle`
//     = `{ center: [x,y], radius }`.

import {
  findMats, toScaleAxis, traverseEdges, isTerminating, getMatCurveToNext,
} from 'flo-mat';

/* ------------------------------------------------------------------ bezier */

export function bezierAt(b, t) {
  const mt = 1 - t;
  if (b.length === 2) return [b[0][0] * mt + b[1][0] * t, b[0][1] * mt + b[1][1] * t];
  if (b.length === 3) {
    const a = mt * mt; const c = 2 * mt * t; const d = t * t;
    return [a * b[0][0] + c * b[1][0] + d * b[2][0], a * b[0][1] + c * b[1][1] + d * b[2][1]];
  }
  const a = mt * mt * mt; const c = 3 * mt * mt * t; const d = 3 * mt * t * t; const e = t * t * t;
  return [
    a * b[0][0] + c * b[1][0] + d * b[2][0] + e * b[3][0],
    a * b[0][1] + c * b[1][1] + d * b[2][1] + e * b[3][1],
  ];
}

export function bezierLength(b, n = 24) {
  let len = 0; let prev = b[0];
  for (let i = 1; i <= n; i++) {
    const p = bezierAt(b, i / n);
    len += Math.hypot(p[0] - prev[0], p[1] - prev[1]);
    prev = p;
  }
  return len;
}

/** Unit tangent at t=0 (start) or t=1 (end), robust to coincident controls. */
export function bezierTangent(b, at) {
  const eps = 1e-4;
  const t = at === 0 ? eps : 1 - eps;
  const p = bezierAt(b, t);
  const q = at === 0 ? b[0] : b[b.length - 1];
  const dx = at === 0 ? p[0] - q[0] : q[0] - p[0];
  const dy = at === 0 ? p[1] - q[1] : q[1] - p[1];
  const L = Math.hypot(dx, dy);
  if (L < 1e-12) {
    // fall back to the chord
    const cx = b[b.length - 1][0] - b[0][0]; const cy = b[b.length - 1][1] - b[0][1];
    const cl = Math.hypot(cx, cy) || 1;
    return [cx / cl, cy / cl];
  }
  return [dx / L, dy / L];
}

/* ---------------------------------------------------------------- MAT graph */

/**
 * Walk a flo-mat `Mat` and build a node/edge graph.
 * Nodes are maximal-disk centres (deduplicated by position), edges are the MAT
 * bezier curves between them, carrying the disk radius at each end.
 *
 * `tol` merges coincident-but-not-bit-identical MAT vertices. flo-mat routinely
 * emits several `CpNode`s at the same centre (they differ in the 1e-9s), which
 * without merging show up as spurious zero-length edges and inflate the node
 * count; this is graph hygiene, not pruning.
 */
export function matToGraph(mat, { sourceElementId = null, tol = 1e-6 } = {}) {
  const nodes = new Map();   // snapped key -> node
  const edges = [];
  let nid = 0;
  const inv = 1 / Math.max(tol, 1e-12);
  const keys = (p) => {
    const gx = Math.round(p[0] * inv); const gy = Math.round(p[1] * inv);
    const out = [];
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) out.push(`${gx + dx},${gy + dy}`);
    return out;
  };

  const nodeFor = (center, radius) => {
    for (const k of keys(center)) {
      const nd = nodes.get(k);
      if (nd && Math.hypot(nd.x - center[0], nd.y - center[1]) <= tol) {
        nd.radius = Math.max(nd.radius, radius);
        return nd;
      }
    }
    const nd = { id: `n${nid++}`, x: center[0], y: center[1], radius, deg: 0 };
    nodes.set(keys(center)[4], nd);
    return nd;
  };

  const seen = new Set();
  traverseEdges(mat.cpNode, (node) => {
    if (isTerminating(node)) return;
    const curve = getMatCurveToNext(node);
    if (!curve || curve.length < 2) return;

    const c0 = node.pointOnShape.circle;
    const c1 = node.next.pointOnShape.circle;
    const a = nodeFor(c0.center, c0.radius);
    const b = nodeFor(c1.center, c1.radius);
    if (a === b) return; // zero-length MAT curve (cap / one-prong node)

    // the same medial edge is visited twice (once from each side of the shape)
    const ek = a.id < b.id ? `${a.id}|${b.id}` : `${b.id}|${a.id}`;
    if (seen.has(ek)) return;
    seen.add(ek);

    a.deg++; b.deg++;
    edges.push({
      id: `e${edges.length}`,
      from: a.id,
      to: b.id,
      geometry: [curve.map((p) => [p[0], p[1]])],
      length: bezierLength(curve),
      medianRadius: (c0.radius + c1.radius) / 2,
      sourceElementId,
    });
  });

  return { nodes: [...nodes.values()], edges };
}

/**
 * Run flo-mat over one element's loops.
 * @param loops bezier loops from normalize.pathToLoops
 * @param opts  { applySat, satScale, simplify, maxLength, maxCurviness, satSweep }
 */
export function runMat(loops, opts = {}) {
  const matOptions = {
    applySat: opts.applySat ?? false,
    satScale: opts.satScale ?? 2,
    simplify: opts.simplify ?? true,
    ...(opts.maxLength !== undefined ? { maxLength: opts.maxLength } : {}),
    ...(opts.maxCurviness !== undefined ? { maxCurviness: opts.maxCurviness } : {}),
    ...(opts.simplifyTolerance !== undefined ? { simplifyTolerance: opts.simplifyTolerance } : {}),
  };
  const t0 = process.hrtime.bigint();
  const mats = findMats(loops, matOptions);
  const t1 = process.hrtime.bigint();
  return { mats, ms: Number(t1 - t0) / 1e6, matOptions };
}

export function applySat(mats, s) {
  if (!(s > 1)) return mats;
  return mats.map((m) => toScaleAxis(m, s));
}

/** Merge several per-mat graphs into one, renaming ids so they stay unique. */
export function mergeGraphs(graphs) {
  const nodes = []; const edges = [];
  graphs.forEach((g, i) => {
    const map = new Map();
    for (const n of g.nodes) {
      const id = `g${i}_${n.id}`;
      map.set(n.id, id);
      nodes.push({ ...n, id });
    }
    for (const e of g.edges) {
      edges.push({ ...e, id: `g${i}_${e.id}`, from: map.get(e.from), to: map.get(e.to) });
    }
  });
  return { nodes, edges };
}
