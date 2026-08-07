// Ported from Tegaki packages/generator/src/processing/voronoi-medial-axis.ts
// (MIT, see VENDOR.md).
//
// Sampled-boundary Voronoi medial axis. Geometry never touches pixels. This is
// the path that carries Tegaki's WIDTH-AWARE spur pruner (L < 1.5 * 2R_junction)
// and its short-edge contraction — the two pieces Track 8 wants.

import { Delaunay } from 'd3-delaunay';
import { SPUR_WIDTH_RATIO } from './constants.js';

// -0.5 keeps this on the same pixel-CENTRE convention as raster.js/toUserSpace,
// so the Voronoi path and the thinning path land in the same coordinate frame.
function toBitmapSpace(p, t) {
  return { x: (p.x - t.offsetX) * t.scaleX - 0.5, y: (p.y - t.offsetY) * t.scaleY - 0.5 };
}

function sampleBoundary(subPaths, transform, interval) {
  const points = [];
  for (const path of subPaths) {
    if (path.length < 2) continue;
    let accumulated = 0;
    points.push(toBitmapSpace(path[0], transform));
    for (let i = 1; i < path.length; i++) {
      const prev = toBitmapSpace(path[i - 1], transform);
      const curr = toBitmapSpace(path[i], transform);
      const dx = curr.x - prev.x;
      const dy = curr.y - prev.y;
      const segLen = Math.sqrt(dx * dx + dy * dy);
      if (segLen === 0) continue;
      accumulated += segLen;
      while (accumulated >= interval) {
        accumulated -= interval;
        const t = 1 - accumulated / segLen;
        points.push({ x: prev.x + dx * t, y: prev.y + dy * t });
      }
    }
  }
  return points;
}

function cross(ax, ay, bx, by, px, py) {
  return (bx - ax) * (py - ay) - (px - ax) * (by - ay);
}

function isInsideShape(point, rings) {
  let winding = 0;
  const px = point.x;
  const py = point.y;
  for (const ring of rings) {
    for (let i = 0; i < ring.length - 1; i++) {
      const ax = ring[i].x;
      const ay = ring[i].y;
      const bx = ring[i + 1].x;
      const by = ring[i + 1].y;
      if (ay <= py) {
        if (by > py && cross(ax, ay, bx, by, px, py) > 0) winding++;
      } else if (by <= py && cross(ax, ay, bx, by, px, py) < 0) winding--;
    }
  }
  return winding !== 0;
}

const pointKey = (p) => `${Math.round(p.x * 10)},${Math.round(p.y * 10)}`;

function edgeKey(ax, ay, bx, by) {
  const rax = Math.round(ax * 10);
  const ray = Math.round(ay * 10);
  const rbx = Math.round(bx * 10);
  const rby = Math.round(by * 10);
  if (rax < rbx || (rax === rbx && ray < rby)) return `${rax},${ray}-${rbx},${rby}`;
  return `${rbx},${rby}-${rax},${ray}`;
}

/** Grid-bucketed nearest boundary distance — Tegaki brute-forces this. */
function makeNearestBoundary(boundary, cellSize = 8) {
  const grid = new Map();
  const key = (cx, cy) => `${cx},${cy}`;
  for (const b of boundary) {
    const k = key(Math.floor(b.x / cellSize), Math.floor(b.y / cellSize));
    if (!grid.has(k)) grid.set(k, []);
    grid.get(k).push(b);
  }
  return (p) => {
    let best = Infinity;
    for (let r = 0; r < 64; r++) {
      const cx = Math.floor(p.x / cellSize);
      const cy = Math.floor(p.y / cellSize);
      for (let i = -r; i <= r; i++) {
        for (let j = -r; j <= r; j++) {
          if (r > 0 && Math.abs(i) !== r && Math.abs(j) !== r) continue;
          const cell = grid.get(key(cx + i, cy + j));
          if (!cell) continue;
          for (const b of cell) {
            const dx = p.x - b.x;
            const dy = p.y - b.y;
            const d = dx * dx + dy * dy;
            if (d < best) best = d;
          }
        }
      }
      // Once a candidate is found, one more ring guarantees correctness
      if (best < Infinity && Math.sqrt(best) <= r * cellSize) break;
    }
    return Math.sqrt(best);
  };
}

