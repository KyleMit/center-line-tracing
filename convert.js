#!/usr/bin/env node
// Convert an SVG whose "lines" are drawn as filled outline shapes into
// real <path> elements with a stroke + stroke-width (fill="none").
//
// Strategy (raster medial-axis):
//   1. parse each <path> (fill color + d)
//   2. rasterize that single path to a binary mask via sharp/librsvg
//   3. thin the mask to a 1px skeleton (Zhang-Suen)
//   4. estimate stroke width from filled-area / skeleton-length
//   5. trace skeleton pixels into ordered polylines (split at junctions)
//   6. simplify polylines (Ramer-Douglas-Peucker via simplify-js)
//   7. emit <path fill="none" stroke=color stroke-width=w d=...>
//
// Usage: node convert.js [inputs/landscape.svg] [outputs/landscape.svg]

const fs = require('fs');
const path = require('path');
const sharp = require('sharp');
const simplify = require('simplify-js');

const INPUT = process.argv[2] || 'inputs/landscape.svg';
const OUTPUT = process.argv[3] || 'outputs/landscape.svg';

// Rendering resolution for the mask. Higher = better skeleton, slower.
const SCALE = Number(process.env.SCALE || 1.0);
// RDP simplification tolerance, in *svg user units*.
const SIMPLIFY_TOL = Number(process.env.SIMPLIFY_TOL || 2.0);
// Drop traced polylines shorter than this (svg units) - removes speckle.
const MIN_SEG_LEN = Number(process.env.MIN_SEG_LEN || 4);

function parseSvg(svg) {
  const vbMatch = svg.match(/viewBox\s*=\s*"([^"]+)"/i);
  let vb = [0, 0, 1773, 1773];
  if (vbMatch) vb = vbMatch[1].trim().split(/[\s,]+/).map(Number);

  // Walk <g>/<path> in document order, tracking inherited fill from groups.
  const paths = [];
  const fillStack = ['#000000']; // SVG default fill is black
  const re = /<g\b([^>]*)>|<\/g>|<path\b([^>]*?)\/?>/gis;
  let m;
  while ((m = re.exec(svg)) !== null) {
    if (m[0].startsWith('</g')) {
      if (fillStack.length > 1) fillStack.pop();
    } else if (m[0].startsWith('<g')) {
      const gf = (m[1].match(/fill\s*=\s*"([^"]*)"/i) || [])[1];
      fillStack.push(gf || fillStack[fillStack.length - 1]);
    } else {
      const attrs = m[2];
      const d = (attrs.match(/\bd\s*=\s*"([^"]*)"/i) || [])[1];
      if (!d) continue;
      const fill = (attrs.match(/fill\s*=\s*"([^"]*)"/i) || [])[1]
        || fillStack[fillStack.length - 1];
      paths.push({ fill, d: d.replace(/\s+/g, ' ').trim() });
    }
  }
  return { vb, paths };
}

// Rasterize one path's fill to a Uint8 binary mask (1 = inside).
async function rasterizePath(d, vb, W, H) {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vb.join(' ')}" ` +
    `width="${W}" height="${H}">` +
    `<rect x="${vb[0]}" y="${vb[1]}" width="${vb[2]}" height="${vb[3]}" fill="#000"/>` +
    `<path fill="#fff" fill-rule="evenodd" d="${d}"/></svg>`;
  const { data } = await sharp(Buffer.from(svg))
    .resize(W, H, { fit: 'fill' })
    .grayscale()
    .raw()
    .toBuffer({ resolveWithObject: true });
  const mask = new Uint8Array(W * H);
  let area = 0;
  for (let i = 0; i < W * H; i++) {
    if (data[i] > 128) { mask[i] = 1; area++; }
  }
  return { mask, area };
}

