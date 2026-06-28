#!/usr/bin/env node
/**
 * Convert a filled-shape SVG line drawing into a stroked-line SVG.
 *
 * Install dependencies:
 *   npm install sharp pngjs
 *
 * Usage:
 *   # Inputs live in inputs/, outputs are written to outputs/.
 *   node convert-filled-svg-to-stroked-lines.mjs inputs/landscape.svg
 *   #   -> writes outputs/landscape.svg
 *
 *   # Or set the output path explicitly:
 *   node convert-filled-svg-to-stroked-lines.mjs inputs/landscape.svg \
 *     --output outputs/landscape.svg
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
    maxStrokeWidth: 30,
    joinGap: 3,
    joinAlignment: 0.15,
    minPathPixels: 2,
    mode: 'elements',
    scale: 1,
    pruneSpurs: 0,
    traceMode: 'continuous',
    capMode: 'round',
    openIterations: 0,
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
    else if (token === '--join-gap') args.joinGap = Number(next());
    else if (token === '--join-alignment') args.joinAlignment = Number(next());
    else if (token === '--min-path-pixels') args.minPathPixels = Number(next());
    else if (token === '--mode') args.mode = next();
    else if (token === '--scale') args.scale = Number(next());
    else if (token === '--prune-spurs') args.pruneSpurs = Number(next());
    else if (token === '--trace-mode') args.traceMode = next();
    else if (token === '--cap-mode') args.capMode = next();
    else if (token === '--open-iterations') args.openIterations = Number(next());
    else if (!args.input) args.input = token;
    else throw new Error(`Unexpected argument: ${token}`);
  }

  if (!args.input) {
    throw new Error('Usage: node convert-filled-svg-to-stroked-lines.mjs inputs/landscape.svg --output outputs/landscape.svg');
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

function attrValue(attrs, name) {
  const match = attrs.match(new RegExp(`\\b${name}\\s*=\\s*["']([^"']+)["']`, 'i'));
  return match ? match[1] : null;
}

function explicitFill(attrs) {
  const direct = attrValue(attrs, 'fill');

  if (direct && /^#[0-9a-fA-F]{6}$/.test(direct)) {
    return direct.toUpperCase();
  }

  const style = attrValue(attrs, 'style');
  const styled = style?.match(/(?:^|;)\s*fill\s*:\s*(#[0-9a-fA-F]{6})/i);

  return styled ? styled[1].toUpperCase() : null;
}

function sanitizeShapeAttrs(attrs) {
  return attrs
    .replace(/\s(?:fill|stroke|stroke-width|stroke-linecap|stroke-linejoin|vector-effect)\s*=\s*["'][^"']*["']/gi, '')
    .replace(/\sstyle\s*=\s*["'][^"']*["']/gi, '')
    .replace(/\/\s*$/, '')
    .trim();
}

function parseFilledElements(svgText) {
  const elements = [];
  const fillStack = [null];
  const regex = /<g\b([^>]*)>|<\/g>|<(path|rect|circle|ellipse)\b([^>]*)\/?>/gi;

  for (const match of svgText.matchAll(regex)) {
    if (match[0].startsWith('</g')) {
      if (fillStack.length > 1) fillStack.pop();
      continue;
    }

    if (match[0].startsWith('<g')) {
      const attrs = match[1];
      const fillAttr = attrValue(attrs, 'fill');
      const fill = fillAttr?.toLowerCase() === 'none'
        ? null
        : explicitFill(attrs) ?? fillStack[fillStack.length - 1];

      fillStack.push(fill);
      continue;
    }

    const tag = match[2].toLowerCase();
    const attrs = match[3];
    const fillAttr = attrValue(attrs, 'fill');
    const fill = fillAttr?.toLowerCase() === 'none'
      ? null
      : explicitFill(attrs) ?? fillStack[fillStack.length - 1];

    if (!fill) continue;

    const cleanAttrs = sanitizeShapeAttrs(attrs);
    elements.push({
      tag,
      fill,
      markup: `<${tag} ${cleanAttrs} fill="#fff"/>`,
      attrs,
    });
  }

  return elements;
}

async function renderElementMask(element, viewBox, scale) {
  const width = Math.round(viewBox.width * scale);
  const height = Math.round(viewBox.height * scale);
  const svg = [
    `<svg xmlns="${SVG_NS}" version="1.1" viewBox="${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}">`,
    `<rect x="${viewBox.x}" y="${viewBox.y}" width="${viewBox.width}" height="${viewBox.height}" fill="#000"/>`,
    element.markup,
    '</svg>',
  ].join('');
  const png = await renderSvgTextToRgba(svg, width, height);
  const mask = new Uint8Array(png.width * png.height);
  let area = 0;

  for (let p = 0; p < mask.length; p++) {
    const offset = p * 4;
    const value = png.data[offset];

    if (value > 128) {
      mask[p] = 1;
      area++;
    }
  }

  return { mask, area };
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

async function renderSvgTextToRgba(svgText, width, height) {
  const pngBuffer = await sharp(Buffer.from(svgText))
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

function opening(mask, width, height) {
  return dilate(erode(mask, width, height), width, height);
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

function traceSkeletonContinuous(skeleton, width, height) {
  const points = [];
  const degree = new Uint8Array(skeleton.length);

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const p = index(width, y, x);

      if (!skeleton[p]) continue;

      points.push(p);
      degree[p] = skeletonNeighbors(skeleton, width, height, p).length;
    }
  }

  const visitedEdges = new Set();
  const paths = [];
  const sortedPoints = [...points].sort((a, b) => degree[a] - degree[b]);

  const peekDirection = (previous, current) => {
    let a = previous;
    let b = current;
    const startX = b % width;
    const startY = Math.floor(b / width);

    for (let step = 0; step < 6; step++) {
      const ax = a % width;
      const ay = Math.floor(a / width);
      const bx = b % width;
      const by = Math.floor(b / width);
      const inX = bx - ax;
      const inY = by - ay;
      let best = null;
      let bestDot = -Infinity;

      for (const q of skeletonNeighbors(skeleton, width, height, b)) {
        if (q === a) continue;

        const qx = q % width;
        const qy = Math.floor(q / width);
        const outX = qx - bx;
        const outY = qy - by;
        const dot = (inX * outX + inY * outY) /
          ((Math.hypot(inX, inY) * Math.hypot(outX, outY)) || 1);

        if (dot > bestDot) {
          bestDot = dot;
          best = q;
        }
      }

      if (best === null) break;

      a = b;
      b = best;
    }

    return [b % width - startX, Math.floor(b / width) - startY];
  };

  const walk = (start) => {
    const path = [start];
    let current = start;

    while (true) {
      const candidates = skeletonNeighbors(skeleton, width, height, current)
        .filter((q) => !visitedEdges.has(edgeKey(current, q)));

      if (!candidates.length) break;

      let next = candidates[0];

      if (path.length >= 2 && candidates.length > 1) {
        const back = path[Math.max(0, path.length - 7)];
        const hx = current % width - back % width;
        const hy = Math.floor(current / width) - Math.floor(back / width);
        const hn = Math.hypot(hx, hy) || 1;
        let bestDot = -Infinity;

        for (const candidate of candidates) {
          const [dx, dy] = peekDirection(current, candidate);
          const dn = Math.hypot(dx, dy) || 1;
          const dot = (hx * dx + hy * dy) / (hn * dn);

          if (dot > bestDot) {
            bestDot = dot;
            next = candidate;
          }
        }
      }

      visitedEdges.add(edgeKey(current, next));
      current = next;
      path.push(current);
    }

    return path;
  };

  for (const p of sortedPoints) {
    let progressed = true;

    while (progressed) {
      progressed = false;

      for (const q of skeletonNeighbors(skeleton, width, height, p)) {
        if (!visitedEdges.has(edgeKey(p, q))) {
          const path = walk(p);

          if (path.length > 1) {
            paths.push(path);
          }

          progressed = true;
          break;
        }
      }
    }
  }

  return paths;
}

function pruneSkeletonSpurs(skeleton, width, height, maxLength) {
  if (maxLength <= 0) return skeleton;

  const out = new Uint8Array(skeleton);
  const removed = new Uint8Array(skeleton.length);

  const degreeAt = (p) => {
    if (!out[p]) return 0;
    return skeletonNeighbors(out, width, height, p).length;
  };

  let changed = true;

  while (changed) {
    changed = false;

    for (let p = 0; p < out.length; p++) {
      if (!out[p] || removed[p] || degreeAt(p) !== 1) continue;

      const branch = [p];
      let previous = -1;
      let current = p;
      let length = 0;
      let removable = false;

      while (branch.length <= maxLength) {
        const neighbors = skeletonNeighbors(out, width, height, current)
          .filter((q) => q !== previous);

        if (!neighbors.length) break;

        if (neighbors.length > 1) {
          removable = true;
          break;
        }

        const next = neighbors[0];
        const cx = current % width;
        const cy = Math.floor(current / width);
        const nx = next % width;
        const ny = Math.floor(next / width);

        length += Math.hypot(nx - cx, ny - cy);
        previous = current;
        current = next;

        const degree = degreeAt(current);

        if (degree > 2) {
          removable = true;
          break;
        }

        if (degree <= 1 || length > maxLength) break;

        branch.push(current);
      }

      if (removable && length <= maxLength) {
        for (const q of branch) {
          out[q] = 0;
          removed[q] = 1;
        }

        changed = true;
      }
    }
  }

  return out;
}

function activeNeighbors(active, width, height, p) {
  const y = Math.floor(p / width);
  const x = p % width;
  const out = [];

  for (const [dy, dx] of NEIGHBORS_8) {
    const yy = y + dy;
    const xx = x + dx;

    if (!inBounds(width, height, yy, xx)) continue;

    const q = index(width, yy, xx);

    if (active.has(q)) out.push(q);
  }

  return out;
}

function connectedComponentsFromActive(active, width, height) {
  const seen = new Set();
  const components = [];

  for (const start of active) {
    if (seen.has(start)) continue;

    const component = [];
    const queue = [start];
    seen.add(start);

    for (let qi = 0; qi < queue.length; qi++) {
      const p = queue[qi];
      component.push(p);

      for (const q of activeNeighbors(active, width, height, p)) {
        if (seen.has(q)) continue;

        seen.add(q);
        queue.push(q);
      }
    }

    components.push(component);
  }

  return components;
}

function farthestEndpointPath(active, width, height, start, endpoints) {
  const endpointSet = new Set(endpoints);
  const queue = [start];
  const previous = new Map([[start, -1]]);
  const distance = new Map([[start, 0]]);
  let farthest = start;
  let farthestDistance = 0;

  for (let qi = 0; qi < queue.length; qi++) {
    const p = queue[qi];
    const d = distance.get(p);

    if (p !== start && endpointSet.has(p) && d > farthestDistance) {
      farthest = p;
      farthestDistance = d;
    }

    for (const q of activeNeighbors(active, width, height, p)) {
      if (previous.has(q)) continue;

      previous.set(q, p);
      distance.set(q, d + joinPointDistance([p % width, Math.floor(p / width)], [q % width, Math.floor(q / width)]));
      queue.push(q);
    }
  }

  if (farthest === start) return null;

  const path = [];
  let current = farthest;

  while (current !== -1) {
    path.push(current);
    current = previous.get(current);
  }

  path.reverse();

  return { path, distance: farthestDistance };
}

function traceSkeletonLongestPaths(skeleton, width, height) {
  const active = new Set();

  for (let p = 0; p < skeleton.length; p++) {
    if (skeleton[p]) active.add(p);
  }

  const paths = [];

  while (active.size) {
    let progressed = false;

    for (const component of connectedComponentsFromActive(active, width, height)) {
      const endpoints = component.filter((p) => activeNeighbors(active, width, height, p).length <= 1);

      if (endpoints.length < 2) continue;

      let best = null;

      for (const endpointPixel of endpoints) {
        const candidate = farthestEndpointPath(active, width, height, endpointPixel, endpoints);

        if (candidate && (!best || candidate.distance > best.distance)) {
          best = candidate;
        }
      }

      if (!best) continue;

      paths.push(best.path);

      for (const p of best.path) {
        active.delete(p);
      }

      progressed = true;
    }

    if (!progressed) break;
  }

  if (active.size) {
    const remaining = new Uint8Array(skeleton.length);

    for (const p of active) remaining[p] = 1;

    paths.push(...traceSkeletonContinuous(remaining, width, height));
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

function simplifyPath(pixelPath, width, epsilon, scale = 1, viewBox = { x: 0, y: 0 }) {
  let points = pixelPath.map((p) => [
    viewBox.x + (p % width) / scale,
    viewBox.y + Math.floor(p / width) / scale,
  ]);

  const [x0, y0] = points[0];
  const [x1, y1] = points[points.length - 1];

  const closed = points.length > 3 && ((x0 - x1) ** 2 + (y0 - y1) ** 2 <= 4 / scale);

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

function endpointDirection(points, atEnd) {
  if (points.length < 2) return [0, 0];

  const a = atEnd ? points[points.length - 2] : points[1];
  const b = atEnd ? points[points.length - 1] : points[0];
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const length = Math.hypot(dx, dy) || 1;

  return [dx / length, dy / length];
}

function endpoint(points, atEnd) {
  return atEnd ? points[points.length - 1] : points[0];
}

function reversePath(path) {
  return {
    ...path,
    points: [...path.points].reverse(),
    startPixel: path.endPixel,
    endPixel: path.startPixel,
  };
}

function joinPointDistance(a, b) {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

function joinCandidate(a, b, maxGap, minAlignment) {
  const cases = [
    { aEnd: true, bEnd: false, reverseA: false, reverseB: false },
    { aEnd: true, bEnd: true, reverseA: false, reverseB: true },
    { aEnd: false, bEnd: false, reverseA: true, reverseB: false },
    { aEnd: false, bEnd: true, reverseA: true, reverseB: true },
  ];

  let best = null;

  for (const c of cases) {
    const pa = endpoint(a.points, c.aEnd);
    const pb = endpoint(b.points, c.bEnd);
    const gap = joinPointDistance(pa, pb);

    if (gap > maxGap) continue;

    const da = endpointDirection(a.points, c.aEnd);
    const db = endpointDirection(b.points, !c.bEnd);
    const alignment = da[0] * db[0] + da[1] * db[1];

    // Tiny gaps usually come from a skeleton junction pixel and should be
    // reconnected even when the local direction changes sharply.
    if (gap > 3 && alignment < minAlignment) continue;

    const score = gap + (1 - alignment) * 8;

    if (!best || score < best.score) {
      best = { ...c, gap, score };
    }
  }

  return best;
}

function mergeTwoPaths(a, b, candidate) {
  const left = candidate.reverseA ? reversePath(a) : a;
  const right = candidate.reverseB ? reversePath(b) : b;
  const [lx, ly] = left.points[left.points.length - 1];
  const [rx, ry] = right.points[0];
  const skipRightStart = lx === rx && ly === ry;

  return {
    ...left,
    points: left.points.concat(skipRightStart ? right.points.slice(1) : right.points),
    closed: false,
    startPixel: left.startPixel,
    endPixel: right.endPixel,
  };
}

function mergeOpenPaths(paths, maxGap, minAlignment) {
  const open = paths.filter((p) => !p.closed);
  const closed = paths.filter((p) => p.closed);

  let changed = true;

  while (changed) {
    changed = false;
    let best = null;

    for (let i = 0; i < open.length; i++) {
      for (let j = i + 1; j < open.length; j++) {
        const candidate = joinCandidate(open[i], open[j], maxGap, minAlignment);

        if (!candidate) continue;

        if (!best || candidate.score < best.candidate.score) {
          best = { i, j, candidate };
        }
      }
    }

    if (best) {
      const merged = mergeTwoPaths(open[best.i], open[best.j], best.candidate);
      open.splice(best.j, 1);
      open.splice(best.i, 1, merged);
      changed = true;
    }
  }

  return closed.concat(open);
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

function ellipseLikeStroke(element, options) {
  if (element.tag !== 'ellipse' && element.tag !== 'circle') return null;

  const transform = attrValue(element.attrs, 'transform') ?? '';
  const translate = transform.match(/translate\(([-\d.]+)[,\s]+([-\d.]+)\)/i);
  const cx = element.tag === 'circle'
    ? Number(attrValue(element.attrs, 'cx'))
    : translate
      ? Number(translate[1])
      : Number(attrValue(element.attrs, 'cx'));
  const cy = element.tag === 'circle'
    ? Number(attrValue(element.attrs, 'cy'))
    : translate
      ? Number(translate[2])
      : Number(attrValue(element.attrs, 'cy'));
  const rx = element.tag === 'circle'
    ? Number(attrValue(element.attrs, 'r'))
    : Number(attrValue(element.attrs, 'rx'));
  const ry = element.tag === 'circle'
    ? rx
    : Number(attrValue(element.attrs, 'ry'));

  if ([cx, cy, rx, ry].some(Number.isNaN)) return null;

  const diameter = Math.min(rx, ry);
  const strokeWidth = Math.max(
    options.minStrokeWidth,
    Math.min(options.maxStrokeWidth, diameter * 0.65),
  );
  const radius = Math.max(2, diameter * 0.4);

  return {
    color: element.fill,
    strokeWidth,
    circle: { cx, cy, r: radius },
  };
}

async function convertSvgByElements(inputSvg, outputSvg, options) {
  const svgText = await fs.readFile(inputSvg, 'utf8');
  const viewBox = readViewBox(svgText);
  const elements = parseFilledElements(svgText);
  const scale = Math.max(1, options.scale || 1);
  const outputPaths = [];

  for (const element of elements) {
    const dotStroke = ellipseLikeStroke(element, options);

    if (dotStroke) {
      outputPaths.push(dotStroke);
      continue;
    }

    const { mask, area } = await renderElementMask(element, viewBox, scale);
    const maskWidth = Math.round(viewBox.width * scale);
    const maskHeight = Math.round(viewBox.height * scale);

    if (area < options.minObjectSize) continue;

    let cleaned = removeSmallObjects(mask, maskWidth, maskHeight, options.minObjectSize);

    for (let i = 0; i < options.openIterations; i++) {
      cleaned = opening(cleaned, maskWidth, maskHeight);
    }

    let skeleton = skeletonizeZhangSuen(cleaned, maskWidth, maskHeight);
    skeleton = pruneSkeletonSpurs(skeleton, maskWidth, maskHeight, options.pruneSpurs * scale);
    const distance = distanceTransformChamfer(cleaned, maskWidth, maskHeight);
    const skeletonDistances = [];
    const trueEndpoints = new Set();

    for (let p = 0; p < skeleton.length; p++) {
      if (skeleton[p]) {
        skeletonDistances.push(distance[p]);

        if (skeletonNeighbors(skeleton, maskWidth, maskHeight, p).length <= 1) {
          trueEndpoints.add(p);
        }
      }
    }

    let strokeWidth = (median(skeletonDistances) * 2 || 8) / scale;
    strokeWidth = Math.max(options.minStrokeWidth, Math.min(options.maxStrokeWidth, strokeWidth));

    const colorPaths = [];

    const tracedPaths = options.traceMode === 'longest'
      ? traceSkeletonLongestPaths(skeleton, maskWidth, maskHeight)
      : traceSkeletonContinuous(skeleton, maskWidth, maskHeight);

    for (const pixelPath of tracedPaths) {
      if (pixelPath.length < options.minPathPixels) continue;

      const { points, closed } = simplifyPath(pixelPath, maskWidth, options.simplifyEpsilon, scale, viewBox);

      if (points.length < 2 || pathLength(points) < options.minPathLength) continue;

      colorPaths.push({
        points,
        closed,
        startPixel: pixelPath[0],
        endPixel: pixelPath[pixelPath.length - 1],
      });
    }

    for (const path of mergeOpenPaths(colorPaths, options.joinGap, options.joinAlignment)) {
      if (path.points.length < 2 || pathLength(path.points) < options.minPathLength) continue;

      outputPaths.push({
        color: element.fill,
        strokeWidth,
        linecap: options.capMode === 'endpoint' ? 'butt' : 'round',
        caps: options.capMode === 'endpoint'
          ? [path.startPixel, path.endPixel]
            .filter((p) => trueEndpoints.has(p))
            .map((p) => [
              viewBox.x + (p % maskWidth) / scale,
              viewBox.y + Math.floor(p / maskWidth) / scale,
            ])
          : [],
        d: svgPathD(path.points, path.closed),
      });
    }
  }

  await writeOutputSvg(outputSvg, viewBox, outputPaths);
}

async function writeOutputSvg(outputSvg, viewBox, outputPaths) {
  const lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    `<svg xmlns="${SVG_NS}" version="1.1" viewBox="${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}">`,
    '  <g fill="none" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke">',
  ];

  for (const p of outputPaths) {
    if (p.circle) {
      lines.push(`    <circle cx="${formatNumber(p.circle.cx)}" cy="${formatNumber(p.circle.cy)}" r="${formatNumber(p.circle.r)}" stroke="${p.color}" stroke-width="${p.strokeWidth.toFixed(1)}"/>`);
    } else {
      const linecap = p.linecap && p.linecap !== 'round' ? ` stroke-linecap="${p.linecap}"` : '';
      lines.push(`    <path d="${p.d}" stroke="${p.color}" stroke-width="${p.strokeWidth.toFixed(1)}"${linecap}/>`);

      for (const [x, y] of p.caps ?? []) {
        lines.push(`    <path d="M ${formatNumber(x)} ${formatNumber(y)} L ${formatNumber(x + 0.01)} ${formatNumber(y)}" stroke="${p.color}" stroke-width="${p.strokeWidth.toFixed(1)}" stroke-linecap="round"/>`);
      }
    }
  }

  lines.push('  </g>', '</svg>');

  await fs.writeFile(outputSvg, lines.join('\n'), 'utf8');
}

async function convertSvg(inputSvg, outputSvg, options) {
  if (options.mode === 'elements') {
    await convertSvgByElements(inputSvg, outputSvg, options);
    return;
  }

  if (options.mode !== 'colors') {
    throw new Error(`Unsupported --mode ${options.mode}. Use "elements" or "colors".`);
  }

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

    const colorPaths = [];

    for (const pixelPath of traceSkeletonPaths(skeleton, png.width, png.height)) {
      if (pixelPath.length < options.minPathPixels) continue;

      const { points, closed } = simplifyPath(pixelPath, png.width, options.simplifyEpsilon);

      if (points.length < 2 || pathLength(points) < options.minPathLength) continue;

      colorPaths.push({ points, closed });
    }

    for (const path of mergeOpenPaths(colorPaths, options.joinGap, options.joinAlignment)) {
      if (path.points.length < 2 || pathLength(path.points) < options.minPathLength) continue;

      outputPaths.push({
        color: colors[colorIndex],
        strokeWidth,
        d: svgPathD(path.points, path.closed),
      });
    }
  }

  await writeOutputSvg(outputSvg, viewBox, outputPaths);
}

// Pick a default output path: if the input lives in an `inputs/` folder,
// mirror it into a sibling `outputs/` folder with the same filename;
// otherwise fall back to a `-lines.svg` sibling of the input.
function deriveOutputPath(inputSvg) {
  const dir = path.dirname(inputSvg);

  if (path.basename(dir) === 'inputs') {
    return path.join(path.dirname(dir), 'outputs', path.basename(inputSvg));
  }

  return path.join(
    dir,
    `${path.basename(inputSvg, path.extname(inputSvg))}-lines.svg`,
  );
}

try {
  const args = parseArgs(process.argv);

  const inputSvg = path.resolve(args.input);
  const outputSvg = path.resolve(args.output ?? deriveOutputPath(inputSvg));

  await fs.mkdir(path.dirname(outputSvg), { recursive: true });

  await convertSvg(inputSvg, outputSvg, args);

  console.log(`Wrote ${outputSvg}`);
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
}
