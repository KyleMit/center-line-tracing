// Stage 1 (report §9.2): SVG normalization.
//
//   1. apply nested transforms to coordinates
//   2. convert primitive shapes to paths
//   3. resolve compound paths (split subpaths into closed loops)
//   4. ensure loops are closed
//   5. separate disconnected components (per element, per loop)
//   6. remove zero-area / degenerate segments
//   7. convert every arc + shorthand into line/quad/cubic Beziers
//
// Step 7 is NOT optional for this track: flo-boolean's `getPathsFromStr`
// silently turns an SVG `A` command into a straight LINE. Feeding it a
// round-capped capsule written with arcs therefore yields the MAT of a
// RECTANGLE. See debug/flo-mat/NOTES.md.

import SPC from 'svg-path-commander';
import { parseXml, findSvg } from './xml.mjs';

const { normalizePath, arcToCubic } = SPC;

/* ------------------------------------------------------------------ matrix */
// [a b c d e f] == | a c e |
//                  | b d f |
export const IDENT = [1, 0, 0, 1, 0, 0];

export function matMul(m1, m2) {
  return [
    m1[0] * m2[0] + m1[2] * m2[1],
    m1[1] * m2[0] + m1[3] * m2[1],
    m1[0] * m2[2] + m1[2] * m2[3],
    m1[1] * m2[2] + m1[3] * m2[3],
    m1[0] * m2[4] + m1[2] * m2[5] + m1[4],
    m1[1] * m2[4] + m1[3] * m2[5] + m1[5],
  ];
}

