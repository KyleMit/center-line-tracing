// Ported from Tegaki packages/generator/src/processing/trace.ts (MIT, see VENDOR.md).
//
// The most sophisticated stage in the generator. Three ideas worth having:
//   1. estimateDirection extrapolates CURVATURE, not just tangent, so a curved
//      stroke picks the right branch at a junction.
//   2. pickStraightest/peekAhead compare whole BRANCH directions (12 px ahead)
//      instead of the 8 possible 1-pixel steps.
//   3. shouldStopAtJunction decides "am I the stem of a T or the through-stroke
//      of an X?" locally — the crossing-ambiguity decision other backends punt.
//
// Pruning: BOTH of Tegaki's pruners live here, switchable, because the A/B
// between naive length pruning (its thinning path) and width-aware L/(2R)
// pruning (its Voronoi path) is this track's main contribution to Track 8.

import {
  JUNCTION_ALIGNMENT_COS,
  JUNCTION_CROSSING_COS,
  RDP_TOLERANCE,
  SMOOTH_KINK_MIN_ANGLE,
  SMOOTH_KINK_THRESHOLD,
  SPUR_LENGTH_CAP,
  SPUR_LENGTH_RATIO,
  SPUR_WIDTH_RATIO,
  TRACE_CURVATURE_BIAS,
  TRACE_LOOKBACK,
} from './constants.js';
import { DX, DY, degree } from './thin.js';
import { sampleRadius } from './dt.js';

function getNeighbors(x, y, skeleton, width, height) {
  const neighbors = [];
  for (let i = 0; i < 8; i++) {
    const nx = x + DX[i];
    const ny = y + DY[i];
    if (nx >= 0 && nx < width && ny >= 0 && ny < height && skeleton[ny * width + nx]) neighbors.push({ x: nx, y: ny });
  }
  return neighbors;
}

function dist(a, b) {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}

export function pathLength(points) {
  let len = 0;
  for (let i = 1; i < points.length; i++) len += dist(points[i], points[i - 1]);
  return len;
}

/**
 * dir = recent + curvatureBias * (recent - older), over a `lookback` window
 * split into halves. bias 0 = plain tangent; bias 1 = full extrapolation of the
 * turning rate. Tegaki ships 0.5.
 */
function estimateDirection(chain, cx, cy, lookback, curvatureBias) {
  const n = chain.length;
  const windowSize = Math.min(n - 1, lookback);
  if (windowSize < 4 || curvatureBias === 0) {
    const prev = chain[n - 1 - windowSize];
    return { dirX: cx - prev.x, dirY: cy - prev.y };
  }
  const halfSize = Math.floor(windowSize / 2);
  const midPoint = chain[n - 1 - halfSize];
  const oldPoint = chain[n - 1 - windowSize];
  const oldDirX = midPoint.x - oldPoint.x;
  const oldDirY = midPoint.y - oldPoint.y;
  const recentDirX = cx - midPoint.x;
  const recentDirY = cy - midPoint.y;
  return {
    dirX: recentDirX + curvatureBias * (recentDirX - oldDirX),
    dirY: recentDirY + curvatureBias * (recentDirY - oldDirY),
  };
}

/** Follow a branch up to `steps` px without touching visited state. */
function peekAhead(cx, cy, start, skeleton, visited, width, height, steps) {
  let px = cx;
  let py = cy;
  let x = start.x;
  let y = start.y;
  for (let step = 0; step < steps; step++) {
    const neighbors = getNeighbors(x, y, skeleton, width, height);
    const forward = neighbors.filter((n) => (n.x !== px || n.y !== py) && !visited[n.y * width + n.x]);
    if (forward.length === 0) break;
    const dx = x - px;
    const dy = y - py;
    let nextP = forward[0];
    if (forward.length > 1 && (dx !== 0 || dy !== 0)) {
      const dLen = Math.sqrt(dx * dx + dy * dy);
      let bestC = -2;
      for (const f of forward) {
        const fdx = f.x - x;
        const fdy = f.y - y;
        const fLen = Math.sqrt(fdx * fdx + fdy * fdy);
        if (fLen === 0) continue;
        const c = (dx * fdx + dy * fdy) / (dLen * fLen);
        if (c > bestC) {
          bestC = c;
          nextP = f;
        }
      }
    }
    px = x;
    py = y;
    x = nextP.x;
    y = nextP.y;
  }
  return { x, y };
}

