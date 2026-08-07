// End-to-end: normalized SVG document -> flo-mat MAT/SAT -> common graph model
// -> cap-calibrated chains -> stroked SVG.

import { runMat, applySat, matToGraph, mergeGraphs, bezierAt, bezierLength } from './mat.mjs';
import {
  extractChains, calibrateCaps, chainToPathD, strokedSvg, graphComplexity, widthError, median,
  contractShortEdges, measureChainRadius, splitBezier,
} from './graph.mjs';
import { boundarySampler } from './geom.mjs';

export const DEFAULTS = {
  applySat: false,      // flo-mat's own default is TRUE (satScale 2) — see NOTES
  satScale: 2,
  simplify: true,
  satSweep: null,       // post-hoc toScaleAxis scale, null = none
  caps: 'apex',         // 'none' | 'apex'
  capK: 1,
  widthMode: 'measured', // 'measured' | 'chain' | 'element' | 'global'
  variableWidth: 0,     // >0: split chains into segments of this many radii
  contractEps: 1e-3,    // fraction of the shape diagonal; degenerate-edge hygiene
  minChainLength: 0,    // 0 = no pruning (pruning is Track 8's job)
};

/** MAT stage, in-process. Fine for the synthetic corpus; the real ladder uses
 *  `runDocumentAsync` so a hanging element can be timed out. */
function matStageSync(doc, opt) {
  const tol = 1e-6 * Math.max(doc.viewBox.w, doc.viewBox.h);
  return doc.elements.map((el) => {
    try {
      const res = runMat(el.loops, opt);
      const mats = opt.satSweep && opt.satSweep > 1 ? applySat(res.mats, opt.satSweep) : res.mats;
      return {
        el,
        graph: mergeGraphs(mats.map((m) => matToGraph(m, { sourceElementId: el.id, tol }))),
        ms: res.ms,
        mats: mats.length,
      };
    } catch (err) {
      return { el, error: String((err && err.message) || err) };
    }
  });
}

export function runDocument(doc, options = {}) {
  return finishDocument(doc, { ...DEFAULTS, ...options }, matStageSync(doc, { ...DEFAULTS, ...options }));
}

/** Same pipeline, but each element's MAT runs in a worker with a timeout. */
export async function runDocumentAsync(doc, options = {}, { timeoutMs = 20000 } = {}) {
  const opt = { ...DEFAULTS, ...options };
  const { computeMatGraphs } = await import('./mat-pool.mjs');
  const raw = await computeMatGraphs(doc.elements, {
    options: opt,
    tol: 1e-6 * Math.max(doc.viewBox.w, doc.viewBox.h),
    satSweep: opt.satSweep,
    timeoutMs,
  });
  return finishDocument(doc, opt, raw);
}