// Two-pass chamfer distance transform: distance (px) from each filled
// pixel to the nearest background pixel. Used to estimate stroke width
// robustly even where scribble strokes overlap/cross.
function distanceTransform(mask, W, H) {
  const INF = 1e9;
  const dt = new Float32Array(W * H);
  const O = 1, D = Math.SQRT2;
  for (let i = 0; i < W * H; i++) dt[i] = mask[i] ? INF : 0;
  const at = (x, y) => y * W + x;
  // forward
  for (let y = 0; y < H; y++)
    for (let x = 0; x < W; x++) {
      const i = at(x, y);
      if (dt[i] === 0) continue;
      let v = dt[i];
      if (x > 0) v = Math.min(v, dt[at(x - 1, y)] + O);
      if (y > 0) v = Math.min(v, dt[at(x, y - 1)] + O);
      if (x > 0 && y > 0) v = Math.min(v, dt[at(x - 1, y - 1)] + D);
      if (x < W - 1 && y > 0) v = Math.min(v, dt[at(x + 1, y - 1)] + D);
      dt[i] = v;
    }
  // backward
  for (let y = H - 1; y >= 0; y--)
    for (let x = W - 1; x >= 0; x--) {
      const i = at(x, y);
      if (dt[i] === 0) continue;
      let v = dt[i];
      if (x < W - 1) v = Math.min(v, dt[at(x + 1, y)] + O);
      if (y < H - 1) v = Math.min(v, dt[at(x, y + 1)] + O);
      if (x < W - 1 && y < H - 1) v = Math.min(v, dt[at(x + 1, y + 1)] + D);
      if (x > 0 && y < H - 1) v = Math.min(v, dt[at(x - 1, y + 1)] + D);
      dt[i] = v;
    }
  return dt;
}

// Zhang-Suen thinning -> 1px skeleton (in place on a copy).
function thin(src, W, H) {
  const img = Uint8Array.from(src);
  const idx = (x, y) => y * W + x;
  let changed = true;
  const toClear = [];
  while (changed) {
    changed = false;
    for (let step = 0; step < 2; step++) {
      toClear.length = 0;
      for (let y = 1; y < H - 1; y++) {
        for (let x = 1; x < W - 1; x++) {
          if (!img[idx(x, y)]) continue;
          const p2 = img[idx(x, y - 1)], p3 = img[idx(x + 1, y - 1)],
                p4 = img[idx(x + 1, y)], p5 = img[idx(x + 1, y + 1)],
                p6 = img[idx(x, y + 1)], p7 = img[idx(x - 1, y + 1)],
                p8 = img[idx(x - 1, y)], p9 = img[idx(x - 1, y - 1)];
          const B = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9;
          if (B < 2 || B > 6) continue;
          const seq = [p2, p3, p4, p5, p6, p7, p8, p9, p2];
          let A = 0;
          for (let k = 0; k < 8; k++) if (seq[k] === 0 && seq[k + 1] === 1) A++;
          if (A !== 1) continue;
          if (step === 0) {
            if (p2 * p4 * p6 !== 0) continue;
            if (p4 * p6 * p8 !== 0) continue;
          } else {
            if (p2 * p4 * p8 !== 0) continue;
            if (p2 * p6 * p8 !== 0) continue;
          }
          toClear.push(idx(x, y));
        }
      }
      if (toClear.length) {
        changed = true;
        for (const i of toClear) img[i] = 0;
      }
    }
  }
  return img;
}

// Remove short dead-end spurs (barbs the thinning leaves at junctions).
// These false branches are what fracture a stroke into junctions; clearing
// them lets a self-crossing stroke trace through as one line. Real stroke
// tips are long, so they only lose `maxLen` px — invisible with round caps.
function pruneSpurs(skel, W, H, maxLen) {
  const idx = (x, y) => y * W + x;
  const degAt = (x, y) => {
    let n = 0;
    for (let dy = -1; dy <= 1; dy++)
      for (let dx = -1; dx <= 1; dx++) {
        if (dx === 0 && dy === 0) continue;
        const nx = x + dx, ny = y + dy;
        if (nx >= 0 && ny >= 0 && nx < W && ny < H && skel[idx(nx, ny)]) n++;
      }
    return n;
  };
  for (let pass = 0; pass < maxLen; pass++) {
    const drop = [];
    for (let y = 1; y < H - 1; y++)
      for (let x = 1; x < W - 1; x++)
        if (skel[idx(x, y)] && degAt(x, y) <= 1) drop.push(idx(x, y));
    if (!drop.length) break;
    for (const i of drop) skel[i] = 0;
  }
}

