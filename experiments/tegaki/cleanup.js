// Ported from Tegaki packages/generator/src/processing/skeletonize/cleanup.ts
// (MIT, see VENDOR.md).
//
// This file is Tegaki's answer to thinning's junction smear, and it is the piece
// Track 6 most likely wants: Zhang-Suen turns a crossing into a blob of degree-3+
// pixels, which any tracer reads as a fistful of spurious micro-branches. The fix
// is to collapse each blob to its single most-medial pixel and re-attach the
// severed arms with straight lines, then re-thin, repeating until stable.

import { DX, DY, degree } from './thin.js';

/** 8-connected component labelling of a binary bitmap. Labels start at 1. */
export function labelComponents(bitmap, width, height) {
  const labels = new Int32Array(width * height);
  let nextLabel = 1;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = y * width + x;
      if (!bitmap[idx] || labels[idx]) continue;
      const label = nextLabel++;
      const queue = [idx];
      labels[idx] = label;
      while (queue.length > 0) {
        const ci = queue.pop();
        const cx = ci % width;
        const cy = (ci - cx) / width;
        for (let d = 0; d < 8; d++) {
          const nx = cx + DX[d];
          const ny = cy + DY[d];
          if (nx < 0 || nx >= width || ny < 0 || ny >= height) continue;
          const ni = ny * width + nx;
          if (bitmap[ni] && !labels[ni]) {
            labels[ni] = label;
            queue.push(ni);
          }
        }
      }
    }
  }
  return { labels, count: nextLabel };
}

/** Re-seed bitmap components that thinning erased entirely (i-dots, small marks). */
export function restoreErasedComponents(bitmap, skeleton, dt, width, height) {
  const { labels, count: nextLabel } = labelComponents(bitmap, width, height);

  const hasSkeleton = new Uint8Array(nextLabel);
  const bestIdx = new Int32Array(nextLabel).fill(-1);
  const bestDt = new Float32Array(nextLabel);
  for (let i = 0; i < bitmap.length; i++) {
    const label = labels[i];
    if (!label) continue;
    if (skeleton[i]) hasSkeleton[label] = 1;
    if (dt[i] > bestDt[label]) {
      bestDt[label] = dt[i];
      bestIdx[label] = i;
    }
  }
  const restoredIdx = [];
  for (let label = 1; label < nextLabel; label++) {
    if (!hasSkeleton[label] && bestIdx[label] >= 0) {
      skeleton[bestIdx[label]] = 1;
      restoredIdx.push(bestIdx[label]);
    }
  }
  return { restoredIdx, labels };
}

export function cleanJunctionClusters(skeleton, dt, width, height, thin, maxIterations) {
  let current = skeleton;
  let collapsed = 0;
  for (let iter = 0; iter < maxIterations; iter++) {
    const result = collapseClusterPass(current, dt, width, height);
    if (!result) break;
    collapsed += result.count;
    current = thin(result.bitmap, width, height);
  }
  return { skeleton: current, collapsed };
}

function collapseClusterPass(skeleton, dt, width, height) {
  const result = new Uint8Array(skeleton);
  const isJunction = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (result[y * width + x] && degree(x, y, result, width, height) >= 3) isJunction[y * width + x] = 1;
    }
  }

  const visited = new Uint8Array(width * height);
  let count = 0;

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (!isJunction[y * width + x] || visited[y * width + x]) continue;

      const cluster = [];
      const queue = [{ x, y }];
      visited[y * width + x] = 1;
      while (queue.length > 0) {
        const curr = queue.shift();
        cluster.push({ x: curr.x, y: curr.y, idx: curr.y * width + curr.x });
        for (let i = 0; i < 8; i++) {
          const nx = curr.x + DX[i];
          const ny = curr.y + DY[i];
          if (nx < 0 || nx >= width || ny < 0 || ny >= height) continue;
          const nIdx = ny * width + nx;
          if (isJunction[nIdx] && !visited[nIdx]) {
            visited[nIdx] = 1;
            queue.push({ x: nx, y: ny });
          }
        }
      }

      if (cluster.length <= 1) continue;
      count++;

      let bestIdx = cluster[0].idx;
      let bestDt = dt[bestIdx];
      for (const p of cluster) {
        if (dt[p.idx] > bestDt) {
          bestDt = dt[p.idx];
          bestIdx = p.idx;
        }
      }

      const clusterSet = new Set(cluster.map((p) => p.idx));
      const arms = [];
      for (const p of cluster) {
        for (let i = 0; i < 8; i++) {
          const nx = p.x + DX[i];
          const ny = p.y + DY[i];
          if (nx < 0 || nx >= width || ny < 0 || ny >= height) continue;
          const nIdx = ny * width + nx;
          if (result[nIdx] && !clusterSet.has(nIdx)) arms.push({ x: nx, y: ny });
        }
      }

      for (const p of cluster) result[p.idx] = 0;
      result[bestIdx] = 1;
      const bestX = bestIdx % width;
      const bestY = (bestIdx - bestX) / width;
      for (const arm of arms) bresenham(result, bestX, bestY, arm.x, arm.y, width);
    }
  }

  return count > 0 ? { bitmap: result, count } : null;
}

function bresenham(bitmap, x0, y0, x1, y1, width) {
  const dx = Math.abs(x1 - x0);
  const dy = Math.abs(y1 - y0);
  const sx = x0 < x1 ? 1 : -1;
  const sy = y0 < y1 ? 1 : -1;
  let err = dx - dy;
  let cx = x0;
  let cy = y0;
  while (true) {
    bitmap[cy * width + cx] = 1;
    if (cx === x1 && cy === y1) break;
    const e2 = 2 * err;
    if (e2 > -dy) {
      err -= dy;
      cx += sx;
    }
    if (e2 < dx) {
      err += dx;
      cy += sy;
    }
  }
}
