// The adapted Tegaki pipeline, end to end, for arbitrary filled SVG.
//
//   parseSvg -> per filled element:
//     flatten (bezier.js) -> rasterize (raster.js) -> inverse DT (dt.js)
//     -> skeletonize (thin.js + cleanup.js) or voronoi (voronoi.js)
//     -> trace + prune (trace.js) -> cap extension (ADAPTED, ours)
//     -> orient/order/width (order.js) -> graph model + stroked SVG
//
// Everything marked ADAPTED is a deliberate departure from Tegaki; see
// debug/tegaki/NOTES.md Part 2.

import { parseSvg } from './svg.js';
import { rasterize, toUserSpace } from './raster.js';
import { computeInverseDistanceTransform, sampleRadius } from './dt.js';
import { zhangSuenThin, guoHallThin, leeThin, morphologicalThin, medialAxisThin } from './thin.js';
import { cleanJunctionClusters, restoreErasedComponents } from './cleanup.js';
import { traceAndSimplify, pathLength } from './trace.js';
import { voronoiMedialAxis } from './voronoi.js';
import { orderStrokes } from './order.js';
import { buildGraph } from './graph.js';
import {
  BEZIER_TOLERANCE,
  DEFAULT_SCALE,
  JUNCTION_CLEANUP_MAX_ITERATIONS,
  MERGE_RADIUS_FACTOR,
  MERGE_THRESHOLD_RATIO,
  RDP_TOLERANCE,
  SPUR_WIDTH_RATIO,
  THIN_MAX_ITERATIONS,
  TRACE_CURVATURE_BIAS,
  TRACE_LOOKBACK,
  VORONOI_SAMPLING_INTERVAL,
} from './constants.js';

export const DEFAULTS = {
  scale: DEFAULT_SCALE,
  resolution: null, // set to use Tegaki's aspect-fit-to-N mode instead of `scale`
  skeleton: 'zhang-suen',
  dt: 'chamfer',
  prune: 'tegaki-width',
  spurWidthRatio: SPUR_WIDTH_RATIO,
  spurMinLength: null,
  rdpTolerance: RDP_TOLERANCE,
  bezierTolerance: BEZIER_TOLERANCE,
  lookback: TRACE_LOOKBACK,
  curvatureBias: TRACE_CURVATURE_BIAS,
  thinMaxIterations: THIN_MAX_ITERATIONS,
  junctionCleanupIterations: JUNCTION_CLEANUP_MAX_ITERATIONS,
  voronoiSamplingInterval: VORONOI_SAMPLING_INTERVAL,
  mergeMode: 'radius', // 'radius' (ours) | 'tegaki' (0.08 * bitmap) | 'off'
  mergeRadiusFactor: MERGE_RADIUS_FACTOR,
  capExtend: 1.0, // ADAPTED: search range in multiples of the stroke diameter; 0 disables
  capStyle: 'round', // 'round' (plateau rule) | 'ink' (run to the ink edge, for butt caps) | 'none'
  minStrokeLength: 0, // user units; drop strokes shorter than this (0 = keep all)
  rtl: false,
};