function pickStraightest(candidates, cx, cy, dirX, dirY, skeleton, visited, width, height, lookback) {
  const dirLen = Math.sqrt(dirX * dirX + dirY * dirY);
  let best = candidates[0];
  let bestCos = -2;
  for (const c of candidates) {
    const ahead = peekAhead(cx, cy, c, skeleton, visited, width, height, lookback);
    const cdx = ahead.x - cx;
    const cdy = ahead.y - cy;
    const cLen = Math.sqrt(cdx * cdx + cdy * cdy);
    if (dirLen === 0 || cLen === 0) continue;
    const cos = (dirX * cdx + dirY * cdy) / (dirLen * cLen);
    if (cos > bestCos) {
      bestCos = cos;
      best = c;
    }
  }
  return best;
}

/**
 * "Am I the stem of a T, or the through-stroke of an X?"
 * Stop iff (a) some pair of outgoing branches is near-opposite (a crossing
 * stroke passes through here) AND (b) my incoming direction aligns with none of
 * them. Report §2.2 / our `crossing ambiguity` tag.
 */
function shouldStopAtJunction(unvisited, cx, cy, dirX, dirY, skeleton, visited, width, height, lookback, stats) {
  if (unvisited.length < 2) return false;
  const branchDirs = [];
  for (const b of unvisited) {
    const ahead = peekAhead(cx, cy, b, skeleton, visited, width, height, lookback);
    const dx = ahead.x - cx;
    const dy = ahead.y - cy;
    const len = Math.sqrt(dx * dx + dy * dy);
    if (len > 0) branchDirs.push({ dx: dx / len, dy: dy / len });
  }

  let hasStraightPair = false;
  for (let i = 0; i < branchDirs.length && !hasStraightPair; i++) {
    for (let j = i + 1; j < branchDirs.length; j++) {
      if (branchDirs[i].dx * branchDirs[j].dx + branchDirs[i].dy * branchDirs[j].dy < JUNCTION_CROSSING_COS) {
        hasStraightPair = true;
        break;
      }
    }
  }
  if (!hasStraightPair) return false;
  if (stats) stats.crossingsSeen++;

  const dirLen = Math.sqrt(dirX * dirX + dirY * dirY);
  if (dirLen === 0) return true;
  const ndx = dirX / dirLen;
  const ndy = dirY / dirLen;
  let maxAlign = -2;
  for (const bd of branchDirs) {
    const align = ndx * bd.dx + ndy * bd.dy;
    if (align > maxAlign) maxAlign = align;
  }
  const stop = maxAlign < JUNCTION_ALIGNMENT_COS;
  if (stop && stats) stats.crossingsStopped++;
  return stop;
}

function traceChain(startX, startY, skeleton, visited, width, height, lookback, curvatureBias, stats) {
  const chain = [{ x: startX, y: startY }];
  visited[startY * width + startX] = 1;
  let cx = startX;
  let cy = startY;

  while (true) {
    const neighbors = getNeighbors(cx, cy, skeleton, width, height);
    const unvisited = neighbors.filter((n) => !visited[n.y * width + n.x]);

    if (unvisited.length === 0) {
      const visitedJunction = neighbors.find((n) => visited[n.y * width + n.x] && degree(n.x, n.y, skeleton, width, height) >= 3);
      if (visitedJunction) chain.push(visitedJunction);
      break;
    }

    let next;
    if (chain.length >= 2 && unvisited.length > 1) {
      const { dirX, dirY } = estimateDirection(chain, cx, cy, lookback, curvatureBias);
      if (shouldStopAtJunction(unvisited, cx, cy, dirX, dirY, skeleton, visited, width, height, lookback, stats)) break;
      next = pickStraightest(unvisited, cx, cy, dirX, dirY, skeleton, visited, width, height, lookback);
    } else if (unvisited.length === 1) {
      next = unvisited[0];
    } else {
      next = unvisited.find((n) => degree(n.x, n.y, skeleton, width, height) <= 2) ?? unvisited[0];
    }

    visited[next.y * width + next.x] = 1;
    chain.push(next);
    cx = next.x;
    cy = next.y;
    if (degree(cx, cy, skeleton, width, height) <= 1) break;
  }
  return chain;
}

