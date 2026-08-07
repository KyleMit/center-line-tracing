// Common graph model (Common Setup §"Emit the common graph model", report §13)
// plus this track's stroke-order/direction extension.
//
// Ours — Tegaki has no graph layer at all; it emits ordered polylines straight
// to JSON. Node identity here comes from snapping stroke endpoints to a grid, so
// two strokes meeting at a junction share one node. Interior geometry stays on
// the edge, which is what the model asks for.

import { ORIENT_X_WEIGHT } from './constants.js';

function median(arr) {
  if (arr.length === 0) return 0;
  const s = [...arr].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/**
 * Build the common graph model from ordered strokes.
 *
 * `snap` is the endpoint-merge radius in user units. Endpoints closer than this
 * become the same node, which is what turns a bag of polylines into a graph.
 */
export function buildGraph(strokes, doc, opts = {}) {
  const snap = opts.graphSnap ?? Math.max(1, median(strokes.map((s) => s.width)) * 0.75);

  const nodes = [];
  const buckets = new Map();
  const cell = Math.max(snap, 1e-6);
  const bkey = (x, y) => `${Math.floor(x / cell)},${Math.floor(y / cell)}`;

  function nodeFor(p, radius) {
    const cx = Math.floor(p.x / cell);
    const cy = Math.floor(p.y / cell);
    let best = null;
    let bestD = snap;
    for (let i = -1; i <= 1; i++) {
      for (let j = -1; j <= 1; j++) {
        const list = buckets.get(`${cx + i},${cy + j}`);
        if (!list) continue;
        for (const id of list) {
          const n = nodes[id];
          const d = Math.hypot(n.x - p.x, n.y - p.y);
          if (d < bestD) {
            bestD = d;
            best = n;
          }
        }
      }
    }
    if (best) {
      best._n++;
      best._rs.push(radius);
      return best;
    }
    const n = { id: `n${nodes.length}`, x: p.x, y: p.y, radius, _n: 1, _rs: [radius] };
    nodes.push(n);
    const k = bkey(p.x, p.y);
    if (!buckets.has(k)) buckets.set(k, []);
    buckets.get(k).push(nodes.length - 1);
    return n;
  }

  const edges = [];
  strokes.forEach((s, i) => {
    const first = s.points[0];
    const last = s.points[s.points.length - 1];
    const from = nodeFor(first, s.widthProfile[0] / 2);
    const to = s.points.length === 1 ? from : nodeFor(last, s.widthProfile[s.widthProfile.length - 1] / 2);

    edges.push({
      id: `e${i}`,
      from: from.id,
      to: to.id,
      geometry: s.points.map((p) => ({ x: +p.x.toFixed(3), y: +p.y.toFixed(3) })),
      length: +s.length.toFixed(3),
      medianRadius: +(s.width / 2).toFixed(3),
      sourceElementId: s.elementId,
      // ── Track 5 extension: stroke order / direction ──────────────────────
      strokeOrder: {
        index: s.orderIndex,
        // We reverse the geometry array itself rather than carry a flag, so
        // geometry[0] is ALWAYS the pen-down point. Recorded explicitly so a
        // consumer never has to guess whether the array was reordered.
        direction: 'start',
        reversed: !!s.reversed,
        t: s.points.map((p) => +p.t.toFixed(4)),
        class: s.class,
        widthProfile: s.widthProfile.map((w) => +w.toFixed(3)),
      },
    });
  });

  for (const n of nodes) {
    n.radius = +median(n._rs).toFixed(3);
    n.x = +n.x.toFixed(3);
    n.y = +n.y.toFixed(3);
    delete n._n;
    delete n._rs;
  }

  const ordered = [...edges].sort((a, b) => a.strokeOrder.index - b.strokeOrder.index);

  return {
    schema: 'centerline-graph/1',
    producer: 'tegaki (Track 5, adapted from github.com/gkurt/tegaki, MIT)',
    units: 'svg-user-units',
    viewBox: doc.viewBox,
    radiusSource: 'native', // inverse distance transform / Voronoi boundary distance
    options: {
      skeleton: opts.skeleton,
      dt: opts.dt,
      prune: opts.prune,
      spurWidthRatio: opts.spurWidthRatio,
      scale: opts.scale,
      resolution: opts.resolution,
      capExtend: opts.capExtend,
      mergeMode: opts.mergeMode,
      rdpTolerance: opts.rdpTolerance,
    },
    nodes,
    edges,
    strokeOrderMeta: {
      method: 'tegaki-greedy-nn',
      entrySide: opts.rtl ? 'right' : 'left',
      orientRule: 'score = y + x * ORIENT_X_WEIGHT, lower score starts',
      orientXWeight: ORIENT_X_WEIGHT,
      order: ordered.map((e) => e.id),
    },
  };
}

/** Minimal structural validator, so other tracks can check our output. */
export function validateGraph(g) {
  const errs = [];
  if (g.schema !== 'centerline-graph/1') errs.push(`unexpected schema: ${g.schema}`);
  const ids = new Set(g.nodes.map((n) => n.id));
  if (ids.size !== g.nodes.length) errs.push('duplicate node ids');
  for (const e of g.edges) {
    if (!ids.has(e.from)) errs.push(`${e.id}: unknown from ${e.from}`);
    if (!ids.has(e.to)) errs.push(`${e.id}: unknown to ${e.to}`);
    if (!Array.isArray(e.geometry) || e.geometry.length < 1) errs.push(`${e.id}: empty geometry`);
    if (e.strokeOrder) {
      if (e.strokeOrder.t.length !== e.geometry.length) errs.push(`${e.id}: t length != geometry length`);
      if (e.strokeOrder.widthProfile.length !== e.geometry.length) errs.push(`${e.id}: widthProfile length != geometry length`);
    }
  }
  if (g.strokeOrderMeta) {
    const order = g.strokeOrderMeta.order;
    if (new Set(order).size !== g.edges.length) errs.push('strokeOrderMeta.order does not cover every edge exactly once');
  }
  return errs;
}