function finishDocument(doc, opt, matResults) {
  const diag = Math.hypot(doc.viewBox.w, doc.viewBox.h);
  const perElement = [];
  const graphs = [];
  let matMs = 0;
  const satMs = 0;
  let contracted = 0;

  for (const res of matResults) {
    const { el } = res;
    if (res.error || !res.graph) {
      perElement.push({ id: el.id, error: res.error || 'no-graph', timeoutMs: res.timeoutMs, loops: el.loops.length });
      continue;
    }
    matMs += res.ms || 0;
    let g = res.graph;
    const c = contractShortEdges(g, opt.contractEps * diag);
    g = c.graph; contracted += c.contracted;
    const sampler = boundarySampler(el.loops, Math.max(diag / 4000, 0.05));
    // dense distance-to-boundary profile per edge — Track 8 wants radius data
    for (const e of g.edges) {
      const samples = [];
      for (const b of e.geometry) for (let k = 0; k <= 8; k++) samples.push(round(sampler.distance(bezierAt(b, k / 8))));
      e.radiusProfile = samples;
    }
    graphs.push({ el, graph: g, sampler });
    perElement.push({ id: el.id, ms: res.ms, mats: res.mats, nodes: g.nodes.length, edges: g.edges.length });
  }

  const graph = mergeGraphs(graphs.map((x) => x.graph));

  // chains are computed per element so separate elements never chain together
  const chains = [];
  const capReports = [];
  for (const { el, graph: g, sampler } of graphs) {
    let cs = extractChains(g);
    if (opt.minChainLength > 0) {
      cs = cs.filter((c) => c.length >= opt.minChainLength * (c.medianRadius * 2 || 1)
        || (c.startDeg !== 1 && c.endDeg !== 1));
    }
    for (const c of cs) {
      let out = c;
      const step = Math.max(diag / 600, 0.25);
      // width first: cap calibration must step back by the *measured* radius,
      // not by a node radius that a nearby junction bulge has inflated
      const pre = measureChainRadius(c, sampler, step);
      if (opt.caps === 'apex') {
        const r = calibrateCaps(c, el.loops, { k: opt.capK, radius: pre.weightedMedian });
        out = r.chain;
        capReports.push(...r.deltas.map((d) => ({ chain: c.id, element: el.id, ...d })));
      }
      const prof = measureChainRadius(out, sampler, step);
      chains.push({
        ...out,
        elementId: el.id,
        fill: el.fill,
        opacity: (el.fillOpacity ?? 1) * (el.opacity ?? 1),
        profile: prof,
        measuredRadius: prof.weightedMedian,
        radiusCv: prof.cv,
      });
    }
  }

  const globalR = median(chains.flatMap((c) => c.radii));
  const elementR = new Map();
  for (const c of chains) {
    if (!elementR.has(c.elementId)) elementR.set(c.elementId, []);
    elementR.get(c.elementId).push(...c.radii);
  }
  for (const [k, v] of elementR) elementR.set(k, median(v));

  const strokes = [];
  for (const c of chains) {
    let r = c.measuredRadius;
    if (opt.widthMode === 'chain') r = c.medianRadius;
    else if (opt.widthMode === 'element') r = elementR.get(c.elementId) ?? r;
    else if (opt.widthMode === 'global') r = globalR;
    if (!(r > 0)) continue;
    if (opt.variableWidth > 0) {
      strokes.push(...splitVariableWidth(c, opt.variableWidth));
    } else {
      const d = chainToPathD(c.beziers);
      if (d) strokes.push({ d, width: 2 * r, stroke: c.fill, opacity: c.opacity, elementId: c.elementId });
    }
  }

  return {
    graph,
    graphs,
    chains,
    strokes,
    svg: strokedSvg(doc, strokes),
    capReports,
    perElement,
    contracted,
    timing: { matMs, satMs },
    complexity: graphComplexity(graph, chains),
    width: widthError(chains),
    options: opt,
  };
}

/**
 * Variable-width emission: cut each chain into short pieces and stroke each at
 * its locally measured radius. Not a production output format — it exists to
 * show that flo-mat's radius data (the "T" in MAT) is accurate even where a
 * single constant width cannot reproduce the fill.
 */
function splitVariableWidth(chain, radiiPerSegment) {
  const target = Math.max(chain.measuredRadius * radiiPerSegment, 1e-6);
  const out = [];
  // split each bezier so no piece is longer than `target`
  const pieces = [];
  for (const b of chain.beziers) {
    const L = bezierLength(b);
    const n = Math.max(1, Math.ceil(L / target));
    let rest = b;
    for (let k = 0; k < n; k++) {
      const remaining = n - k;
      if (remaining === 1) { pieces.push(rest); break; }
      const t = 1 / remaining;
      pieces.push(splitBezier(rest, t));
      rest = splitAfter(rest, t);
    }
  }
  const samples = chain.profile.samples;
  let s0 = 0;
  for (const piece of pieces) {
    const L = bezierLength(piece);
    const mid = s0 + L / 2;
    let r = chain.measuredRadius; let bd = Infinity;
    for (const smp of samples) {
      const d = Math.abs(smp.s - mid);
      if (d < bd) { bd = d; r = smp.r; }
    }
    out.push({ d: chainToPathD([piece]), width: 2 * r, stroke: chain.fill, opacity: chain.opacity, elementId: chain.elementId });
    s0 += L;
  }
  return out;
}

/** de Casteljau: return the [t,1] portion. */
function splitAfter(b, t) {
  const rev = [...b].reverse();
  const head = splitBezier(rev, 1 - t);
  return [...head].reverse();
}

/** Serialize to the common graph model (Common Setup §"Emit the common graph model"). */
export function toGraphJson(result, meta = {}) {
  return {
    schema: 'centerline-graph/1',
    backend: 'flo-mat@4.1.0',
    ...meta,
    options: result.options,
    nodes: result.graph.nodes.map((n) => ({
      id: n.id, x: round(n.x), y: round(n.y), radius: round(n.radius),
    })),
    edges: result.graph.edges.map((e) => ({
      id: e.id,
      from: e.from,
      to: e.to,
      geometry: e.geometry.map((b) => b.map((p) => [round(p[0]), round(p[1])])),
      length: round(e.length),
      medianRadius: round(e.medianRadius),
      // dense distance-to-boundary profile along the edge; `radius` on a node is
      // flo-mat's exact maximal-disk radius, this is the sampled continuation
      radiusProfile: e.radiusProfile,
      sourceElementId: e.sourceElementId,
    })),
    stats: result.complexity,
  };
}

const round = (v) => Math.round(v * 1e4) / 1e4;
