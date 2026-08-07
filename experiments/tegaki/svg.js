// Minimal SVG normalization stage (§9.2). Ours — Tegaki has no counterpart,
// it consumes opentype.js glyph commands directly.
//
// Track 1 (flo-mat, svg-path-commander) had not pushed a normalizer when this
// track ran, so this is the "otherwise write a minimal one" branch of the
// handoff. Scope is deliberately just what our ten inputs use: path / rect /
// circle / ellipse, nested <g>, and translate/rotate/scale/matrix/skew
// transforms. Presentation attributes beyond fill are ignored.

import { flattenPathData, computePathBBox } from './bezier.js';
import { BEZIER_TOLERANCE } from './constants.js';

const IDENTITY = [1, 0, 0, 1, 0, 0]; // a b c d e f

function mul(m, n) {
  return [
    m[0] * n[0] + m[2] * n[1],
    m[1] * n[0] + m[3] * n[1],
    m[0] * n[2] + m[2] * n[3],
    m[1] * n[2] + m[3] * n[3],
    m[0] * n[4] + m[2] * n[5] + m[4],
    m[1] * n[4] + m[3] * n[5] + m[5],
  ];
}

function applyMatrix(m, p) {
  return { x: m[0] * p.x + m[2] * p.y + m[4], y: m[1] * p.x + m[3] * p.y + m[5] };
}

/** Uniform-ish scale factor of a matrix — sqrt of |det|. Used to keep the
 *  flattening tolerance constant in *final* user units under a transform. */
function matrixScale(m) {
  return Math.sqrt(Math.abs(m[0] * m[3] - m[1] * m[2])) || 1;
}

export function parseTransform(str) {
  if (!str) return IDENTITY;
  let m = IDENTITY;
  const re = /([a-zA-Z]+)\s*\(([^)]*)\)/g;
  let t;
  while ((t = re.exec(str)) !== null) {
    const name = t[1];
    const a = (t[2].match(/[+-]?(?:\d*\.\d+|\d+\.?)(?:[eE][+-]?\d+)?/g) || []).map(Number);
    let n = IDENTITY;
    switch (name) {
      case 'translate':
        n = [1, 0, 0, 1, a[0] || 0, a[1] || 0];
        break;
      case 'scale':
        n = [a[0] ?? 1, 0, 0, a[1] ?? a[0] ?? 1, 0, 0];
        break;
      case 'rotate': {
        const r = ((a[0] || 0) * Math.PI) / 180;
        const c = Math.cos(r);
        const s = Math.sin(r);
        const rot = [c, s, -s, c, 0, 0];
        if (a.length >= 3) {
          n = mul(mul([1, 0, 0, 1, a[1], a[2]], rot), [1, 0, 0, 1, -a[1], -a[2]]);
        } else {
          n = rot;
        }
        break;
      }
      case 'matrix':
        n = [a[0], a[1], a[2], a[3], a[4], a[5]];
        break;
      case 'skewX':
        n = [1, 0, Math.tan(((a[0] || 0) * Math.PI) / 180), 1, 0, 0];
        break;
      case 'skewY':
        n = [1, Math.tan(((a[0] || 0) * Math.PI) / 180), 0, 1, 0, 0];
        break;
    }
    m = mul(m, n);
  }
  return m;
}

function attrs(tagBody) {
  const out = {};
  const re = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*"([^"]*)"/g;
  let m;
  while ((m = re.exec(tagBody)) !== null) out[m[1]] = m[2];
  return out;
}

/** Rounded-rect (or plain rect) as a `d` string, per the SVG shape equations. */
function rectToPath(a) {
  const x = Number(a.x || 0);
  const y = Number(a.y || 0);
  const w = Number(a.width || 0);
  const h = Number(a.height || 0);
  let rx = a.rx !== undefined ? Number(a.rx) : a.ry !== undefined ? Number(a.ry) : 0;
  let ry = a.ry !== undefined ? Number(a.ry) : a.rx !== undefined ? Number(a.rx) : 0;
  rx = Math.min(rx, w / 2);
  ry = Math.min(ry, h / 2);
  if (rx <= 0 || ry <= 0) {
    return `M ${x} ${y} L ${x + w} ${y} L ${x + w} ${y + h} L ${x} ${y + h} Z`;
  }
  return (
    `M ${x + rx} ${y} L ${x + w - rx} ${y} A ${rx} ${ry} 0 0 1 ${x + w} ${y + ry}` +
    ` L ${x + w} ${y + h - ry} A ${rx} ${ry} 0 0 1 ${x + w - rx} ${y + h}` +
    ` L ${x + rx} ${y + h} A ${rx} ${ry} 0 0 1 ${x} ${y + h - ry}` +
    ` L ${x} ${y + ry} A ${rx} ${ry} 0 0 1 ${x + rx} ${y} Z`
  );
}