function median(arr) {
  if (arr.length === 0) return 0;
  const s = [...arr].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/**
 * ADAPTED — not in Tegaki. Font glyphs have no round caps, so Tegaki never has
 * to undo the medial axis's cap inset (report §2.3). Pen artwork does: a
 * round-capped stroke's medial axis stops one radius short of the true endpoint
 * at each end. Extend each free (unattached) terminal along its outgoing tangent
 * by `capExtend * R_local`, walking outward only while the bitmap is still
 * filled, so we never overshoot the actual ink.
 */
function extendCaps(polylines, bitmap, inverseDT, width, height, factor, attachThreshold, capStyle = 'round') {
  if (factor <= 0 || capStyle === 'none') return { polylines, extended: 0 };
  const inside = (p) => {
    const x = Math.round(p.x);
    const y = Math.round(p.y);
    return x >= 0 && x < width && y >= 0 && y < height && bitmap[y * width + x] === 1;
  };

  let extended = 0;
  const out = polylines.map((p) => p.map((q) => ({ x: q.x, y: q.y })));

  out.forEach((p, i) => {
    if (p.length < 2) return;
    // Median radius along this polyline — how far it is reasonable to search.
    const radii = p.map((q) => sampleRadius(q.x, q.y, inverseDT, width, height)).sort((a, b) => a - b);
    const rMed = radii[radii.length >> 1];

    for (const end of [0, 1]) {
      const tip = end === 0 ? p[0] : p[p.length - 1];
      const attached = out.some((other, j) => j !== i && other.some((q) => Math.hypot(q.x - tip.x, q.y - tip.y) < attachThreshold));
      if (attached) continue;

      // Outgoing tangent from a short window, so pixel noise at the tip does not
      // decide the direction.
      const win = Math.min(6, p.length - 1);
      const back = end === 0 ? p[win] : p[p.length - 1 - win];
      let dx = tip.x - back.x;
      let dy = tip.y - back.y;
      const len = Math.hypot(dx, dy);
      if (len === 0) continue;
      dx /= len;
      dy /= len;

      // Walk outward while still inside the ink, recording the radius profile,
      // and stop at THE LAST POINT WHERE THE RADIUS IS STILL AT ITS MAXIMUM.
      //
      // Why that rule. The inscribed radius along a stroke's axis is flat at the
      // pen radius until the true endpoint, then falls away through the cap —
      // for every cap style, because past the endpoint the nearest boundary is
      // the cap itself. So the end of the radius plateau IS the endpoint:
      //   round cap  — plateau ends at the cap-arc centre;
      //   square cap — plateau ends where the square starts;
      //   butt cap   — the radius is ALREADY falling at the traced tip (the ink
      //                just stops), so there is no plateau; fall back to the
      //                last point still inside the ink.
      // Extending by a flat `1 * R` instead, which is the obvious first guess,
      // overshot the true endpoint of a round-capped capsule by 6 units.
      const maxStep = factor * 2 * Math.max(rMed, sampleRadius(tip.x, tip.y, inverseDT, width, height));
      const STEP = 0.25;
      let lastInside = 0;
      let maxR = sampleRadius(tip.x, tip.y, inverseDT, width, height);
      const profile = [];
      for (let s = STEP; s <= maxStep + 1e-9; s += STEP) {
        const q = { x: tip.x + dx * s, y: tip.y + dy * s };
        if (!inside(q)) break;
        lastInside = s;
        const r = sampleRadius(q.x, q.y, inverseDT, width, height);
        profile.push({ s, r });
        if (r > maxR) maxR = r;
      }
      let plateauEnd = 0;
      for (const { s, r } of profile) if (r >= maxR - 0.05) plateauEnd = s;
      // The DT is quantized to the pixel grid, so "no plateau" still reports a
      // pixel or two. Require the plateau to be a real fraction of the radius.
      const havePlateau = plateauEnd >= 0.25 * maxR;

      // `capStyle` is a genuine ambiguity, not a tuning knob. Measured on the
      // synthetic corpus: the true endpoint of a ROUND-capped stroke and the
      // traced tip of a BUTT-capped stroke have IDENTICAL local radius profiles
      // — full radius at the point, falling linearly to zero one radius further
      // out. Nothing local separates them. So:
      //   'round' (default) — extend only to the end of a radius plateau, and
      //     not at all when there is none. Correct for round and square caps;
      //     leaves butt-capped strokes one radius short at each end, which we
      //     tag `cap artifact` rather than hide.
      //   'ink' — always run out to the edge of the ink. Correct for butt caps,
      //     overshoots round caps by one radius.
      // Our real inputs are round-capped pen strokes, so 'round' is the default.
      const best = capStyle === 'ink' ? lastInside : havePlateau ? plateauEnd : 0;
      if (best <= 0) continue;

      const np = { x: tip.x + dx * best, y: tip.y + dy * best, extended: true };
      if (end === 0) p.unshift(np);
      else p.push(np);
      extended++;
    }
  });

  return { polylines: out, extended };
}

function skeletonizeElement(element, raster, inverseDT, opts) {
  const { bitmap, width, height, transform } = raster;

  if (opts.skeleton === 'voronoi') {
    const v = voronoiMedialAxis(element.subPaths, transform, width, height, {
      samplingInterval: opts.voronoiSamplingInterval,
      spurWidthRatio: opts.spurWidthRatio,
      prune: opts.prune === 'none' ? 'none' : 'tegaki-width',
    });
    const skeleton = new Uint8Array(width * height);
    for (const pl of v.polylines) {
      for (const p of pl) {
        const px = Math.round(p.x);
        const py = Math.round(p.y);
        if (px >= 0 && px < width && py >= 0 && py < height) skeleton[py * width + px] = 1;
      }
    }
    return {
      skeleton,
      polylines: v.polylines,
      widths: v.widths,
      stats: { prunedCount: v.prunedCount, prunedLength: v.prunedLength, collapsed: 0, restored: 0, crossingsSeen: 0, crossingsStopped: 0 },
    };
  }

  const thinFns = {
    'zhang-suen': zhangSuenThin,
    'guo-hall': guoHallThin,
    lee: leeThin,
    thin: (b, w, h) => morphologicalThin(b, w, h, opts.thinMaxIterations),
  };
  const thinFn = thinFns[opts.skeleton] ?? zhangSuenThin;

  let skeleton;
  let collapsed = 0;
  if (opts.skeleton === 'medial-axis') {
    skeleton = medialAxisThin(bitmap, inverseDT, width, height);
  } else {
    const raw = thinFn(bitmap, width, height);
    const cleaned = cleanJunctionClusters(raw, inverseDT, width, height, thinFn, opts.junctionCleanupIterations);
    skeleton = cleaned.skeleton;
    collapsed = cleaned.collapsed;
  }
  const { restoredIdx, labels } = restoreErasedComponents(bitmap, skeleton, inverseDT, width, height);

  // Global radius of this element, used for the width-relative merge threshold.
  let rSum = 0;
  let rN = 0;
  for (let i = 0; i < skeleton.length; i++) {
    if (skeleton[i]) {
      rSum += inverseDT[i];
      rN++;
    }
  }
  const rGlobal = rN > 0 ? rSum / rN : 1;

  let mergeThreshold;
  if (opts.mergeMode === 'off') mergeThreshold = 0;
  else if (opts.mergeMode === 'tegaki') mergeThreshold = Math.max(width, height) * MERGE_THRESHOLD_RATIO;
  else mergeThreshold = opts.mergeRadiusFactor * rGlobal;

  const traced = traceAndSimplify(skeleton, width, height, {
    rdpTolerance: opts.rdpTolerance,
    lookback: opts.lookback,
    curvatureBias: opts.curvatureBias,
    mergeThreshold,
    prune: opts.prune,
    inverseDT,
    spurMinLength: opts.spurMinLength ?? undefined,
    spurWidthRatio: opts.spurWidthRatio,
    rtl: opts.rtl,
  });

  // ADAPTED: drop single-point strokes that are tracer residue, keep the ones
  // that are a whole mark.
  //
  // Tegaki keeps every leftover single pixel — in a glyph it is an i-dot — and
  // paints it at the glyph's AVERAGE stroke width. On a drawing, most of them
  // are residue left near a junction, and painting each as a disk of average
  // width put six visible blobs on landscape-square where there is no ink.
  //
  // The first discriminator we tried ("was it re-seeded by
  // restoreErasedComponents?") was wrong in both directions: it dropped real
  // ink dots on butterfly-wide (a small disk thins to a blob, so it is never
  // "erased" and never re-seeded) and kept landscape's residue. The right test
  // is structural — a single point is a real mark only if it is the ONLY thing
  // representing its connected ink component. If a multi-point stroke already
  // covers that component, the stray point is residue.
  // "Tiny" means a single pixel, or a chain under 2 px long — the latter is
  // what Tegaki's orientPolyline collapses into a dot when start and end are
  // within 5 px of each other, and on a drawing that collapse is what actually
  // produced landscape-square's phantom blobs.
  const componentOf = (p) => labels[Math.round(p.y) * width + Math.round(p.x)] ?? 0;
  const isTiny = (p) => p.length === 1 || pathLength(p) < 2;
  const covered = new Set();
  for (const p of traced.polylines) if (!isTiny(p)) for (const q of p) covered.add(componentOf(q));
  const polylines = traced.polylines.filter((p) => !isTiny(p) || !covered.has(componentOf(p[0])));
  const droppedSingles = traced.polylines.length - polylines.length;

  return {
    skeleton,
    polylines,
    widths: null,
    rGlobal,
    mergeThreshold,
    stats: {
      prunedCount: traced.prunedCount,
      prunedLength: traced.prunedLength,
      pruneThreshold: traced.pruneThreshold,
      tracedCount: traced.tracedCount,
      collapsed,
      restored: restoredIdx.length,
      droppedSingles,
      crossingsSeen: traced.crossingsSeen,
      crossingsStopped: traced.crossingsStopped,
    },
  };
}

/** Run the whole pipeline on one SVG's text. Returns strokes + graph + stats. */
export function convert(svgText, options = {}) {
  const opts = { ...DEFAULTS, ...options };
  const t0 = performance.now();
  const doc = parseSvg(svgText, opts.bezierTolerance);

  const allStrokes = [];
  const elementStats = [];

  for (const element of doc.elements) {
    const te0 = performance.now();
    const raster = rasterize(element.subPaths, element.bbox, { scale: opts.scale, resolution: opts.resolution });
    const { bitmap, width, height, transform } = raster;

    let filled = 0;
    for (let i = 0; i < bitmap.length; i++) if (bitmap[i]) filled++;
    if (filled === 0) {
      elementStats.push({ id: element.id, strokes: 0, filledPx: 0, note: 'empty raster' });
      continue;
    }

    const inverseDT = computeInverseDistanceTransform(bitmap, width, height, opts.dt);
    const sk = skeletonizeElement(element, raster, inverseDT, opts);

    const attachThreshold = sk.mergeThreshold ?? 3;
    const capped = extendCaps(sk.polylines, bitmap, inverseDT, width, height, opts.capExtend, attachThreshold, opts.capStyle);

    const strokes = orderStrokes(capped.polylines, inverseDT, width, height, sk.widths, opts.rtl);

    // Map to user space; width is in bitmap px so divide by the raster scale.
    for (const s of strokes) {
      const pts = s.points.map((p) => ({ ...toUserSpace(p, transform), t: p.t, width: p.width / transform.scaleX }));
      const lenUser = pathLength(pts);
      if (opts.minStrokeLength > 0 && lenUser < opts.minStrokeLength && s.class !== 'dot') continue;
      allStrokes.push({
        points: pts,
        length: lenUser,
        width: s.medianWidth / transform.scaleX,
        widthProfile: s.widthProfile.map((w) => w / transform.scaleX),
        class: s.class,
        reversed: s.reversed,
        rotated: s.rotated,
        fill: element.fill,
        fillOpacity: element.fillOpacity,
        elementId: element.id,
      });
    }

    elementStats.push({
      id: element.id,
      tag: element.tag,
      strokes: strokes.length,
      filledPx: filled,
      bitmap: `${width}x${height}`,
      rGlobal: sk.rGlobal ? +(sk.rGlobal / transform.scaleX).toFixed(2) : undefined,
      capsExtended: capped.extended,
      ms: +(performance.now() - te0).toFixed(1),
      ...sk.stats,
    });
  }

  // Global draw order: bodies in element order, dots last (Tegaki's rule applied
  // across the whole document rather than one glyph).
  allStrokes.sort((a, b) => (a.class === b.class ? 0 : a.class === 'dot' ? 1 : -1));
  allStrokes.forEach((s, i) => {
    s.orderIndex = i;
  });

  const graph = buildGraph(allStrokes, doc, opts);
  const svg = renderSvg(allStrokes, doc, opts);

  return {
    svg,
    graph,
    strokes: allStrokes,
    doc,
    stats: {
      elements: doc.elements.length,
      strokes: allStrokes.length,
      dots: allStrokes.filter((s) => s.class === 'dot').length,
      totalLength: +allStrokes.reduce((s, x) => s + x.length, 0).toFixed(1),
      medianWidth: +median(allStrokes.map((s) => s.width)).toFixed(2),
      ms: +(performance.now() - t0).toFixed(1),
      elementStats,
    },
  };
}

const fmt = (n) => (Math.abs(n) < 1e-4 ? '0' : String(+n.toFixed(2)));

export function renderSvg(strokes, doc, opts = {}) {
  const vb = doc.viewBox;
  const header =
    `<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n` +
    `<svg xmlns="http://www.w3.org/2000/svg" version="1.1"` +
    (vb ? ` viewBox="${vb.x} ${vb.y} ${vb.w} ${vb.h}"` : '') +
    `>\n`;

  const body = strokes
    .map((s) => {
      if (s.points.length === 1) {
        const p = s.points[0];
        return `<circle cx="${fmt(p.x)}" cy="${fmt(p.y)}" r="${fmt(s.width / 2)}" fill="${s.fill}"/>`;
      }
      const d = s.points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${fmt(p.x)} ${fmt(p.y)}`).join(' ');
      const op = s.fillOpacity !== undefined && s.fillOpacity !== 1 ? ` stroke-opacity="${s.fillOpacity}"` : '';
      return (
        `<path d="${d}" fill="none" stroke="${s.fill}" stroke-width="${fmt(s.width)}"` +
        ` stroke-linecap="round" stroke-linejoin="round"${op}/>`
      );
    })
    .join('\n');

  return `${header}${body}\n</svg>\n`;
}

/** Re-render the NORMALIZED input geometry as fills, to validate stage 1 (§9.2). */
export function renderNormalized(doc) {
  const vb = doc.viewBox;
  const header =
    `<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n` +
    `<svg xmlns="http://www.w3.org/2000/svg" version="1.1"` +
    (vb ? ` viewBox="${vb.x} ${vb.y} ${vb.w} ${vb.h}"` : '') +
    `>\n`;
  const body = doc.elements
    .map((e) => {
      const d = e.subPaths.map((sp) => sp.map((p, i) => `${i === 0 ? 'M' : 'L'} ${fmt(p.x)} ${fmt(p.y)}`).join(' ') + ' Z').join(' ');
      const op = e.fillOpacity !== 1 ? ` fill-opacity="${e.fillOpacity}"` : '';
      return `<path d="${d}" fill="${e.fill}" fill-rule="nonzero"${op}/>`;
    })
    .join('\n');
  return `${header}${body}\n</svg>\n`;
}
