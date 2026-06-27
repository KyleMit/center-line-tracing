#!/usr/bin/env node
/**
 * Convert a filled-shape SVG line drawing into a stroked-line SVG.
 *
 * Install dependencies:
 *   npm install sharp pngjs
 *
 * Usage:
 *   node convert-filled-svg-to-stroked-lines.mjs large-image-drawing.svg \
 *     --output large-image-drawing-lines.svg
 */

import fs from 'node:fs/promises';
import path from 'node:path';
import sharp from 'sharp';
import { PNG } from 'pngjs';

const SVG_NS = 'http://www.w3.org/2000/svg';

const NEIGHBORS_8 = [
  [-1, -1], [-1, 0], [-1, 1],
  [0, -1],           [0, 1],
  [1, -1],  [1, 0],  [1, 1],
];

function parseArgs(argv) {
  const args = {
    input: null,
    output: null,
    alphaThreshold: 48,
    minObjectSize: 20,
    minPathLength: 15,
    simplifyEpsilon: 2.2,
    minStrokeWidth: 6,
    maxStrokeWidth: 18,
  };

  for (let i = 2; i < argv.length; i++) {
    const token = argv[i];
    const next = () => argv[++i];

    if (token === '--output' || token === '-o') args.output = next();
    else if (token === '--alpha-threshold') args.alphaThreshold = Number(next());
    else if (token === '--min-object-size') args.minObjectSize = Number(next());
    else if (token === '--min-path-length') args.minPathLength = Number(next());
    else if (token === '--simplify-epsilon') args.simplifyEpsilon = Number(next());
    else if (token === '--min-stroke-width') args.minStrokeWidth = Number(next());
    else if (token === '--max-stroke-width') args.maxStrokeWidth = Number(next());
    else if (!args.input) args.input = token;
    else throw new Error(`Unexpected argument: ${token}`);
  }

  if (!args.input) {
    throw new Error('Usage: node convert-filled-svg-to-stroked-lines.mjs input.svg --output output.svg');
  }

  return args;
}

function readViewBox(svgText) {
  const match = svgText.match(/viewBox=["']([^"']+)["']/i);
  if (!match) throw new Error('Input SVG must have a viewBox.');

  const values = match[1].trim().split(/[\s,]+/).map(Number);

  if (values.length !== 4 || values.some(Number.isNaN)) {
    throw new Error(`Expected four viewBox values, got: ${match[1]}`);
  }

  return {
    x: Math.round(values[0]),
    y: Math.round(values[1]),
    width: Math.round(values[2]),
    height: Math.round(values[3]),
  };
}

function extractFillColors(svgText) {
  const colors = new Set();

  const regexes = [
    /fill=["'](#[0-9a-fA-F]{6})["']/g,
    /fill:\s*(#[0-9a-fA-F]{6})/g,
  ];

  for (const regex of regexes) {
    for (const match of svgText.matchAll(regex)) {
      colors.add(match[1].toUpperCase());
    }
  }

  if (!colors.size) {
    throw new Error('No explicit hex fill colors found. This script expects filled line-shape SVGs.');
  }

  return [...colors].sort();
}

function hexToRgb(hex) {
  return [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16));
}

async function renderSvgToRgba(svgPath, width, height) {
  const pngBuffer = await sharp(svgPath)
    .resize(width, height, { fit: 'fill' })
    .png()
    .toBuffer();

  const png = PNG.sync.read(pngBuffer);

  return {
    data: png.data,
    width: png.width,
    height: png.height,
  };
}

function index(width, y, x) {
  return y * width + x;
}

function inBounds(width, height, y, x) {
  return y >= 0 && y < height && x >= 0 && x < width;
}

function dilate(mask, width, height) {
  const out = new Uint8Array(mask.length);

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      let value = 0;

      for (const [dy, dx] of [[0, 0], ...NEIGHBORS_8]) {
        const yy = y + dy;
        const xx = x + dx;

        if (inBounds(width, height, yy, xx) && mask[index(width, yy, xx)]) {
          value = 1;
          break;
        }
      }

      out[index(width, y, x)] = value;
    }
  }

  return out;
}

function erode(mask, width, height) {
  const out = new Uint8Array(mask.length);

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      let value = 1;

      for (const [dy, dx] of [[0, 0], ...NEIGHBORS_8]) {
        const yy = y + dy;
        const xx = x + dx;

        if (!inBounds(width, height, yy, xx) || !mask[index(width, yy, xx)]) {
          value = 0;
          break;
        }
      }

      out[index(width, y, x)] = value;
    }
  }

  return out;
}