function ellipseToPath(cx, cy, rx, ry) {
  return (
    `M ${cx - rx} ${cy} A ${rx} ${ry} 0 0 1 ${cx + rx} ${cy}` + ` A ${rx} ${ry} 0 0 1 ${cx - rx} ${cy} Z`
  );
}

function isFilled(fill) {
  if (fill === undefined || fill === null) return false;
  const f = fill.trim().toLowerCase();
  return f !== '' && f !== 'none' && f !== 'transparent';
}

/**
 * Parse an SVG file into filled elements, each with its contours flattened to
 * polygons in final user-space coordinates.
 *
 * Returns { viewBox, width, height, elements: [{ id, index, fill, fillOpacity,
 *           tag, subPaths, bbox }] }
 */
export function parseSvg(svgText, tolerance = BEZIER_TOLERANCE) {
  const svgTag = /<svg\b([^>]*)>/i.exec(svgText);
  const svgAttrs = svgTag ? attrs(svgTag[1]) : {};
  let viewBox = null;
  if (svgAttrs.viewBox) {
    const v = svgAttrs.viewBox.trim().split(/[\s,]+/).map(Number);
    if (v.length === 4) viewBox = { x: v[0], y: v[1], w: v[2], h: v[3] };
  }

  const elements = [];
  const stack = [{ m: IDENTITY, fill: undefined, fillOpacity: undefined }];
  const tagRe = /<\/?([a-zA-Z][a-zA-Z0-9]*)\b([^>]*?)(\/?)>/g;
  let t;
  let index = 0;

  while ((t = tagRe.exec(svgText)) !== null) {
    const raw = t[0];
    const name = t[1].toLowerCase();
    const body = t[2];
    const selfClosing = t[3] === '/';
    const closing = raw.startsWith('</');

    if (name === 'svg') continue;

    if (closing) {
      if (name === 'g' && stack.length > 1) stack.pop();
      continue;
    }

    const a = attrs(body);
    const parent = stack[stack.length - 1];
    const m = a.transform ? mul(parent.m, parseTransform(a.transform)) : parent.m;
    const fill = a.fill !== undefined ? a.fill : parent.fill;
    const fillOpacity = a['fill-opacity'] !== undefined ? Number(a['fill-opacity']) : parent.fillOpacity;

    if (name === 'g') {
      if (!selfClosing) stack.push({ m, fill, fillOpacity });
      continue;
    }

    let d = null;
    if (name === 'path') d = a.d;
    else if (name === 'rect') d = rectToPath(a);
    else if (name === 'circle') d = ellipseToPath(Number(a.cx || 0), Number(a.cy || 0), Number(a.r || 0), Number(a.r || 0));
    else if (name === 'ellipse') d = ellipseToPath(Number(a.cx || 0), Number(a.cy || 0), Number(a.rx || 0), Number(a.ry || 0));
    else continue;

    if (!d || !isFilled(fill)) continue;

    // Flatten in local space at a tolerance pre-divided by the transform's scale,
    // so the error is `tolerance` in final user units.
    const local = flattenPathData(d, tolerance / matrixScale(m));
    const subPaths = local.map((sp) => sp.map((p) => applyMatrix(m, p)));
    if (subPaths.length === 0) continue;

    elements.push({
      id: a.id || `${name}${index}`,
      index: index++,
      tag: name,
      fill,
      fillOpacity: fillOpacity === undefined ? 1 : fillOpacity,
      subPaths,
      bbox: computePathBBox(subPaths),
    });
  }

  return {
    viewBox,
    width: svgAttrs.width || (viewBox ? String(viewBox.w) : undefined),
    height: svgAttrs.height || (viewBox ? String(viewBox.h) : undefined),
    elements,
  };
}
