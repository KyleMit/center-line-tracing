#!/usr/bin/env node
// Visualize the stroke ORDER and DIRECTION metadata (report §9.8, Experiment 5).
// No other track produces this, so it needs its own picture to be checkable.
//
//   node experiments/tegaki/order-sheet.js [image ...]
//
// Each stroke is drawn in a viridis-like ramp from draw-order 0 (dark blue) to
// last (yellow), with an arrowhead at the pen-up end and a dot at pen-down, so
// both the sequence and the per-stroke direction are legible at a glance.

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import sharp from 'sharp';
import { svgToPng } from './render.js';

const RAMP = ['#440154', '#414487', '#2a788e', '#22a884', '#7ad151', '#fde725'];

function rampColor(t) {
  const x = Math.max(0, Math.min(0.999, t)) * (RAMP.length - 1);
  const i = Math.floor(x);
  const f = x - i;
  const hex = (c) => [1, 3, 5].map((k) => parseInt(c.slice(k, k + 2), 16));
  const a = hex(RAMP[i]);
  const b = hex(RAMP[Math.min(RAMP.length - 1, i + 1)]);
  const m = a.map((v, k) => Math.round(v + (b[k] - v) * f));
  return `rgb(${m[0]},${m[1]},${m[2]})`;
}

/** Build an order/direction visualization SVG from a graph JSON. */
export function orderSvg(graph, opts = {}) {
  const vb = graph.viewBox;
  const order = graph.strokeOrderMeta.order;
  const byId = new Map(graph.edges.map((e) => [e.id, e]));
  const n = order.length;
  const span = vb ? Math.max(vb.w, vb.h) : 1000;
  const lw = opts.lineWidth ?? span / 450;
  const head = lw * 5;

  const parts = [];
  // Faint grey underlay of the recovered geometry, so order is read against shape
  parts.push(`<g stroke="#cccccc" fill="none" stroke-width="${lw * 3}" stroke-linecap="round">`);
  for (const e of graph.edges) {
    parts.push(`<path d="${e.geometry.map((p, i) => `${i ? 'L' : 'M'} ${p.x} ${p.y}`).join(' ')}"/>`);
  }
  parts.push('</g>');

  order.forEach((id, k) => {
    const e = byId.get(id);
    if (!e) return;
    const c = rampColor(n > 1 ? k / (n - 1) : 0);
    const g = e.geometry;
    const d = g.map((p, i) => `${i ? 'L' : 'M'} ${p.x} ${p.y}`).join(' ');
    parts.push(`<path d="${d}" fill="none" stroke="${c}" stroke-width="${lw}" stroke-linecap="round"/>`);

    // pen-down marker (geometry[0] is ALWAYS the pen-down point, by schema)
    parts.push(`<circle cx="${g[0].x}" cy="${g[0].y}" r="${lw * 1.8}" fill="${c}"/>`);

    // pen-up arrowhead along the final tangent
    if (g.length >= 2) {
      const a = g[g.length - 2];
      const b = g[g.length - 1];
      const len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
      const ux = (b.x - a.x) / len;
      const uy = (b.y - a.y) / len;
      const px = -uy;
      const py = ux;
      parts.push(
        `<polygon points="${b.x},${b.y} ` +
          `${b.x - ux * head + px * head * 0.45},${b.y - uy * head + py * head * 0.45} ` +
          `${b.x - ux * head - px * head * 0.45},${b.y - uy * head - py * head * 0.45}" fill="${c}"/>`,
      );
    }
    if (e.strokeOrder?.class === 'dot') {
      parts.push(`<circle cx="${g[0].x}" cy="${g[0].y}" r="${lw * 4}" fill="none" stroke="${c}" stroke-width="${lw * 0.6}"/>`);
    }
  });

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" version="1.1"${vb ? ` viewBox="${vb.x} ${vb.y} ${vb.w} ${vb.h}"` : ''}>` +
    `<rect x="${vb ? vb.x : 0}" y="${vb ? vb.y : 0}" width="${vb ? vb.w : 1000}" height="${vb ? vb.h : 1000}" fill="#ffffff"/>` +
    parts.join('') +
    `</svg>`
  );
}

async function main() {
  const images = process.argv.slice(2);
  const list = images.length ? images : ['house-wide', 'boat-tall', 'dinosaur-wide', 'landscape-square'];
  mkdirSync('debug/tegaki/sheet', { recursive: true });
  const tiles = [];
  const W = 460;

  for (const name of list) {
    const graph = JSON.parse(readFileSync(`debug/tegaki/graphs/${name}.json`, 'utf8'));
    const svg = orderSvg(graph);
    writeFileSync(`debug/tegaki/sheet/order.${name}.svg`, svg);
    const png = svgToPng(svg, W);
    const h = Math.round((W * graph.viewBox.h) / graph.viewBox.w);
    const dots = graph.edges.filter((e) => e.strokeOrder?.class === 'dot').length;
    const rev = graph.edges.filter((e) => e.strokeOrder?.reversed).length;
    const label = `${name} — ${graph.edges.length} strokes in order, ${rev} reversed by orientation, ${dots} dots deferred`;
    const bar = Buffer.from(
      `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="34">` +
        `<rect width="${W}" height="34" fill="#1b1d21"/>` +
        `<text x="8" y="22" font-family="monospace" font-size="11" fill="#e6e6e6">${label}</text></svg>`,
    );
    tiles.push(
      await sharp({ create: { width: W, height: h + 34, channels: 3, background: '#ffffff' } })
        .composite([
          { input: await sharp(png).resize(W, h, { fit: 'contain', background: '#fff' }).png().toBuffer(), top: 0, left: 0 },
          { input: await sharp(bar).png().toBuffer(), top: h, left: 0 },
        ])
        .png()
        .toBuffer(),
    );
    console.log(label);
  }

  const cols = 2;
  const rows = Math.ceil(tiles.length / cols);
  const meta = await Promise.all(tiles.map((t) => sharp(t).metadata()));
  const cellH = Math.max(...meta.map((m) => m.height));
  const composite = tiles.map((t, i) => ({ input: t, top: Math.floor(i / cols) * cellH, left: (i % cols) * W }));
  await sharp({ create: { width: cols * W, height: rows * cellH, channels: 3, background: '#ffffff' } })
    .composite(composite)
    .png()
    .toFile('debug/tegaki/sheet/stroke-order.png');
  console.log('wrote debug/tegaki/sheet/stroke-order.png');
}

if (import.meta.url === `file://${process.argv[1]}`) main();