function closing(mask, width, height) {
  return erode(dilate(mask, width, height), width, height);
}

function removeSmallObjects(mask, width, height, minSize) {
  const out = new Uint8Array(mask);
  const seen = new Uint8Array(mask.length);
  const queue = [];

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const start = index(width, y, x);

      if (!out[start] || seen[start]) continue;

      queue.length = 0;
      queue.push(start);
      seen[start] = 1;

      const component = [start];

      for (let qi = 0; qi < queue.length; qi++) {
        const p = queue[qi];
        const py = Math.floor(p / width);
        const px = p % width;

        for (const [dy, dx] of NEIGHBORS_8) {
          const yy = py + dy;
          const xx = px + dx;

          if (!inBounds(width, height, yy, xx)) continue;

          const q = index(width, yy, xx);

          if (out[q] && !seen[q]) {
            seen[q] = 1;
            queue.push(q);
            component.push(q);
          }
        }
      }

      if (component.length < minSize) {
        for (const p of component) out[p] = 0;
      }
    }
  }

  return out;
}

function transitionCount(neighbors) {
  let count = 0;

  for (let i = 0; i < neighbors.length; i++) {
    if (neighbors[i] === 0 && neighbors[(i + 1) % neighbors.length] === 1) {
      count++;
    }
  }

  return count;
}

function skeletonizeZhangSuen(input, width, height) {
  const img = new Uint8Array(input);
  let changed = true;
  const toDelete = [];

  const neighborValues = (y, x) => {
    const coords = [
      [-1, 0],
      [-1, 1],
      [0, 1],
      [1, 1],
      [1, 0],
      [1, -1],
      [0, -1],
      [-1, -1],
    ];

    return coords.map(([dy, dx]) => img[index(width, y + dy, x + dx)] ? 1 : 0);
  };

  while (changed) {
    changed = false;

    for (let step = 0; step < 2; step++) {
      toDelete.length = 0;

      for (let y = 1; y < height - 1; y++) {
        for (let x = 1; x < width - 1; x++) {
          const p = index(width, y, x);
          if (!img[p]) continue;

          const n = neighborValues(y, x);
          const nSum = n.reduce((a, b) => a + b, 0);
          const transitions = transitionCount(n);

          const p2 = n[0];
          const p4 = n[2];
          const p6 = n[4];
          const p8 = n[6];

          const c1 = nSum >= 2 && nSum <= 6;
          const c2 = transitions === 1;
          const c3 = step === 0 ? p2 * p4 * p6 === 0 : p2 * p4 * p8 === 0;
          const c4 = step === 0 ? p4 * p6 * p8 === 0 : p2 * p6 * p8 === 0;

          if (c1 && c2 && c3 && c4) {
            toDelete.push(p);
          }
        }
      }

      if (toDelete.length) {
        changed = true;

        for (const p of toDelete) {
          img[p] = 0;
        }
      }
    }
  }

  return img;
}

function distanceTransformChamfer(mask, width, height) {
  const inf = 1e9;
  const dist = new Float32Array(mask.length);

  for (let i = 0; i < mask.length; i++) {
    dist[i] = mask[i] ? inf : 0;
  }

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const p = index(width, y, x);
      let d = dist[p];

      if (x > 0) d = Math.min(d, dist[index(width, y, x - 1)] + 1);
      if (y > 0) d = Math.min(d, dist[index(width, y - 1, x)] + 1);
      if (x > 0 && y > 0) d = Math.min(d, dist[index(width, y - 1, x - 1)] + Math.SQRT2);
      if (x < width - 1 && y > 0) d = Math.min(d, dist[index(width, y - 1, x + 1)] + Math.SQRT2);

      dist[p] = d;
    }
  }

  for (let y = height - 1; y >= 0; y--) {
    for (let x = width - 1; x >= 0; x--) {
      const p = index(width, y, x);
      let d = dist[p];

      if (x < width - 1) d = Math.min(d, dist[index(width, y, x + 1)] + 1);
      if (y < height - 1) d = Math.min(d, dist[index(width, y + 1, x)] + 1);
      if (x < width - 1 && y < height - 1) d = Math.min(d, dist[index(width, y + 1, x + 1)] + Math.SQRT2);
      if (x > 0 && y < height - 1) d = Math.min(d, dist[index(width, y + 1, x - 1)] + Math.SQRT2);

      dist[p] = d;
    }
  }

  return dist;
}

