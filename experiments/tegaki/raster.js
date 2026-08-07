// Ported from Tegaki packages/generator/src/processing/rasterize.ts (MIT, see VENDOR.md).
// Hand-written scanline fill with the nonzero winding rule. Binary, no
// anti-aliasing — deterministic by construction (report §15).
//
// ADAPTED: Tegaki always aspect-fits one glyph into `resolution x resolution`.
// We default to a fixed px-per-user-unit `scale` instead, because our elements
// live in one shared page coordinate system and a per-element 400px budget
// would give a big element and a small element wildly different effective
// resolutions. Tegaki's mode is still available via `opts.resolution`.

import { BITMAP_PADDING } from './constants.js';

export function rasterize(subPaths, boundingBox, opts = {}) {
  const bboxW = boundingBox.x2 - boundingBox.x1;
  const bboxH = boundingBox.y2 - boundingBox.y1;

  if (!(bboxW > 0) || !(bboxH > 0)) {
    return { bitmap: new Uint8Array(1), width: 1, height: 1, transform: { scaleX: 1, scaleY: 1, offsetX: boundingBox.x1 || 0, offsetY: boundingBox.y1 || 0 } };
  }

  const padFrac = opts.padding ?? BITMAP_PADDING;
  // ADAPTED: Tegaki's padding is 5% of the bbox, which is tiny for a long thin
  // element (a 4px pad on a 2px-wide stroke). Pad by at least a few pixels so a
  // stroke touching the bbox edge is not clipped by the border-guarded thinners.
  const scale = opts.resolution
    ? Math.min(opts.resolution / (bboxW * (1 + 2 * padFrac)), opts.resolution / (bboxH * (1 + 2 * padFrac)))
    : (opts.scale ?? 2);
  const padX = Math.max(bboxW * padFrac, 4 / scale);
  const padY = Math.max(bboxH * padFrac, 4 / scale);

  const minX = boundingBox.x1 - padX;
  const minY = boundingBox.y1 - padY;
  const totalW = bboxW + 2 * padX;
  const totalH = bboxH + 2 * padY;

  const w = Math.max(1, Math.ceil(totalW * scale));
  const h = Math.max(1, Math.ceil(totalH * scale));
  const bitmap = new Uint8Array(w * h);

  const scaleX = scale;
  const scaleY = scale;
  const offsetX = minX;
  const offsetY = minY;

  // Collect all edges, bucketed by scanline range so the per-row loop is not O(edges)
  const edges = [];
  for (const path of subPaths) {
    for (let i = 0; i < path.length - 1; i++) {
      const p1x = (path[i].x - offsetX) * scaleX;
      const p1y = (path[i].y - offsetY) * scaleY;
      const p2x = (path[i + 1].x - offsetX) * scaleX;
      const p2y = (path[i + 1].y - offsetY) * scaleY;
      if (p1y === p2y) continue; // skip horizontal edges
      edges.push({ x1: p1x, y1: p1y, x2: p2x, y2: p2y, direction: p1y > p2y ? 1 : -1 });
    }
    // Implicitly close open sub-paths so the winding rule is well defined
    const first = path[0];
    const last = path[path.length - 1];
    if (first.x !== last.x || first.y !== last.y) {
      const p1x = (last.x - offsetX) * scaleX;
      const p1y = (last.y - offsetY) * scaleY;
      const p2x = (first.x - offsetX) * scaleX;
      const p2y = (first.y - offsetY) * scaleY;
      if (p1y !== p2y) edges.push({ x1: p1x, y1: p1y, x2: p2x, y2: p2y, direction: p1y > p2y ? 1 : -1 });
    }
  }

  const buckets = Array.from({ length: h }, () => []);
  for (const e of edges) {
    const y0 = Math.max(0, Math.floor(Math.min(e.y1, e.y2) - 0.5));
    const y1 = Math.min(h - 1, Math.ceil(Math.max(e.y1, e.y2) + 0.5));
    for (let y = y0; y <= y1; y++) buckets[y].push(e);
  }

  const intersections = [];
  for (let y = 0; y < h; y++) {
    const scanY = y + 0.5;
    intersections.length = 0;
    for (const edge of buckets[y]) {
      const yMin = Math.min(edge.y1, edge.y2);
      const yMax = Math.max(edge.y1, edge.y2);
      if (scanY < yMin || scanY >= yMax) continue;
      const t = (scanY - edge.y1) / (edge.y2 - edge.y1);
      intersections.push({ x: edge.x1 + t * (edge.x2 - edge.x1), direction: edge.direction });
    }
    if (intersections.length === 0) continue;
    intersections.sort((a, b) => a.x - b.x);

    let winding = 0;
    let nextIdx = 0;
    const row = y * w;
    for (let x = 0; x < w; x++) {
      const pixelCenter = x + 0.5;
      while (nextIdx < intersections.length && intersections[nextIdx].x <= pixelCenter) {
        winding += intersections[nextIdx].direction;
        nextIdx++;
      }
      if (winding !== 0) bitmap[row + x] = 1;
    }
  }

  return { bitmap, width: w, height: h, transform: { scaleX, scaleY, offsetX, offsetY } };
}

// Pixel (i, j) covers [i, i+1) x [j, j+1), so its centre is at (i+0.5, j+0.5).
// Tegaki's toFontUnits ignores this and maps the pixel INDEX, which puts every
// recovered centerline half a pixel up and to the left of where it belongs. At
// 400px per glyph that is invisible; measured against a known synthetic
// centerline it is a systematic bias, so we correct it.
export function toUserSpace(p, transform) {
  return { x: (p.x + 0.5) / transform.scaleX + transform.offsetX, y: (p.y + 0.5) / transform.scaleY + transform.offsetY };
}

export function toBitmapSpace(p, transform) {
  return { x: (p.x - transform.offsetX) * transform.scaleX - 0.5, y: (p.y - transform.offsetY) * transform.scaleY - 0.5 };
}