// Trace the skeleton into long polylines. Crucially, it does NOT stop at
// junctions: when a stroke crosses itself the medial axis branches, and we
// continue along whichever branch best preserves the current heading, so one
// continuous pen stroke comes back as one continuous line.
function traceSkeleton(skel, W, H) {
  const idx = (x, y) => y * W + x;
  const nbrs = (x, y) => {
    const out = [];
    for (let dy = -1; dy <= 1; dy++)
      for (let dx = -1; dx <= 1; dx++) {
        if (dx === 0 && dy === 0) continue;
        const nx = x + dx, ny = y + dy;
        if (nx >= 0 && ny >= 0 && nx < W && ny < H && skel[idx(nx, ny)])
          out.push([nx, ny]);
      }
    return out;
  };

  const deg = new Uint8Array(W * H);
  const pts = [];
  for (let y = 0; y < H; y++)
    for (let x = 0; x < W; x++)
      if (skel[idx(x, y)]) { deg[idx(x, y)] = nbrs(x, y).length; pts.push([x, y]); }

  const AHEAD = 6;  // px to peek down a branch to estimate its direction
  const BACK = 6;   // px of incoming history used as the heading
  // Direction of the branch leaving (bx,by) away from (ax,ay), peeking ahead
  // along the locally-straightest path so junction choices are robust.
  const peekDir = (ax, ay, bx, by) => {
    const sx0 = bx, sy0 = by;
    for (let s = 0; s < AHEAD; s++) {
      let best = null, bestDot = -Infinity;
      const v1x = bx - ax, v1y = by - ay;
      for (const [nx, ny] of nbrs(bx, by)) {
        if (nx === ax && ny === ay) continue;
        const v2x = nx - bx, v2y = ny - by;
        const d = (v1x * v2x + v1y * v2y) /
          ((Math.hypot(v1x, v1y) * Math.hypot(v2x, v2y)) || 1);
        if (d > bestDot) { bestDot = d; best = [nx, ny]; }
      }
      if (!best) break;
      ax = bx; ay = by; bx = best[0]; by = best[1];
    }
    return [bx - sx0, by - sy0];
  };

  const visited = new Set();
  const ekey = (a, b) => a < b ? a + ',' + b : b + ',' + a;
  const polylines = [];

  const walk = (sx, sy) => {
    const line = [[sx, sy]];
    let cx = sx, cy = sy;
    while (true) {
      const here = idx(cx, cy);
      const cand = nbrs(cx, cy).filter(
        ([nx, ny]) => !visited.has(ekey(here, idx(nx, ny)))
      );
      if (cand.length === 0) break;
      let next = cand[0];
      if (line.length >= 2 && cand.length > 1) {
        // heading over the last BACK pixels (smoother than 1-px direction)
        const j = Math.max(0, line.length - 1 - BACK);
        const hx = cx - line[j][0], hy = cy - line[j][1];
        const hn = Math.hypot(hx, hy) || 1;
        let best = -Infinity;
        for (const c of cand) {
          const [dx, dy] = peekDir(cx, cy, c[0], c[1]);
          const dn = Math.hypot(dx, dy) || 1;
          const dot = (hx * dx + hy * dy) / (hn * dn);
          if (dot > best) { best = dot; next = c; }
        }
      }
      visited.add(ekey(here, idx(next[0], next[1])));
      cx = next[0]; cy = next[1];
      line.push([cx, cy]);
    }
    return line;
  };

  // Start at true stroke ends (degree 1) so whole strokes trace in one go,
  // then mop up any remaining edges (closed loops / leftover crossings).
  const order = [...pts].sort((a, b) =>
    deg[idx(a[0], a[1])] - deg[idx(b[0], b[1])]);
  for (const [x, y] of order) {
    let progressed = true;
    while (progressed) {
      progressed = false;
      const here = idx(x, y);
      for (const [nx, ny] of nbrs(x, y)) {
        if (!visited.has(ekey(here, idx(nx, ny)))) {
          const line = walk(x, y);
          if (line.length > 1) polylines.push(line);
          progressed = true;
          break;
        }
      }
    }
  }
  return polylines;
}