// ── RDP ────────────────────────────────────────────────────────────────────
function perpendicularDistance(point, lineStart, lineEnd) {
  const dx = lineEnd.x - lineStart.x;
  const dy = lineEnd.y - lineStart.y;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return dist(point, lineStart);
  const t = ((point.x - lineStart.x) * dx + (point.y - lineStart.y) * dy) / lenSq;
  const projX = lineStart.x + t * dx;
  const projY = lineStart.y + t * dy;
  const ex = point.x - projX;
  const ey = point.y - projY;
  return Math.sqrt(ex * ex + ey * ey);
}

export function rdpSimplify(points, tolerance = RDP_TOLERANCE) {
  if (points.length <= 2) return points;
  const first = points[0];
  const last = points[points.length - 1];
  let maxDist = 0;
  let maxIdx = 0;
  for (let i = 1; i < points.length - 1; i++) {
    const d = perpendicularDistance(points[i], first, last);
    if (d > maxDist) {
      maxDist = d;
      maxIdx = i;
    }
  }
  if (maxDist > tolerance) {
    const left = rdpSimplify(points.slice(0, maxIdx + 1), tolerance);
    const right = rdpSimplify(points.slice(maxIdx), tolerance);
    return [...left.slice(0, -1), ...right];
  }
  return [first, last];
}

// ── Merging ────────────────────────────────────────────────────────────────
function mergePolylines(polylines, threshold) {
  if (polylines.length <= 1) return polylines;
  const used = new Uint8Array(polylines.length);
  const merged = [];
  for (let i = 0; i < polylines.length; i++) {
    if (used[i]) continue;
    used[i] = 1;
    let chain = [...polylines[i]];
    let changed = true;
    while (changed) {
      changed = false;
      for (let j = 0; j < polylines.length; j++) {
        if (used[j]) continue;
        const other = polylines[j];
        const chainStart = chain[0];
        const chainEnd = chain[chain.length - 1];
        const otherStart = other[0];
        const otherEnd = other[other.length - 1];
        if (dist(chainEnd, otherStart) < threshold) chain = [...chain, ...other.slice(1)];
        else if (dist(chainEnd, otherEnd) < threshold) chain = [...chain, ...[...other].reverse().slice(1)];
        else if (dist(chainStart, otherEnd) < threshold) chain = [...other, ...chain.slice(1)];
        else if (dist(chainStart, otherStart) < threshold) chain = [...[...other].reverse(), ...chain.slice(1)];
        else continue;
        used[j] = 1;
        changed = true;
      }
    }
    merged.push(chain);
  }
  return merged;
}

// ── Junction-kink smoothing (three independent removal tests) ──────────────
function smoothJunctionKinks(polyline, lookback, curvatureBias, minAngle = (SMOOTH_KINK_MIN_ANGLE * Math.PI) / 180) {
  if (polyline.length <= 2) return polyline;
  const result = [polyline[0]];

  for (let i = 1; i < polyline.length - 1; i++) {
    const prev = result[result.length - 1];
    const curr = polyline[i];
    const next = polyline[i + 1];
    const ax = prev.x - curr.x;
    const ay = prev.y - curr.y;
    const bx = next.x - curr.x;
    const by = next.y - curr.y;
    const magA = Math.sqrt(ax * ax + ay * ay);
    const magB = Math.sqrt(bx * bx + by * by);
    if (magA === 0 || magB === 0) continue;

    // 1. classic angle test
    const cosAngle = (ax * bx + ay * by) / (magA * magB);
    if (Math.acos(Math.max(-1, Math.min(1, cosAngle))) >= minAngle) continue;

    // 2. curvature prediction test
    if (result.length >= 3) {
      const { dirX, dirY } = estimateDirection(result, prev.x, prev.y, lookback, curvatureBias);
      const predLen = Math.sqrt(dirX * dirX + dirY * dirY);
      if (predLen > 0) {
        const skipX = next.x - prev.x;
        const skipY = next.y - prev.y;
        const skipLen = Math.sqrt(skipX * skipX + skipY * skipY);
        const toCurrX = curr.x - prev.x;
        const toCurrY = curr.y - prev.y;
        const toCurrLen = Math.sqrt(toCurrX * toCurrX + toCurrY * toCurrY);
        if (skipLen > 0 && toCurrLen > 0) {
          const cosSkip = (dirX * skipX + dirY * skipY) / (predLen * skipLen);
          const cosThrough = (dirX * toCurrX + dirY * toCurrY) / (predLen * toCurrLen);
          if (cosSkip - cosThrough > SMOOTH_KINK_THRESHOLD) continue;
        }
      }
    }

    // 3. smoothness test — is curr a junction detour?
    if (result.length >= 2) {
      const prevPrev = result[result.length - 2];
      const withX = curr.x - prev.x;
      const withY = curr.y - prev.y;
      const withLen = Math.sqrt(withX * withX + withY * withY);
      const withoutX = next.x - prev.x;
      const withoutY = next.y - prev.y;
      const withoutLen = Math.sqrt(withoutX * withoutX + withoutY * withoutY);
      const inX = prev.x - prevPrev.x;
      const inY = prev.y - prevPrev.y;
      const inLen = Math.sqrt(inX * inX + inY * inY);
      if (inLen > 0 && withLen > 0 && withoutLen > 0) {
        const cosWithCurr = (inX * withX + inY * withY) / (inLen * withLen);
        const cosWithout = (inX * withoutX + inY * withoutY) / (inLen * withoutLen);
        if (cosWithout - cosWithCurr > SMOOTH_KINK_THRESHOLD) continue;
      }
    }

    result.push(curr);
  }
  result.push(polyline[polyline.length - 1]);
  return result;
}

