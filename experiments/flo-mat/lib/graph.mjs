// Common graph model utilities: chain (branch) extraction, cap calibration,
// and re-stroke emission.

import { bezierAt, bezierLength, bezierTangent } from './mat.mjs';
import { rayToBoundary } from './geom.mjs';

export function median(xs) {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export function adjacency(graph) {
  const adj = new Map();
  for (const n of graph.nodes) adj.set(n.id, []);
  for (const e of graph.edges) {
    adj.get(e.from)?.push({ edge: e, other: e.to, rev: false });
    adj.get(e.to)?.push({ edge: e, other: e.from, rev: true });
  }
  return adj;
}

const revBez = (b) => [...b].reverse();

/**
 * Contract numerically degenerate MAT edges (length below `eps`).
 *
 * flo-mat emits a small fan of ~0.04-unit branches inside every round cap disk
 * and at boundary-intersection points: `L / (2R) ~= 0.002`. They are a
 * discretization artifact of the maximal-disk contact arc, not shape detail —
 * so contracting them is graph hygiene, NOT semantic pruning (which is Track 8).
 * The count is reported as `cap artifact`.
 */
export function contractShortEdges(graph, eps) {
  if (!(eps > 0)) return { graph, contracted: 0 };
  const parent = new Map(graph.nodes.map((n) => [n.id, n.id]));
  const find = (a) => { while (parent.get(a) !== a) { parent.set(a, parent.get(parent.get(a))); a = parent.get(a); } return a; };
  let contracted = 0;
  // contract the shortest first so a chain of tiny edges collapses to one node
  for (const e of [...graph.edges].sort((a, b) => a.length - b.length)) {
    if (e.length >= eps) continue;
    const a = find(e.from); const b = find(e.to);
    if (a === b) { contracted++; continue; }
    parent.set(b, a);
    contracted++;
  }
  if (!contracted) return { graph, contracted: 0 };
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const keep = new Map();
  for (const n of graph.nodes) {
    const root = find(n.id);
    if (!keep.has(root)) keep.set(root, { ...byId.get(root) });
    const k = keep.get(root);
    k.radius = Math.max(k.radius, n.radius);
  }
  const edges = [];
  for (const e of graph.edges) {
    const a = find(e.from); const b = find(e.to);
    if (a === b) continue;
    edges.push({ ...e, from: a, to: b });
  }
  return { graph: { nodes: [...keep.values()], edges }, contracted };
}

/**
 * Collapse degree-2 nodes: return maximal chains running between terminal
 * (deg 1) or junction (deg >= 3) nodes, plus isolated cycles.
 */
export function extractChains(graph) {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const adj = adjacency(graph);
  const deg = (id) => adj.get(id).length;
  const usedEdge = new Set();
  const chains = [];

  const walk = (startId, first) => {
    const beziers = [];
    const nodeIds = [startId];
    let cur = startId;
    let step = first;
    for (;;) {
      usedEdge.add(step.edge.id);
      for (const b of step.edge.geometry) beziers.push(step.rev ? revBez(b) : b);
      cur = step.other;
      nodeIds.push(cur);
      if (deg(cur) !== 2) break;
      const next = adj.get(cur).find((x) => !usedEdge.has(x.edge.id));
      if (!next) break;
      step = next;
    }
    return { beziers, nodeIds };
  };

  for (const n of graph.nodes) {
    if (deg(n.id) === 2) continue;
    for (const step of adj.get(n.id)) {
      if (usedEdge.has(step.edge.id)) continue;
      chains.push(walk(n.id, step));
    }
  }
  // pure cycles (every node degree 2)
  for (const e of graph.edges) {
    if (usedEdge.has(e.id)) continue;
    const step = { edge: e, other: e.to, rev: false };
    chains.push(walk(e.from, step));
  }

  return chains.map((c, i) => {
    const radii = c.nodeIds.map((id) => byId.get(id)?.radius ?? 0);
    const length = c.beziers.reduce((s, b) => s + bezierLength(b), 0);
    return {
      id: `c${i}`,
      beziers: c.beziers,
      nodeIds: c.nodeIds,
      radii,
      medianRadius: median(radii),
      meanRadius: radii.reduce((s, r) => s + r, 0) / (radii.length || 1),
      length,
      closed: c.nodeIds[0] === c.nodeIds[c.nodeIds.length - 1],
      startDeg: deg(c.nodeIds[0]),
      endDeg: deg(c.nodeIds[c.nodeIds.length - 1]),
    };
  });
}

/**
 * Dense, length-parameterised radius profile for a chain, measured directly
 * against the shape boundary. Returns the profile plus a LENGTH-WEIGHTED
 * median, which is what should drive stroke width: a junction bulge is short
 * relative to the branch it sits on, so it no longer drags the width up.
 */
export function measureChainRadius(chain, sampler, spacing = 1) {
  const samples = [];
  let s = 0;
  for (const b of chain.beziers) {
    const L = bezierLength(b);
    const n = Math.max(1, Math.ceil(L / spacing));
    for (let k = 0; k < n; k++) {
      const p = bezierAt(b, k / n);
      samples.push({ s: s + (L * k) / n, r: sampler.distance(p), w: L / n });
    }
    s += L;
  }
  if (!samples.length) return { samples: [], weightedMedian: chain.medianRadius, cv: 0 };
  const sorted = [...samples].sort((a, b) => a.r - b.r);
  const total = sorted.reduce((t, x) => t + x.w, 0);
  let acc = 0; let wm = sorted[0].r;
  for (const x of sorted) { acc += x.w; if (acc >= total / 2) { wm = x.r; break; } }
  const mean = samples.reduce((t, x) => t + x.r * x.w, 0) / (total || 1);
  const varr = samples.reduce((t, x) => t + x.w * (x.r - mean) ** 2, 0) / (total || 1);
  return { samples, weightedMedian: wm, mean, cv: mean ? Math.sqrt(varr) / mean : 0 };
}

/* ------------------------------------------------------- cap calibration */

/** Cumulative arclength samples of a bezier list. */
function sampleChain(beziers, per = 16) {
  const pts = [];
  beziers.forEach((b, i) => {
    for (let k = i === 0 ? 0 : 1; k <= per; k++) pts.push(bezierAt(b, k / per));
  });
  return pts;
}

function trimFromEnd(beziers, dist, fromStart) {
  // walk in from the given end, dropping/splitting beziers until `dist` consumed
  const list = fromStart ? beziers.map(revBez).reverse() : beziers.slice();
  let remaining = dist;
  while (list.length > 1 && remaining > 0) {
    const L = bezierLength(list[list.length - 1]);
    if (L > remaining) break;
    list.pop();
    remaining -= L;
  }
  if (remaining > 1e-12 && list.length) {
    const last = list[list.length - 1];
    // arclength -> parameter, with linear interpolation inside the sample step
    // (a whole-step cut here silently removed several units of real centerline)
    const per = 256;
    let acc = 0; let prev = bezierAt(last, 1); let tCut = 0;
    for (let k = per - 1; k >= 0; k--) {
      const t = k / per;
      const p = bezierAt(last, t);
      const seg = Math.hypot(p[0] - prev[0], p[1] - prev[1]);
      if (acc + seg >= remaining) {
        const frac = seg > 0 ? (remaining - acc) / seg : 0;
        tCut = t + (1 / per) * (1 - frac);
        break;
      }
      acc += seg; prev = p;
    }
    if (tCut > 0) list[list.length - 1] = splitBezier(last, tCut);
    else list.pop();
  }
  if (!list.length) return beziers.slice(0, 1);
  return fromStart ? list.map(revBez).reverse() : list;
}

/** de Casteljau: return the [0,t] portion. */
export function splitBezier(b, t) {
  if (b.length === 2) return [b[0], bezierAt(b, t)];
  const lerp = (p, q) => [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t];
  if (b.length === 3) {
    const a1 = lerp(b[0], b[1]); const a2 = lerp(b[1], b[2]);
    return [b[0], a1, lerp(a1, a2)];
  }
  const a1 = lerp(b[0], b[1]); const a2 = lerp(b[1], b[2]); const a3 = lerp(b[2], b[3]);
  const c1 = lerp(a1, a2); const c2 = lerp(a2, a3);
  return [b[0], a1, c1, lerp(c1, c2)];
}

/**
 * Move each free (degree-1) chain end so the round cap kisses the outline apex:
 *   tip = march_to_boundary(end, tangent) - k * R
 * Returns a new chain plus a per-end delta report.
 *
 * With a genuine round cap the MAT already terminates exactly one radius from
 * the boundary, so delta is ~0 and this is a no-op. It only bites on butt/flat
 * ends, tapers and SAT-truncated branches.
 */
export function calibrateCaps(chain, loops, { k = 1, maxDelta = Infinity, radius = null } = {}) {
  if (chain.closed) return { chain, deltas: [] };
  let beziers = chain.beziers;
  const deltas = [];
  const R = radius ?? chain.medianRadius;
  const deadband = 1e-3 * R;

  for (const which of ['start', 'end']) {
    const isStart = which === 'start';
    const deg = isStart ? chain.startDeg : chain.endDeg;
    if (deg !== 1) continue;
    const b = isStart ? beziers[0] : beziers[beziers.length - 1];
    const p = isStart ? b[0] : b[b.length - 1];
    const t = bezierTangent(b, isStart ? 0 : 1);
    const dir = isStart ? [-t[0], -t[1]] : t;      // outward
    const dist = rayToBoundary(loops, p, dir, R * 12);
    if (!Number.isFinite(dist)) { deltas.push({ which, delta: 0, reason: 'no-hit' }); continue; }
    let delta = dist - k * R;
    if (Math.abs(delta) > maxDelta) delta = Math.sign(delta) * maxDelta;
    deltas.push({ which, delta, dist, radius: R });
    if (Math.abs(delta) < deadband) continue;
    if (delta > 0) {
      const q = [p[0] + dir[0] * delta, p[1] + dir[1] * delta];
      if (isStart) beziers = [[q, p], ...beziers];
      else beziers = [...beziers, [p, q]];
    } else {
      beziers = trimFromEnd(beziers, -delta, isStart);
    }
  }
  const length = beziers.reduce((s, x) => s + bezierLength(x), 0);
  return { chain: { ...chain, beziers, length }, deltas };
}

/* -------------------------------------------------------------- emission */

const fmt = (v, prec = 3) => {
  const r = Math.round(v * 10 ** prec) / 10 ** prec;
  return Object.is(r, -0) ? 0 : r;
};

export function chainToPathD(beziers) {
  if (!beziers.length) return '';
  let d = `M${fmt(beziers[0][0][0])} ${fmt(beziers[0][0][1])}`;
  for (const b of beziers) {
    if (b.length === 2) d += `L${fmt(b[1][0])} ${fmt(b[1][1])}`;
    else if (b.length === 3) d += `Q${fmt(b[1][0])} ${fmt(b[1][1])} ${fmt(b[2][0])} ${fmt(b[2][1])}`;
    else d += `C${fmt(b[1][0])} ${fmt(b[1][1])} ${fmt(b[2][0])} ${fmt(b[2][1])} ${fmt(b[3][0])} ${fmt(b[3][1])}`;
  }
  return d;
}

export function strokedSvg(doc, strokes) {
  const vb = doc.viewBox;
  const body = strokes.map((s) => `<path d="${s.d}" fill="none" stroke="${s.stroke}" stroke-width="${fmt(s.width)}"`
    + ' stroke-linecap="round" stroke-linejoin="round"/>').join('\n');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vb.x} ${vb.y} ${vb.w} ${vb.h}">\n${body}\n</svg>\n`;
}