function skeletonDegree(skeleton, width, height, y, x) {
  let count = 0;

  for (const [dy, dx] of NEIGHBORS_8) {
    const yy = y + dy;
    const xx = x + dx;

    if (inBounds(width, height, yy, xx) && skeleton[index(width, yy, xx)]) {
      count++;
    }
  }

  return count;
}

function edgeKey(a, b) {
  return a < b ? `${a}:${b}` : `${b}:${a}`;
}

function skeletonNeighbors(skeleton, width, height, p) {
  const y = Math.floor(p / width);
  const x = p % width;
  const out = [];

  for (const [dy, dx] of NEIGHBORS_8) {
    const yy = y + dy;
    const xx = x + dx;

    if (inBounds(width, height, yy, xx)) {
      const q = index(width, yy, xx);

      if (skeleton[q]) {
        out.push(q);
      }
    }
  }

  return out;
}

function traceSkeletonPaths(skeleton, width, height) {
  const points = [];
  const nodes = new Set();

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const p = index(width, y, x);

      if (!skeleton[p]) continue;

      points.push(p);

      const deg = skeletonDegree(skeleton, width, height, y, x);

      if (deg !== 2) {
        nodes.add(p);
      }
    }
  }

  if (!points.length) return [];

  const visitedEdges = new Set();
  const paths = [];

  for (const node of nodes) {
    for (const neighbor of skeletonNeighbors(skeleton, width, height, node)) {
      const key = edgeKey(node, neighbor);

      if (visitedEdges.has(key)) continue;

      const traced = [node, neighbor];
      visitedEdges.add(key);

      let previous = node;
      let current = neighbor;

      while (!nodes.has(current)) {
        const nextPixels = skeletonNeighbors(skeleton, width, height, current)
          .filter((q) => q !== previous);

        if (!nextPixels.length) break;

        const next = nextPixels[0];

        visitedEdges.add(edgeKey(current, next));
        traced.push(next);

        previous = current;
        current = next;
      }

      paths.push(traced);
    }
  }

  const remainingEdges = [];

  for (const p of points) {
    for (const q of skeletonNeighbors(skeleton, width, height, p)) {
      if (!visitedEdges.has(edgeKey(p, q))) {
        remainingEdges.push([p, q]);
      }
    }
  }

  while (remainingEdges.length) {
    const [start, neighbor] = remainingEdges.pop();

    if (visitedEdges.has(edgeKey(start, neighbor))) continue;

    const traced = [start, neighbor];
    visitedEdges.add(edgeKey(start, neighbor));

    let previous = start;
    let current = neighbor;
    let guard = 0;

    while (current !== start && guard++ < 100000) {
      const nextPixels = skeletonNeighbors(skeleton, width, height, current)
        .filter((q) => q !== previous);

      if (!nextPixels.length) break;

      const next = nextPixels[0];

      if (visitedEdges.has(edgeKey(current, next)) && next !== start) break;

      visitedEdges.add(edgeKey(current, next));
      traced.push(next);

      previous = current;
      current = next;
    }

    if (traced.length > 2) {
      paths.push(traced);
    }
  }

  return paths;
}

function perpendicularDistance(point, start, end) {
  const [x, y] = point;
  const [x1, y1] = start;
  const [x2, y2] = end;

  const dx = x2 - x1;
  const dy = y2 - y1;

  if (dx === 0 && dy === 0) {
    return Math.hypot(x - x1, y - y1);
  }

  return Math.abs(dy * x - dx * y + x2 * y1 - y2 * x1) / Math.hypot(dx, dy);
}

function simplifyDouglasPeucker(points, epsilon) {
  if (points.length <= 2) return points;

  let maxDistance = -1;
  let split = -1;

  for (let i = 1; i < points.length - 1; i++) {
    const d = perpendicularDistance(points[i], points[0], points[points.length - 1]);

    if (d > maxDistance) {
      maxDistance = d;
      split = i;
    }
  }

  if (maxDistance <= epsilon) {
    return [points[0], points[points.length - 1]];
  }

  const left = simplifyDouglasPeucker(points.slice(0, split + 1), epsilon);
  const right = simplifyDouglasPeucker(points.slice(split), epsilon);

  return left.slice(0, -1).concat(right);
}

function simplifyPath(pixelPath, width, epsilon) {
  let points = pixelPath.map((p) => [p % width, Math.floor(p / width)]);

  const [x0, y0] = points[0];
  const [x1, y1] = points[points.length - 1];

  const closed = points.length > 3 && ((x0 - x1) ** 2 + (y0 - y1) ** 2 <= 4);

  points = simplifyDouglasPeucker(points, epsilon);

  if (closed) {
    points.push(points[0]);
  }

  return { points, closed };
}

