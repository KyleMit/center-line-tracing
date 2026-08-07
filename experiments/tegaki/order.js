// Ported from Tegaki packages/generator/src/processing/stroke-order.ts and
// font-units.ts (MIT, see VENDOR.md).
//
// Stage 5 — orientation, dot classification/deferral, arc-length t, per-point
// width. Report §9.8 asks for exactly this and Tegaki is the only working
// implementation we found. The ORDER itself comes from the tracer's greedy
// nearest-neighbour sequencing; this stage decides DIRECTION and re-sorts dots.

import { DOT_DIAG_RATIO, DOT_ISOLATION_RATIO, ORIENT_X_WEIGHT } from './constants.js';
import { getStrokeWidth } from './dt.js';

function dist(a, b) {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}

function pathLength(points) {
  let len = 0;
  for (let i = 1; i < points.length; i++) len += dist(points[i], points[i - 1]);
  return len;
}

/**
 * Orient a polyline so the natural pen-down point comes first.
 * Open: score each end as `y + x * ORIENT_X_WEIGHT` (weight 2 => x dominates,
 * i.e. left-to-right with top-to-bottom as tiebreak) and start from the lower.
 * Near-closed loop: you cannot reverse a loop into a natural start, so ROTATE
 * the ring to begin at its leftmost point.
 * Returns { points, reversed, rotated }.
 */
export function orientPolyline(points, rtl = false, loopTolerance = 5) {
  // NOTE: point objects are passed through by reference, so an `extended` flag
  // set upstream survives reversal/rotation.
  if (points.length < 2) return { points, reversed: false, rotated: false };
  const start = points[0];
  const end = points[points.length - 1];
  const xWeight = rtl ? -ORIENT_X_WEIGHT : ORIENT_X_WEIGHT;

  if (dist(start, end) < loopTolerance) {
    if (points.length === 2) return { points: [start], reversed: false, rotated: false };
    let bestIdx = 0;
    let bestX = points[0].x;
    let bestY = points[0].y;
    for (let i = 1; i < points.length; i++) {
      const p = points[i];
      const better = rtl ? p.x > bestX || (p.x === bestX && p.y < bestY) : p.x < bestX || (p.x === bestX && p.y < bestY);
      if (better) {
        bestX = p.x;
        bestY = p.y;
        bestIdx = i;
      }
    }
    if (bestIdx !== 0) return { points: [...points.slice(bestIdx), ...points.slice(1, bestIdx + 1)], reversed: false, rotated: true };
    return { points, reversed: false, rotated: false };
  }

  const startScore = start.y + start.x * xWeight;
  const endScore = end.y + end.x * xWeight;
  if (endScore < startScore) return { points: [...points].reverse(), reversed: true, rotated: false };
  return { points, reversed: false, rotated: false };
}

function bboxOf(points) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const p of points) {
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.y > maxY) maxY = p.y;
  }
  return { minX, minY, maxX, maxY };
}

const bboxDiag = (b) => Math.sqrt((b.maxX - b.minX) ** 2 + (b.maxY - b.minY) ** 2);

function bboxGap(a, b) {
  const dx = Math.max(0, Math.max(a.minX - b.maxX, b.minX - a.maxX));
  const dy = Math.max(0, Math.max(a.minY - b.maxY, b.minY - a.maxY));
  return Math.sqrt(dx * dx + dy * dy);
}

/**
 * "Small AND isolated" => a dot, drawn after every body stroke. Same predicate
 * shape as the pruner's "short AND attached" — a nice piece of design worth
 * copying: size alone decides nothing, size plus attachment decides everything.
 */