/* ------------------------------------------------------------- statistics */

export function graphComplexity(graph, chains) {
  const segs = graph.edges.reduce((s, e) => s + e.geometry.length, 0);
  const cps = graph.edges.reduce((s, e) => s + e.geometry.reduce((t, b) => t + b.length, 0), 0);
  const deg = new Map(graph.nodes.map((n) => [n.id, 0]));
  for (const e of graph.edges) { deg.set(e.from, deg.get(e.from) + 1); deg.set(e.to, deg.get(e.to) + 1); }
  const counts = { 1: 0, 2: 0, 3: 0, 4: 0, more: 0 };
  for (const v of deg.values()) {
    if (v >= 5) counts.more++;
    else counts[v] = (counts[v] || 0) + 1;
  }
  return {
    nodes: graph.nodes.length,
    edges: graph.edges.length,
    beziers: segs,
    controlPoints: cps,
    strokes: chains.length,
    terminals: counts[1],
    junctions: (counts[3] || 0) + (counts[4] || 0) + counts.more,
    deg3: counts[3] || 0,
    deg4: counts[4] || 0,
    degGE5: counts.more,
    totalLength: chains.reduce((s, c) => s + c.length, 0),
  };
}

/** Width consistency: std(R)/mean(R) over all chains, length-weighted. */
export function widthError(chains) {
  let wsum = 0; let acc = 0;
  const all = [];
  for (const c of chains) {
    if (!c.radii.length) continue;
    const mean = c.meanRadius || 1e-9;
    const varr = c.radii.reduce((s, r) => s + (r - mean) ** 2, 0) / c.radii.length;
    const cv = Math.sqrt(varr) / mean;
    acc += cv * c.length; wsum += c.length;
    all.push(...c.radii);
  }
  const gm = all.reduce((s, r) => s + r, 0) / (all.length || 1);
  const gv = all.reduce((s, r) => s + (r - gm) ** 2, 0) / (all.length || 1);
  return {
    perChainCv: wsum ? acc / wsum : 0,
    globalCv: gm ? Math.sqrt(gv) / gm : 0,
    medianRadius: median(all),
  };
}

/** Sample points along all chains at a fixed arclength spacing. */
export function chainPoints(chains, spacing = 0.5) {
  const pts = [];
  for (const c of chains) {
    for (const b of c.beziers) {
      const n = Math.max(2, Math.ceil(bezierLength(b) / spacing));
      for (let k = 0; k <= n; k++) pts.push(bezierAt(b, k / n));
    }
  }
  return pts;
}