function pathLength(points) {
  let total = 0;

  for (let i = 1; i < points.length; i++) {
    total += Math.hypot(
      points[i][0] - points[i - 1][0],
      points[i][1] - points[i - 1][1],
    );
  }

  return total;
}

function formatNumber(value) {
  return Number(value.toFixed(1)).toString();
}

function svgPathD(points, closed) {
  if (!points.length) return '';

  const parts = [`M ${formatNumber(points[0][0])} ${formatNumber(points[0][1])}`];

  for (const [x, y] of points.slice(1)) {
    parts.push(`L ${formatNumber(x)} ${formatNumber(y)}`);
  }

  if (closed) {
    parts.push('Z');
  }

  return parts.join(' ');
}

function median(values) {
  if (!values.length) return 0;

  values.sort((a, b) => a - b);

  const mid = Math.floor(values.length / 2);

  return values.length % 2
    ? values[mid]
    : (values[mid - 1] + values[mid]) / 2;
}

async function convertSvg(inputSvg, outputSvg, options) {
  const svgText = await fs.readFile(inputSvg, 'utf8');
  const viewBox = readViewBox(svgText);
  const colors = extractFillColors(svgText);
  const palette = colors.map(hexToRgb);

  const png = await renderSvgToRgba(inputSvg, viewBox.width, viewBox.height);
  const pixelCount = png.width * png.height;

  const nearestColorIndex = new Int16Array(pixelCount);
  nearestColorIndex.fill(-1);

  for (let p = 0; p < pixelCount; p++) {
    const offset = p * 4;
    const alpha = png.data[offset + 3];

    if (alpha <= options.alphaThreshold) continue;

    const r = png.data[offset];
    const g = png.data[offset + 1];
    const b = png.data[offset + 2];

    let bestIndex = 0;
    let bestDistance = Number.POSITIVE_INFINITY;

    for (let i = 0; i < palette.length; i++) {
      const [pr, pg, pb] = palette[i];
      const d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2;

      if (d < bestDistance) {
        bestDistance = d;
        bestIndex = i;
      }
    }

    nearestColorIndex[p] = bestIndex;
  }

  const outputPaths = [];

  for (let colorIndex = 0; colorIndex < colors.length; colorIndex++) {
    let colorMask = new Uint8Array(pixelCount);

    for (let p = 0; p < pixelCount; p++) {
      colorMask[p] = nearestColorIndex[p] === colorIndex ? 1 : 0;
    }

    colorMask = closing(colorMask, png.width, png.height);
    colorMask = removeSmallObjects(colorMask, png.width, png.height, options.minObjectSize);

    const skeleton = skeletonizeZhangSuen(colorMask, png.width, png.height);
    const distance = distanceTransformChamfer(colorMask, png.width, png.height);

    const skeletonDistances = [];

    for (let p = 0; p < pixelCount; p++) {
      if (skeleton[p]) {
        skeletonDistances.push(distance[p]);
      }
    }

    let strokeWidth = median(skeletonDistances) * 2 || 8;
    strokeWidth = Math.max(options.minStrokeWidth, Math.min(options.maxStrokeWidth, strokeWidth));

    for (const pixelPath of traceSkeletonPaths(skeleton, png.width, png.height)) {
      if (pixelPath.length < 8) continue;

      const { points, closed } = simplifyPath(pixelPath, png.width, options.simplifyEpsilon);

      if (points.length < 2 || pathLength(points) < options.minPathLength) continue;

      outputPaths.push({
        color: colors[colorIndex],
        strokeWidth,
        d: svgPathD(points, closed),
      });
    }
  }

  const lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    `<svg xmlns="${SVG_NS}" version="1.1" viewBox="${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}">`,
    '  <g fill="none" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke">',
  ];

  for (const p of outputPaths) {
    lines.push(`    <path d="${p.d}" stroke="${p.color}" stroke-width="${p.strokeWidth.toFixed(1)}"/>`);
  }

  lines.push('  </g>', '</svg>');

  await fs.writeFile(outputSvg, lines.join('\n'), 'utf8');
}

try {
  const args = parseArgs(process.argv);

  const inputSvg = path.resolve(args.input);
  const outputSvg = path.resolve(
    args.output ?? path.join(
      path.dirname(inputSvg),
      `${path.basename(inputSvg, path.extname(inputSvg))}-lines.svg`,
    ),
  );

  await convertSvg(inputSvg, outputSvg, args);

  console.log(`Wrote ${outputSvg}`);
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
}