export function applyMat(m, x, y) {
  return [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
}

/** Uniform scale factor implied by a matrix (geometric mean of singular values). */
export function matScale(m) {
  return Math.sqrt(Math.abs(m[0] * m[3] - m[1] * m[2])) || 1;
}

const NUM = /[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?/g;

export function parseTransform(str) {
  let m = IDENT;
  if (!str) return m;
  const re = /(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)/g;
  let t;
  while ((t = re.exec(str))) {
    const nums = (t[2].match(NUM) || []).map(Number);
    let local = IDENT;
    switch (t[1]) {
      case 'matrix': local = nums.slice(0, 6); break;
      case 'translate': local = [1, 0, 0, 1, nums[0] || 0, nums[1] || 0]; break;
      case 'scale': local = [nums[0] ?? 1, 0, 0, nums[1] ?? nums[0] ?? 1, 0, 0]; break;
      case 'rotate': {
        const a = ((nums[0] || 0) * Math.PI) / 180;
        const c = Math.cos(a); const s = Math.sin(a);
        const rot = [c, s, -s, c, 0, 0];
        if (nums.length >= 3) {
          local = matMul(matMul([1, 0, 0, 1, nums[1], nums[2]], rot), [1, 0, 0, 1, -nums[1], -nums[2]]);
        } else local = rot;
        break;
      }
      case 'skewX': local = [1, 0, Math.tan(((nums[0] || 0) * Math.PI) / 180), 1, 0, 0]; break;
      case 'skewY': local = [1, Math.tan(((nums[0] || 0) * Math.PI) / 180), 0, 1, 0, 0]; break;
    }
    m = matMul(m, local);
  }
  return m;
}

/* ------------------------------------------------------------ shape -> path */
const n = (a, k, d = 0) => (a[k] === undefined ? d : parseFloat(a[k]) || 0);

/** Convert an SVG basic shape element into a path `d` string. */
export function shapeToPathD(tag, a) {
  switch (tag) {
    case 'path': return a.d || '';
    case 'rect': {
      const x = n(a, 'x'); const y = n(a, 'y');
      const w = n(a, 'width'); const h = n(a, 'height');
      if (w <= 0 || h <= 0) return '';
      let rx = a.rx !== undefined ? n(a, 'rx') : (a.ry !== undefined ? n(a, 'ry') : 0);
      let ry = a.ry !== undefined ? n(a, 'ry') : (a.rx !== undefined ? n(a, 'rx') : 0);
      rx = Math.min(rx, w / 2); ry = Math.min(ry, h / 2);
      if (rx <= 0 || ry <= 0) return `M${x} ${y}H${x + w}V${y + h}H${x}Z`;
      return `M${x + rx} ${y}H${x + w - rx}A${rx} ${ry} 0 0 1 ${x + w} ${y + ry}`
        + `V${y + h - ry}A${rx} ${ry} 0 0 1 ${x + w - rx} ${y + h}`
        + `H${x + rx}A${rx} ${ry} 0 0 1 ${x} ${y + h - ry}`
        + `V${y + ry}A${rx} ${ry} 0 0 1 ${x + rx} ${y}Z`;
    }
    case 'circle': {
      const cx = n(a, 'cx'); const cy = n(a, 'cy'); const r = n(a, 'r');
      if (r <= 0) return '';
      return `M${cx - r} ${cy}A${r} ${r} 0 0 1 ${cx + r} ${cy}A${r} ${r} 0 0 1 ${cx - r} ${cy}Z`;
    }
    case 'ellipse': {
      const cx = n(a, 'cx'); const cy = n(a, 'cy');
      const rx = n(a, 'rx'); const ry = n(a, 'ry');
      if (rx <= 0 || ry <= 0) return '';
      return `M${cx - rx} ${cy}A${rx} ${ry} 0 0 1 ${cx + rx} ${cy}A${rx} ${ry} 0 0 1 ${cx - rx} ${cy}Z`;
    }
    case 'line': {
      return `M${n(a, 'x1')} ${n(a, 'y1')}L${n(a, 'x2')} ${n(a, 'y2')}`;
    }
    case 'polyline':
    case 'polygon': {
      const pts = (a.points || '').match(NUM);
      if (!pts || pts.length < 4) return '';
      let d = `M${pts[0]} ${pts[1]}`;
      for (let i = 2; i + 1 < pts.length; i += 2) d += `L${pts[i]} ${pts[i + 1]}`;
      return tag === 'polygon' ? d + 'Z' : d;
    }
    default: return '';
  }
}

/* --------------------------------------------------------- path -> loops */

const DEGENERATE = 1e-9;

function dedupe(pts) {
  const out = [pts[0]];
  for (let i = 1; i < pts.length; i++) {
    const p = pts[i]; const q = out[out.length - 1];
    if (Math.abs(p[0] - q[0]) > DEGENERATE || Math.abs(p[1] - q[1]) > DEGENERATE) out.push(p);
  }
  return out;
}

/**
 * Convert an SVG path `d` into flo-mat bezier loops, in the coordinate space
 * defined by `mat`.
 *
 * Returns `{ loops, stats }` where each loop is an array of beziers and each
 * bezier is an array of 2 (line), 3 (quadratic) or 4 (cubic) `[x,y]` points.
 */
export function pathToLoops(d, mat = IDENT) {
  const segs = normalizePath(d); // absolute M/L/C/Q/A/Z
  const loops = [];
  const stats = { arcs: 0, subpaths: 0, dropped: 0, openClosed: 0 };

  let cur = null;      // current loop (array of beziers)
  let start = null;    // subpath start point (transformed)
  let pen = null;      // current point (transformed)

  const T = (x, y) => applyMat(mat, x, y);

  const push = (bez) => {
    const b = dedupe(bez);
    if (b.length < 2) { stats.dropped++; return; }
    cur.push(b);
  };

  const closeLoop = () => {
    if (!cur) return;
    if (pen && start && (Math.abs(pen[0] - start[0]) > DEGENERATE || Math.abs(pen[1] - start[1]) > DEGENERATE)) {
      cur.push([pen, start]);
      stats.openClosed++;
    }
    if (cur.length >= 2) loops.push(cur);
    else stats.dropped++;
    cur = null;
  };

  for (const s of segs) {
    const op = s[0];
    if (op === 'M') {
      closeLoop();
      start = T(s[1], s[2]); pen = start; cur = []; stats.subpaths++;
    } else if (!cur) {
      continue; // geometry before any M
    } else if (op === 'L') {
      const p = T(s[1], s[2]); push([pen, p]); pen = p;
    } else if (op === 'Q') {
      const c = T(s[1], s[2]); const p = T(s[3], s[4]);
      push([pen, c, p]); pen = p;
    } else if (op === 'C') {
      const c1 = T(s[1], s[2]); const c2 = T(s[3], s[4]); const p = T(s[5], s[6]);
      push([pen, c1, c2, p]); pen = p;
    } else if (op === 'A') {
      // untransformed current point is needed by arcToCubic
      const prev = untransform(mat, pen);
      const flat = arcToCubic(prev[0], prev[1], s[1], s[2], s[3], s[4], s[5], s[6], s[7]);
      stats.arcs++;
      for (let i = 0; i < flat.length; i += 6) {
        const c1 = T(flat[i], flat[i + 1]);
        const c2 = T(flat[i + 2], flat[i + 3]);
        const p = T(flat[i + 4], flat[i + 5]);
        push([pen, c1, c2, p]); pen = p;
      }
    } else if (op === 'Z') {
      closeLoop();
      pen = start;
    }
  }
  closeLoop();
  return { loops, stats };
}

function untransform(m, p) {
  const det = m[0] * m[3] - m[1] * m[2];
  if (!det) return p;
  const x = p[0] - m[4]; const y = p[1] - m[5];
  return [(m[3] * x - m[2] * y) / det, (m[0] * y - m[1] * x) / det];
}

/* ------------------------------------------------------------- loop helpers */

/** Signed area of a bezier loop (shoelace on control polygon endpoints is not
 *  exact for curves, so integrate the exact bezier contribution). */
export function loopSignedArea(loop) {
  let a = 0;
  for (const b of loop) {
    const p = b;
    if (p.length === 2) {
      a += p[0][0] * p[1][1] - p[1][0] * p[0][1];
    } else if (p.length === 3) {
      const [p0, p1, p2] = p;
      a += (p0[0] * (2 * p1[1] + p2[1]) + p1[0] * (-2 * p0[1] + 2 * p2[1]) + p2[0] * (-p0[1] - 2 * p1[1])) / 3;
    } else {
      const [p0, p1, p2, p3] = p;
      a += (p0[0] * (6 * p1[1] + 3 * p2[1] + p3[1])
        + p1[0] * (-6 * p0[1] + 3 * p2[1] + 3 * p3[1])
        + p2[0] * (-3 * p0[1] - 3 * p1[1] + 6 * p3[1])
        + p3[0] * (-p0[1] - 3 * p1[1] - 6 * p2[1])) / 10;
    }
  }
  return a / 2;
}

export function loopBounds(loop) {
  let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity;
  for (const b of loop) for (const p of b) {
    if (p[0] < x0) x0 = p[0]; if (p[0] > x1) x1 = p[0];
    if (p[1] < y0) y0 = p[1]; if (p[1] > y1) y1 = p[1];
  }
  return { x0, y0, x1, y1, w: x1 - x0, h: y1 - y0 };
}

export function loopsToPathD(loops, prec = 4) {
  const f = (v) => {
    const r = Math.round(v * 10 ** prec) / 10 ** prec;
    return Object.is(r, -0) ? 0 : r;
  };
  let d = '';
  for (const loop of loops) {
    d += `M${f(loop[0][0][0])} ${f(loop[0][0][1])}`;
    for (const b of loop) {
      if (b.length === 2) d += `L${f(b[1][0])} ${f(b[1][1])}`;
      else if (b.length === 3) d += `Q${f(b[1][0])} ${f(b[1][1])} ${f(b[2][0])} ${f(b[2][1])}`;
      else d += `C${f(b[1][0])} ${f(b[1][1])} ${f(b[2][0])} ${f(b[2][1])} ${f(b[3][0])} ${f(b[3][1])}`;
    }
    d += 'Z';
  }
  return d;
}

/* ------------------------------------------------------------ document walk */

const DRAWABLE = new Set(['path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon']);
const SKIP = new Set(['defs', 'clipPath', 'mask', 'symbol', 'marker', 'pattern', 'metadata', 'title', 'desc']);

/**
 * Normalize a whole SVG document.
 * @returns {{viewBox:{x,y,w,h}, width:number, height:number, elements:Array}}
 */
export function normalizeSvg(src) {
  const root = parseXml(src);
  const svg = findSvg(root);
  if (!svg) throw new Error('no <svg> element');

  const vbNums = (svg.attrs.viewBox || '').match(NUM);
  const viewBox = vbNums && vbNums.length >= 4
    ? { x: +vbNums[0], y: +vbNums[1], w: +vbNums[2], h: +vbNums[3] }
    : { x: 0, y: 0, w: parseFloat(svg.attrs.width) || 100, h: parseFloat(svg.attrs.height) || 100 };

  const elements = [];
  const stats = { arcs: 0, subpaths: 0, dropped: 0, openClosed: 0, shapes: 0 };
  let idx = 0;

  const walk = (node, ctm, inherited) => {
    for (const child of node.children) {
      if (SKIP.has(child.tag)) continue;
      const m = matMul(ctm, parseTransform(child.attrs.transform));
      const style = { ...inherited };
      if (child.attrs.fill !== undefined) style.fill = child.attrs.fill;
      if (child.attrs['fill-rule'] !== undefined) style.fillRule = child.attrs['fill-rule'];
      if (child.attrs.style) {
        const fm = /(?:^|;)\s*fill\s*:\s*([^;]+)/.exec(child.attrs.style);
        if (fm) style.fill = fm[1].trim();
        const fr = /(?:^|;)\s*fill-rule\s*:\s*([^;]+)/.exec(child.attrs.style);
        if (fr) style.fillRule = fr[1].trim();
      }

      if (child.tag === 'g' || child.tag === 'svg' || child.tag === 'a') {
        walk(child, m, style);
        continue;
      }
      if (!DRAWABLE.has(child.tag)) continue;
      const fill = style.fill ?? '#000';
      if (fill === 'none' || fill === 'transparent') continue;

      const d = shapeToPathD(child.tag, child.attrs);
      if (!d) continue;
      const { loops, stats: st } = pathToLoops(d, m);
      if (!loops.length) continue;
      stats.arcs += st.arcs; stats.subpaths += st.subpaths;
      stats.dropped += st.dropped; stats.openClosed += st.openClosed; stats.shapes++;

      elements.push({
        id: child.attrs.id || `${child.tag}-${idx}`,
        index: idx++,
        tag: child.tag,
        fill,
        fillRule: style.fillRule || 'nonzero',
        loops,
        area: loops.reduce((s, l) => s + loopSignedArea(l), 0),
      });
    }
  };

  walk(svg, IDENT, {});
  return { viewBox, width: viewBox.w, height: viewBox.h, elements, stats };
}

/** Re-serialize normalized geometry as an SVG, for the normalization round-trip check. */
export function elementsToSvg(doc, elements = doc.elements) {
  const vb = doc.viewBox;
  const body = elements
    .map((e) => `<path fill="${e.fill}" fill-rule="${e.fillRule}" d="${loopsToPathD(e.loops)}"/>`)
    .join('\n');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vb.x} ${vb.y} ${vb.w} ${vb.h}">\n${body}\n</svg>\n`;
}