// ── PRUNING — the two variants, side by side ──────────────────────────────

/**
 * Tegaki's thinning-path pruner, verbatim in spirit:
 *   keep if pathLength >= min(0.08 * max(w,h), 10)   OR   the polyline is isolated.
 *
 * Two observations (see NOTES.md): the threshold is ABSOLUTE (no radius term
 * anywhere), and it needs a hard 10 px cap to stop small shapes being erased —
 * which is the tell-tale sign of a threshold that should have been scale-free.
 * The isolation clause is the good half: "short AND attached" is a much better
 * spur predicate than "short".
 */
export function pruneTegakiLength(polylines, width, height, mergeThreshold, spurMinLength) {
  const effectiveSpurMin = spurMinLength ?? Math.min(Math.round(Math.max(width, height) * SPUR_LENGTH_RATIO), SPUR_LENGTH_CAP);
  const removed = [];
  const kept = polylines.filter((p) => {
    if (pathLength(p) >= effectiveSpurMin) return true;
    const pStart = p[0];
    const pEnd = p[p.length - 1];
    const isConnected = polylines.some((other) => {
      if (other === p) return false;
      const oStart = other[0];
      const oEnd = other[other.length - 1];
      return (
        dist(pStart, oStart) < mergeThreshold ||
        dist(pStart, oEnd) < mergeThreshold ||
        dist(pEnd, oStart) < mergeThreshold ||
        dist(pEnd, oEnd) < mergeThreshold
      );
    });
    if (isConnected) removed.push(p);
    return !isConnected;
  });
  return { kept, removed, threshold: effectiveSpurMin };
}

/**
 * Tegaki's Voronoi-path pruner, lifted onto the raster path — the point of this
 * track. A terminal branch is a spur iff
 *
 *     L  <  SPUR_WIDTH_RATIO * (2 * R_parent)
 *
 * i.e. `L / (2 R) < 1.5`: shorter than 1.5 local stroke widths. Report §10.1's
 * scale-free feature, with the radius sampled at the junction end of the branch.
 * `R_parent` is read from the inverse distance transform rather than from
 * nearest-boundary-sample distance, which is the same quantity on the raster path.
 *
 * `attachThreshold` decides which end of a polyline counts as "attached to a
 * junction": an endpoint within that distance of another polyline's interior or
 * endpoint. A polyline attached at BOTH ends is a bridge and is never pruned,
 * matching Tegaki's "if we hit another endpoint, don't prune (it's a bridge)".
 */
