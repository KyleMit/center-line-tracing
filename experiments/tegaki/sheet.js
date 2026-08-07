#!/usr/bin/env node
// Contact sheets (Common Setup §"Contact sheets"). Emits HTML and PNG.
//
//   node experiments/tegaki/sheet.js comparison [--tag baseline]
//   node experiments/tegaki/sheet.js progress --image house-wide
//   node experiments/tegaki/sheet.js synth [--tag baseline]

import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync } from 'node:fs';
import sharp from 'sharp';
import { svgToPng, overlaySvg } from './render.js';
import { parseArgs } from './cli.js';
import { REAL_LADDER } from './bench.js';

const TILE = 440;
const LABEL_H = 34;
const METRICS = 'debug/tegaki/metrics.json';

function loadMetrics() {
  return existsSync(METRICS) ? JSON.parse(readFileSync(METRICS, 'utf8')) : { runs: {} };
}

/** Pixel diff of two equally-sized PNG buffers -> red/blue difference image. */
async function diffPng(aBuf, bBuf, w, h) {
  const a = await sharp(aBuf).resize(w, h, { fit: 'fill' }).greyscale().raw().toBuffer();
  const b = await sharp(bBuf).resize(w, h, { fit: 'fill' }).greyscale().raw().toBuffer();
  const out = Buffer.alloc(w * h * 3, 255);
  let diff = 0;
  for (let i = 0; i < w * h; i++) {
    const d = a[i] - b[i];
    if (Math.abs(d) > 40) {
      diff++;
      if (d < 0) {
        // present in A (original ink), missing in B  -> red
        out[i * 3] = 220;
        out[i * 3 + 1] = 40;
        out[i * 3 + 2] = 40;
      } else {
        // present in B (recovered), absent in A      -> blue
        out[i * 3] = 40;
        out[i * 3 + 1] = 90;
        out[i * 3 + 2] = 220;
      }
    }
  }
  const png = await sharp(out, { raw: { width: w, height: h, channels: 3 } }).png().toBuffer();
  return { png, pct: (100 * diff) / (w * h) };
}

async function labelled(buf, text, w, h) {
  const esc = text.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const bar = Buffer.from(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${LABEL_H}">` +
      `<rect width="${w}" height="${LABEL_H}" fill="#1b1d21"/>` +
      `<text x="8" y="22" font-family="monospace" font-size="13" fill="#e6e6e6">${esc}</text></svg>`,
  );
  const img = await sharp(buf).resize(w, h, { fit: 'contain', background: '#ffffff' }).png().toBuffer();
  return sharp({ create: { width: w, height: h + LABEL_H, channels: 3, background: '#ffffff' } })
    .composite([
      { input: img, top: 0, left: 0 },
      { input: await sharp(bar).png().toBuffer(), top: h, left: 0 },
    ])
    .png()
    .toBuffer();
}

async function gridPng(rows, cellW, cellH, out) {
  const cols = Math.max(...rows.map((r) => r.length));
  const W = cols * cellW;
  const H = rows.length * (cellH + LABEL_H);
  const composite = [];
  rows.forEach((row, y) => {
    row.forEach((buf, x) => {
      composite.push({ input: buf, top: y * (cellH + LABEL_H), left: x * cellW });
    });
  });
  await sharp({ create: { width: W, height: H, channels: 3, background: '#ffffff' } })
    .composite(composite)
    .png()
    .toFile(out);
}

function aspect(svgText) {
  const m = /viewBox="([^"]*)"/.exec(svgText);
  if (!m) return 1;
  const v = m[1].trim().split(/[\s,]+/).map(Number);
  return v[2] / v[3];
}