function contractShortEdges(adj, threshold) {
  let changed = true;
  while (changed) {
    changed = false;
    for (const [keyA, nodeA] of adj) {
      for (const keyB of nodeA.neighbors) {
        const nodeB = adj.get(keyB);
        if (!nodeB) continue;
        const dx = nodeA.point.x - nodeB.point.x;
        const dy = nodeA.point.y - nodeB.point.y;
        if (Math.sqrt(dx * dx + dy * dy) >= threshold) continue;

        const keepKey = nodeA.neighbors.size >= nodeB.neighbors.size ? keyA : keyB;
        const removeKey = keepKey === keyA ? keyB : keyA;
        const keepNode = adj.get(keepKey);
        const removeNode = adj.get(removeKey);
        for (const n of removeNode.neighbors) {
          if (n === keepKey) continue;
          const neighbor = adj.get(n);
          if (!neighbor) continue;
          neighbor.neighbors.delete(removeKey);
          neighbor.neighbors.add(keepKey);
          keepNode.neighbors.add(n);
        }
        keepNode.neighbors.delete(removeKey);
        keepNode.neighbors.delete(keepKey);
        adj.delete(removeKey);
        changed = true;
        break;
      }
      if (changed) break;
    }
  }
}

/**
 * THE WIDTH-AWARE PRUNER. Walk from each degree-1 node to the first degree-3+
 * node; if the accumulated length is under `ratio * (2 * R_at_junction)`, delete
 * the whole chain. Reaching another degree-1 node instead means the chain is a
 * bridge and is left alone.
 */
function pruneShortSpurs(adj, nearestBoundaryDist, ratio, stats) {
  let changed = true;
  while (changed) {
    changed = false;
    for (const [key, node] of adj) {
      if (node.neighbors.size !== 1) continue;
      let length = 0;
      let curr = key;
      let prev = '';
      const chain = [curr];

      while (true) {
        const cn = adj.get(curr);
        if (!cn) break;
        let next = null;
        for (const n of cn.neighbors) {
          if (n !== prev) {
            next = n;
            break;
          }
        }
        if (!next) break;
        const nextNode = adj.get(next);
        if (!nextNode) break;
        const dx = nextNode.point.x - cn.point.x;
        const dy = nextNode.point.y - cn.point.y;
        length += Math.sqrt(dx * dx + dy * dy);

        if (nextNode.neighbors.size >= 3) {
          const localWidth = nearestBoundaryDist(nextNode.point) * 2;
          if (length < localWidth * ratio) {
            for (const c of chain) {
              const cNode = adj.get(c);
              if (cNode) {
                for (const n of cNode.neighbors) adj.get(n)?.neighbors.delete(c);
                adj.delete(c);
              }
            }
            nextNode.neighbors.delete(curr);
            changed = true;
            if (stats) stats.prunedCount++;
            if (stats) stats.prunedLength += length;
          }
          break;
        }
        if (nextNode.neighbors.size <= 1) break; // a bridge — never prune
        prev = curr;
        curr = next;
        chain.push(curr);
      }
    }
  }
}