export function pruneTegakiWidth(polylines, inverseDT, skeleton, width, height, ratio = SPUR_WIDTH_RATIO) {
  // Attachment is decided TOPOLOGICALLY, from the skeleton's degree at the
  // endpoint — degree 1 is a free end, anything else sits on a junction.
  //
  // The first version of this used a metric test ("is this endpoint within the
  // merge threshold of any point of another polyline?"), mirroring how Tegaki's
  // length pruner decides isolation. On a drawing that is useless: the merge
  // threshold is ~1.5 stroke radii, the polylines are dense pixel chains, and
  // so essentially EVERY endpoint is "near" some other stroke. Every branch got
  // classified as a two-ended bridge and the pruner removed exactly nothing.
  // Tegaki's own Voronoi pruner is topological (walk from a degree-1 node to
  // the first degree-3+ node); this restores that on the raster graph.
  const freeEnd = (p) => degree(Math.round(p.x), Math.round(p.y), skeleton, width, height) <= 1;

  const removed = [];
  const kept = [];
  polylines.forEach((p) => {
    const startAttached = !freeEnd(p[0]);
    const endAttached = !freeEnd(p[p.length - 1]);
    // Not attached at all -> isolated mark, keep (Tegaki's isolation clause).
    // Attached at both ends -> a bridge between two junctions, keep (Tegaki:
    // "if we hit another endpoint, don't prune (it's a bridge)").
    if ((!startAttached && !endAttached) || (startAttached && endAttached)) {
      kept.push(p);
      return;
    }
    const junctionEnd = startAttached ? p[0] : p[p.length - 1];
    const rParent = sampleRadius(junctionEnd.x, junctionEnd.y, inverseDT, width, height);
    const localWidth = 2 * rParent;
    if (pathLength(p) < localWidth * ratio) removed.push(p);
    else kept.push(p);
  });
  return { kept, removed, threshold: ratio };
}

// ── Entry point ────────────────────────────────────────────────────────────
export function traceAndSimplify(skeleton, width, height, opts = {}) {
  const {
    rdpTolerance = RDP_TOLERANCE,
    lookback = TRACE_LOOKBACK,
    curvatureBias = TRACE_CURVATURE_BIAS,
    mergeThreshold,
    prune = 'tegaki-width',
    inverseDT = null,
    spurMinLength,
    spurWidthRatio = SPUR_WIDTH_RATIO,
    rtl = false,
  } = opts;

  const visited = new Uint8Array(width * height);
  const polylines = [];
  const stats = { crossingsSeen: 0, crossingsStopped: 0 };

  const endpoints = [];
  let minX = width;
  let maxX = 0;
  let minY = height;
  let maxY = 0;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (!skeleton[y * width + x]) continue;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
      if (degree(x, y, skeleton, width, height) === 1) endpoints.push({ x, y });
    }
  }

  // Greedy nearest-neighbour sequencing from the writing-entry side. This IS
  // Tegaki's stroke-order logic — see NOTES.md Part 1, stage 5b.
  let lastEnd = { x: rtl ? maxX : minX, y: (minY + maxY) / 2 };

  while (true) {
    let bestIdx = -1;
    let bestDist = Infinity;
    for (let i = 0; i < endpoints.length; i++) {
      const ep = endpoints[i];
      if (visited[ep.y * width + ep.x]) continue;
      const d = dist(ep, lastEnd);
      if (d < bestDist) {
        bestDist = d;
        bestIdx = i;
      }
    }
    if (bestIdx < 0) break;
    const ep = endpoints[bestIdx];
    const chain = traceChain(ep.x, ep.y, skeleton, visited, width, height, lookback, curvatureBias, stats);
    if (chain.length > 1) {
      if (dist(chain[chain.length - 1], lastEnd) < dist(chain[0], lastEnd)) chain.reverse();
      polylines.push(chain);
      lastEnd = chain[chain.length - 1];
    }
  }

  // Second pass: loops with no endpoints, isolated pixels.
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (!skeleton[y * width + x] || visited[y * width + x]) continue;
      const chain = traceChain(x, y, skeleton, visited, width, height, lookback, curvatureBias, stats);
      if (chain.length >= 1) polylines.push(chain);
    }
  }

  const mt = mergeThreshold ?? Math.max(width, height) * 0.08;
  const mergedPolylines = mergePolylines(polylines, mt);
  const smoothed = mergedPolylines.map((p) => smoothJunctionKinks(p, lookback, curvatureBias));

  let pruneResult;
  if (prune === 'tegaki-width' && inverseDT) {
    pruneResult = pruneTegakiWidth(smoothed, inverseDT, skeleton, width, height, spurWidthRatio);
  } else if (prune === 'none') {
    pruneResult = { kept: smoothed, removed: [], threshold: 0 };
  } else {
    pruneResult = pruneTegakiLength(smoothed, width, height, mt, spurMinLength);
  }

  return {
    polylines: pruneResult.kept.map((p) => rdpSimplify(p, rdpTolerance)),
    prunedCount: pruneResult.removed.length,
    prunedLength: pruneResult.removed.reduce((s, p) => s + pathLength(p), 0),
    pruneThreshold: pruneResult.threshold,
    tracedCount: polylines.length,
    mergedCount: mergedPolylines.length,
    ...stats,
  };
}