// Estimate skeleton length in pixels (sum of step lengths).
function skelLength(polys) {
  let len = 0;
  for (const line of polys)
    for (let i = 1; i < line.length; i++) {
      const dx = line[i][0] - line[i - 1][0], dy = line[i][1] - line[i - 1][1];
      len += Math.hypot(dx, dy);
    }
  return len;
}

function fmt(n) { return Math.round(n * 100) / 100; }

async function main() {
  const svg = fs.readFileSync(INPUT, 'utf8');
  const { vb, paths } = parseSvg(svg);
  const W = Math.round(vb[2] * SCALE);
  const H = Math.round(vb[3] * SCALE);
  console.log(`viewBox ${vb.join(' ')}  render ${W}x${H}  paths ${paths.length}`);

  const sx = vb[2] / W, sy = vb[3] / H; // px -> user units
  const outPaths = [];

  for (let p = 0; p < paths.length; p++) {
    const { fill, d } = paths[p];
    const { mask, area } = await rasterizePath(d, vb, W, H);
    if (area === 0) { console.log(`  path ${p}: empty`); continue; }
    const dt = distanceTransform(mask, W, H);
    const skel = thin(mask, W, H);

    // Representative stroke width from the distance transform along the raw
    // skeleton (before pruning): 2 * ~median half-width.
    const dvals = [];
    for (let y = 0; y < H; y++)
      for (let x = 0; x < W; x++)
        if (skel[y * W + x]) dvals.push(dt[y * W + x]);
    dvals.sort((a, b) => a - b);
    const pct = (q) => dvals.length ? dvals[Math.min(dvals.length - 1,
      Math.floor(q * dvals.length))] : 0;
    const widthPx = 2 * pct(0.55);
    const strokeW = fmt(widthPx * ((sx + sy) / 2));

    // Prune barbs up to ~half the stroke width, then trace through junctions.
    pruneSpurs(skel, W, H, Math.max(2, Math.round(widthPx * 0.6)));
    let polys = traceSkeleton(skel, W, H);
    const len = skelLength(polys) || 1;

    // px -> user coords, simplify, drop tiny
    const segs = [];
    for (const line of polys) {
      const usr = line.map(([x, y]) => ({ x: vb[0] + x * sx, y: vb[1] + y * sy }));
      const s = simplify(usr, SIMPLIFY_TOL, true);
      let segLen = 0;
      for (let i = 1; i < s.length; i++)
        segLen += Math.hypot(s[i].x - s[i - 1].x, s[i].y - s[i - 1].y);
      if (s.length >= 2 && segLen >= MIN_SEG_LEN) segs.push(s);
    }
    if (!segs.length) { console.log(`  path ${p}: no segments`); continue; }

    const dStr = segs.map(s =>
      'M' + s.map(pt => `${fmt(pt.x)} ${fmt(pt.y)}`).join(' L')
    ).join(' ');

    outPaths.push(
      `<path fill="none" stroke="${fill}" stroke-width="${strokeW}" ` +
      `stroke-linecap="round" stroke-linejoin="round" d="${dStr}"/>`
    );
    console.log(`  path ${p} ${fill}: area=${area} len=${fmt(len)} ` +
      `w=${strokeW} segs=${segs.length}`);
  }

  const out =
    `<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n` +
    `<svg xmlns="http://www.w3.org/2000/svg" version="1.1" ` +
    `viewBox="${vb.join(' ')}">\n` + outPaths.join('\n') + `\n</svg>\n`;
  fs.mkdirSync(path.dirname(OUTPUT), { recursive: true });
  fs.writeFileSync(OUTPUT, out);
  console.log(`wrote ${OUTPUT} (${outPaths.length} paths, ${out.length} bytes)`);
}

main().catch(e => { console.error(e); process.exit(1); });