async function comparisonSheet(tag) {
  const metrics = loadMetrics();
  const run = metrics.runs[`real:${tag}`];
  const byName = new Map((run?.rows ?? []).map((r) => [r.name, r]));

  const rows = [];
  const html = [];
  for (const name of REAL_LADDER) {
    const outPath = `debug/tegaki/out/${name}.${tag}.svg`;
    if (!existsSync(outPath)) continue;
    const inSvg = readFileSync(`inputs/${name}.svg`, 'utf8');
    const outSvg = readFileSync(outPath, 'utf8');
    const ar = aspect(inSvg);
    const cw = TILE;
    const ch = Math.round(TILE / ar);

    const inPng = svgToPng(inSvg, cw);
    const outPng = svgToPng(outSvg, cw);
    const ovlPng = svgToPng(overlaySvg(inSvg, outSvg), cw);
    const { png: dPng, pct } = await diffPng(inPng, outPng, cw, ch);

    const m = byName.get(name) ?? {};
    const label = `${name}  IoU ${m.iou ?? '-'}  pxdiff ${pct.toFixed(2)}%  strokes ${m.strokeCount ?? '-'}`;
    rows.push([
      await labelled(inPng, `${label} | input`, cw, ch),
      await labelled(outPng, 'output', cw, ch),
      await labelled(dPng, `diff (red=missing ink, blue=extra)`, cw, ch),
      await labelled(ovlPng, 'overlay: centerlines over fill', cw, ch),
    ]);

    mkdirSync('debug/tegaki/sheet', { recursive: true });
    writeFileSync(`debug/tegaki/sheet/${name}.${tag}.diff.png`, dPng);
    html.push(
      `<tr><td colspan="4" class="h">${label}</td></tr><tr>` +
        [inPng, outPng, dPng, ovlPng]
          .map((b) => `<td><img src="data:image/png;base64,${b.toString('base64')}"></td>`)
          .join('') +
        `</tr>`,
    );
  }

  mkdirSync('debug/tegaki/sheet', { recursive: true });
  await gridPng(rows, TILE, Math.round(TILE / 1), `debug/tegaki/sheet/comparison.${tag}.png`);
  writeFileSync(
    `debug/tegaki/sheet/comparison.${tag}.html`,
    `<!doctype html><meta charset="utf-8"><title>tegaki comparison — ${tag}</title>` +
      `<style>body{background:#14161a;color:#ddd;font:13px/1.5 system-ui;margin:16px}` +
      `img{width:${TILE}px;background:#fff;display:block}td{padding:4px;vertical-align:top}` +
      `.h{font:12px monospace;color:#9fe;padding-top:14px}</style><table>${html.join('')}</table>`,
  );
  console.log(`wrote debug/tegaki/sheet/comparison.${tag}.{html,png} (${rows.length} rows)`);
}

async function synthSheet(tag) {
  const dir = 'debug/tegaki/synth';
  const metrics = loadMetrics();
  const byName = new Map((metrics.runs[`synth:${tag}`]?.rows ?? []).map((r) => [r.name, r]));
  const files = readdirSync(dir).filter((f) => f.endsWith('.svg')).sort();
  const cells = [];
  const html = [];
  for (const f of files) {
    const name = f.replace(/\.svg$/, '');
    const outPath = `debug/tegaki/out/synth/${name}.${tag}.svg`;
    if (!existsSync(outPath)) continue;
    const inSvg = readFileSync(`${dir}/${f}`, 'utf8');
    const outSvg = readFileSync(outPath, 'utf8');
    const cw = TILE;
    const ch = Math.round(TILE / aspect(inSvg));
    const ovl = svgToPng(overlaySvg(inSvg, outSvg), cw);
    const m = byName.get(name) ?? {};
    const label = `${name} IoU ${m.iou ?? '-'} clP95 ${m.centerline?.p95 ?? '-'} Hd ${m.centerline?.hausdorff ?? '-'}`;
    cells.push(await labelled(ovl, label, cw, ch));
    html.push(`<td><div class="h">${label}</div><img src="data:image/png;base64,${ovl.toString('base64')}"></td>`);
  }
  const rows = [];
  for (let i = 0; i < cells.length; i += 4) rows.push(cells.slice(i, i + 4));
  mkdirSync('debug/tegaki/sheet', { recursive: true });
  await gridPng(rows, TILE, Math.round(TILE / 1.5), `debug/tegaki/sheet/synth.${tag}.png`);
  const htmlRows = [];
  for (let i = 0; i < html.length; i += 4) htmlRows.push(`<tr>${html.slice(i, i + 4).join('')}</tr>`);
  writeFileSync(
    `debug/tegaki/sheet/synth.${tag}.html`,
    `<!doctype html><meta charset="utf-8"><title>tegaki synthetic — ${tag}</title>` +
      `<style>body{background:#14161a;color:#ddd;font:13px/1.5 system-ui;margin:16px}` +
      `img{width:${TILE}px;background:#fff;display:block}td{padding:4px;vertical-align:top}` +
      `.h{font:11px monospace;color:#9fe}</style><table>${htmlRows.join('')}</table>`,
  );
  console.log(`wrote debug/tegaki/sheet/synth.${tag}.{html,png} (${cells.length} tiles)`);
}