export function classifyDots(strokes) {
  if (strokes.length < 2) return;
  const boxes = strokes.map((s) => bboxOf(s.points));
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const b of boxes) {
    if (b.minX < minX) minX = b.minX;
    if (b.minY < minY) minY = b.minY;
    if (b.maxX > maxX) maxX = b.maxX;
    if (b.maxY > maxY) maxY = b.maxY;
  }
  const diag = Math.sqrt((maxX - minX) ** 2 + (maxY - minY) ** 2);
  if (diag <= 0) return;
  const maxDotDiag = diag * DOT_DIAG_RATIO;
  const isolationThreshold = diag * DOT_ISOLATION_RATIO;

  for (let i = 0; i < strokes.length; i++) {
    if (bboxDiag(boxes[i]) > maxDotDiag) continue;
    let isolated = true;
    for (let j = 0; j < strokes.length; j++) {
      if (j === i) continue;
      if (bboxGap(boxes[i], boxes[j]) <= isolationThreshold) {
        isolated = false;
        break;
      }
    }
    if (isolated) strokes[i].class = 'dot';
  }
}

function median(arr) {
  if (arr.length === 0) return 0;
  const s = [...arr].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/**
 * Turn traced polylines (bitmap space) into ordered, oriented strokes with a
 * per-point width profile and arc-length t.
 *
 * ADAPTED: Tegaki keeps only the per-point width for a variable-width renderer.
 * SVG cannot vary width along a path, so we additionally record the MEDIAN of
 * the profile as the stroke's emitted width. The median (rather than the mean)
 * matters: the inscribed radius spikes at junctions, and a mean is dragged up by
 * those spikes. The full profile is kept and goes into the graph JSON.
 */
export function orderStrokes(polylines, inverseDT, bitmapWidth, bitmapHeight, precomputedWidths, rtl = false) {
  if (polylines.length === 0) return [];
  const strokes = [];

  polylines.forEach((polyline, order) => {
    const { points: oriented, reversed, rotated } = orientPolyline(polyline, rtl);
    const totalLen = pathLength(oriented);
    const pWidths = precomputedWidths ? precomputedWidths[order] : null;

    let cumLen = 0;
    const points = oriented.map((p, i) => {
      if (i > 0) cumLen += dist(oriented[i - 1], p);
      const t = totalLen > 0 ? cumLen / totalLen : 0;
      const widthIdx = reversed ? oriented.length - 1 - i : i;
      const width = pWidths ? (pWidths[widthIdx] ?? 1) : getStrokeWidth(p.x, p.y, inverseDT, bitmapWidth, bitmapHeight);
      return { x: p.x, y: p.y, t, width, extended: !!p.extended };
    });

    // ADAPTED: cap-extended tips sit inside the cap, where the inscribed radius
    // is smaller than the pen radius. Sampling the DT there drags the width
    // profile down (on a width-20 capsule it pulled the median to 14). The pen
    // width at a cap IS the stroke width, so inherit it from the neighbour.
    for (let i = 0; i < points.length; i++) {
      if (!points[i].extended) continue;
      const src = i === 0 ? points[1] : points[i - 1];
      if (src) points[i].width = src.width;
    }

    strokes.push({
      points,
      order,
      length: totalLen,
      reversed,
      rotated,
      class: 'body',
      widthProfile: points.map((p) => p.width),
      medianWidth: median(points.map((p) => p.width)),
    });
  });

  // Tegaki's dot-width correction: an isolated blob's inscribed radius measures
  // the BLOB, not the pen. Replace single-point widths with the average of the
  // multi-point strokes' mean widths.
  const multi = strokes.filter((s) => s.points.length > 1);
  if (multi.length > 0) {
    const avgWidth = multi.reduce((sum, s) => sum + s.points.reduce((ps, p) => ps + p.width, 0) / s.points.length, 0) / multi.length;
    for (const s of strokes) {
      if (s.points.length === 1) {
        s.points[0].width = avgWidth;
        s.widthProfile = [avgWidth];
        s.medianWidth = avgWidth;
      }
    }
  }

  classifyDots(strokes);

  // Stable re-sort: bodies first, dots last, relative order preserved.
  if (strokes.some((s) => s.class === 'dot')) {
    strokes.sort((a, b) => (a.class === b.class ? a.order - b.order : a.class === 'dot' ? 1 : -1));
  }
  strokes.forEach((s, i) => {
    s.order = i;
  });

  return strokes;
}