export function voronoiMedialAxis(subPaths, transform, bitmapWidth, bitmapHeight, opts = {}) {
  const samplingInterval = opts.samplingInterval ?? 2;
  const ratio = opts.spurWidthRatio ?? SPUR_WIDTH_RATIO;
  const prune = opts.prune ?? 'tegaki-width';

  const boundary = sampleBoundary(subPaths, transform, samplingInterval);
  if (boundary.length < 3) return { polylines: [], widths: [], prunedCount: 0, prunedLength: 0 };

  const rings = subPaths.map((sp) => sp.map((p) => toBitmapSpace(p, transform)));

  const coords = new Float64Array(boundary.length * 2);
  boundary.forEach((p, i) => {
    coords[i * 2] = p.x;
    coords[i * 2 + 1] = p.y;
  });
  const delaunay = new Delaunay(coords);
  const voronoi = delaunay.voronoi([0, 0, bitmapWidth, bitmapHeight]);

  const seen = new Set();
  const edges = [];
  for (let i = 0; i < boundary.length; i++) {
    const cell = voronoi.cellPolygon(i);
    if (!cell) continue;
    for (let j = 0; j < cell.length - 1; j++) {
      const [ax, ay] = cell[j];
      const [bx, by] = cell[j + 1];
      const k = edgeKey(ax, ay, bx, by);
      if (seen.has(k)) continue;
      seen.add(k);
      const a = { x: ax, y: ay };
      const b = { x: bx, y: by };
      const mid = { x: (ax + bx) / 2, y: (ay + by) / 2 };
      if (isInsideShape(mid, rings) && isInsideShape(a, rings) && isInsideShape(b, rings)) edges.push({ a, b });
    }
  }
  if (edges.length === 0) return { polylines: [], widths: [], prunedCount: 0, prunedLength: 0 };

  const adj = new Map();
  const getOrCreate = (p) => {
    const key = pointKey(p);
    if (!adj.has(key)) adj.set(key, { point: p, neighbors: new Set() });
    return key;
  };
  for (const { a, b } of edges) {
    const ka = getOrCreate(a);
    const kb = getOrCreate(b);
    if (ka === kb) continue;
    adj.get(ka).neighbors.add(kb);
    adj.get(kb).neighbors.add(ka);
  }

  contractShortEdges(adj, opts.contractThreshold ?? 2.0);

  const nearestBoundaryDist = makeNearestBoundary(boundary);
  const stats = { prunedCount: 0, prunedLength: 0 };
  if (prune !== 'none') pruneShortSpurs(adj, nearestBoundaryDist, ratio, stats);

  // Trace chains between non-degree-2 nodes
  const visitedEdges = new Set();
  const polylines = [];
  const widths = [];
  const allNodes = [...adj.keys()].sort((a, b) => {
    const da = adj.get(a).neighbors.size;
    const db = adj.get(b).neighbors.size;
    if (da === 1 && db !== 1) return -1;
    if (da !== 1 && db === 1) return 1;
    if (da >= 3 && db < 3) return -1;
    if (da < 3 && db >= 3) return 1;
    return 0;
  });

  for (const start of allNodes) {
    const node = adj.get(start);
    if (!node || node.neighbors.size === 0) continue;
    for (const firstNeighbor of node.neighbors) {
      if (visitedEdges.has(`${start}-${firstNeighbor}`)) continue;
      const chain = [node.point];
      let prev = start;
      let curr = firstNeighbor;
      visitedEdges.add(`${prev}-${curr}`);
      visitedEdges.add(`${curr}-${prev}`);
      while (true) {
        const currNode = adj.get(curr);
        if (!currNode) break;
        chain.push(currNode.point);
        if (currNode.neighbors.size !== 2) break;
        let next = null;
        for (const n of currNode.neighbors) {
          if (n !== prev) {
            next = n;
            break;
          }
        }
        if (!next || visitedEdges.has(`${curr}-${next}`)) break;
        visitedEdges.add(`${curr}-${next}`);
        visitedEdges.add(`${next}-${curr}`);
        prev = curr;
        curr = next;
      }
      if (chain.length >= 2) {
        let chainLen = 0;
        for (let i = 1; i < chain.length; i++) {
          const dx = chain[i].x - chain[i - 1].x;
          const dy = chain[i].y - chain[i - 1].y;
          chainLen += Math.sqrt(dx * dx + dy * dy);
        }
        if (chainLen < 2) continue;
        polylines.push(chain);
        widths.push(chain.map((p) => nearestBoundaryDist(p) * 2));
      }
    }
  }

  return { polylines, widths, ...stats };
}