/** Progress sheet: one tile per iteration of the focus image, chronological. */
async function progressSheet(image) {
  const metrics = loadMetrics();
  const iters = [];
  for (const [key, run] of Object.entries(metrics.runs)) {
    if (!key.startsWith('real:')) continue;
    const tag = key.slice(5);
    const p = `debug/tegaki/out/${image}.${tag}.svg`;
    if (!existsSync(p)) continue;
    const row = (run.rows ?? []).find((r) => r.name === image);
    iters.push({ tag, path: p, at: run.at, iou: row?.iou, strokes: row?.strokeCount });
  }
  iters.sort((a, b) => String(a.at).localeCompare(String(b.at)));
  if (iters.length === 0) {
    console.log(`no iterations recorded for ${image}`);
    return;
  }

  const inSvg = readFileSync(`inputs/${image}.svg`, 'utf8');
  const cw = TILE;
  const ch = Math.round(TILE / aspect(inSvg));
  const cells = [];
  const html = [];
  for (const it of iters) {
    const png = svgToPng(overlaySvg(inSvg, readFileSync(it.path, 'utf8')), cw);
    const label = `${it.tag}  IoU ${it.iou ?? '-'}  strokes ${it.strokes ?? '-'}`;
    cells.push(await labelled(png, label, cw, ch));
    html.push(`<td><div class="h">${label}</div><img src="data:image/png;base64,${png.toString('base64')}"></td>`);
  }
  const rows = [];
  for (let i = 0; i < cells.length; i += 3) rows.push(cells.slice(i, i + 3));
  mkdirSync('debug/tegaki/sheet', { recursive: true });
  await gridPng(rows, TILE, ch, `debug/tegaki/sheet/progress.${image}.png`);
  const htmlRows = [];
  for (let i = 0; i < html.length; i += 3) htmlRows.push(`<tr>${html.slice(i, i + 3).join('')}</tr>`);
  writeFileSync(
    `debug/tegaki/sheet/progress.${image}.html`,
    `<!doctype html><meta charset="utf-8"><title>tegaki progress — ${image}</title>` +
      `<style>body{background:#14161a;color:#ddd;font:13px/1.5 system-ui;margin:16px}` +
      `img{width:${TILE}px;background:#fff;display:block}td{padding:4px;vertical-align:top}` +
      `.h{font:11px monospace;color:#9fe}</style><table>${htmlRows.join('')}</table>`,
  );
  console.log(`wrote debug/tegaki/sheet/progress.${image}.{html,png} (${cells.length} iterations)`);
}

/** Zoomed crop of a region, input | output | overlay. */
export async function cropSheet(image, tag, regions, out) {
  const inSvg = readFileSync(`inputs/${image}.svg`, 'utf8');
  const outSvg = readFileSync(`debug/tegaki/out/${image}.${tag}.svg`, 'utf8');
  const vb = /viewBox="([^"]*)"/.exec(inSvg)[1].trim().split(/[\s,]+/).map(Number);
  const cells = [];
  for (const r of regions) {
    const sub = (svg) => svg.replace(/viewBox="[^"]*"/, `viewBox="${r.x} ${r.y} ${r.w} ${r.h}"`);
    const ovl = svgToPng(sub(overlaySvg(inSvg, outSvg)), TILE);
    cells.push(await labelled(ovl, `${image} crop ${r.label}`, TILE, Math.round((TILE * r.h) / r.w)));
  }
  const rows = [];
  for (let i = 0; i < cells.length; i += 3) rows.push(cells.slice(i, i + 3));
  await gridPng(rows, TILE, TILE, out);
  console.log(`wrote ${out} (viewBox ${vb.join(' ')})`);
}

async function main() {
  const { positional, opts } = parseArgs(process.argv.slice(2));
  const mode = positional[0] || 'comparison';
  const tag = opts.tag || 'baseline';
  if (mode === 'comparison') await comparisonSheet(tag);
  else if (mode === 'synth') await synthSheet(tag);
  else if (mode === 'progress') await progressSheet(opts.image || 'house-wide');
  else console.error(`unknown mode ${mode}`);
}

if (import.meta.url === `file://${process.argv[1]}`) main();
