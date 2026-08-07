// Deterministic SVG rasterization for the `opencv-tracing` track (report §7.1, §15).
//
// Reads a JSON job description on stdin and writes one PNG per job. Rendering is
// done by resvg, which the report picks specifically because its output is
// reproducible across platforms — the raster masks are the shared substrate for
// the Track 3 / Track 6 comparison, so they must be identical between tracks.
//
// Each element is rendered into a tight bounding box rather than the full canvas
// (report §16: "crop each connected component to a tight bounding box before
// skeletonization"). On house-wide.svg that is the difference between 19 renders
// of a 6648x3784 canvas and 19 small ones.
//
// stdin:  { "outDir": "...", "scale": 4, "pad": 4,
//           "jobs": [ { "id": "el000", "svg": "<svg .../>", "element": "<path .../>" } ] }
// stdout: { "resvg": "2.6.2", "written": [ { id, png, x0, y0, width, height } ] }
//   x0/y0 are the crop origin in SVG user units.
//
// Rasterization contract (Track 3 must match these exactly):
//   renderer      @resvg/resvg-js 2.6.2
//   fitTo         { mode: 'zoom', value: scale }        <- NOT 'width'; crop-invariant
//   crop          element bbox expanded by `pad` user units, filled opaque black
//   shape fill    #ffffff
//   antialiasing  resvg default (shape antialiasing on)
//   threshold     red channel > 128  (applied on the Python side)
//   pixel->svg    svg = cropOrigin + (pixelIndex + 0.5) / scale

import { createRequire } from 'node:module';
import { writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

const require = createRequire(import.meta.url);
const { Resvg } = require('@resvg/resvg-js');
const resvgVersion = require('@resvg/resvg-js/package.json').version;

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const job = JSON.parse(Buffer.concat(chunks).toString('utf8'));
const scale = job.scale ?? 4;
const pad = job.pad ?? 4;

mkdirSync(job.outDir, { recursive: true });

const written = [];
for (const item of job.jobs) {
  // Pass 1: bbox of the element alone, in SVG user units.
  const probe = new Resvg(item.svg, { fitTo: { mode: 'zoom', value: scale } });
  let bb;
  try {
    bb = probe.getBBox();
  } catch {
    bb = null;
  }
  if (!bb || !(bb.width > 0) || !(bb.height > 0)) {
    written.push({ id: item.id, png: null, empty: true });
    continue;
  }

  // Pass 2: an opaque black rect at the padded bbox both supplies the mask
  // background and *defines* the crop region, since resvg's BBox objects
  // cannot be constructed on the JS side.
  //
  // The rect is snapped outward onto the *global* canvas pixel grid. Without
  // this the crop starts at a fractional pixel, resvg rounds it, and every
  // element lands up to half a pixel off its true position — which shows up
  // downstream as a systematic sub-pixel bias in every centerline.
  const snapDown = (v) => job.originX + Math.floor((v - job.originX) * scale) / scale;
  const snapUp = (v) => job.originX + Math.ceil((v - job.originX) * scale) / scale;
  const snapDownY = (v) => job.originY + Math.floor((v - job.originY) * scale) / scale;
  const snapUpY = (v) => job.originY + Math.ceil((v - job.originY) * scale) / scale;

  const x0 = snapDown(bb.x - pad), y0 = snapDownY(bb.y - pad);
  const x1 = snapUp(bb.x + bb.width + pad), y1 = snapUpY(bb.y + bb.height + pad);
  const w = x1 - x0, h = y1 - y0;
  const framed = item.svg.replace(
    '<!--BG-->',
    `<rect x="${x0}" y="${y0}" width="${w}" height="${h}" fill="#000000"/>`);

  const resvg = new Resvg(framed, {
    fitTo: { mode: 'zoom', value: scale },
    font: { loadSystemFonts: false },
  });
  resvg.cropByBBox(resvg.getBBox());
  const img = resvg.render();
  const out = join(job.outDir, `${item.id}.png`);
  writeFileSync(out, img.asPng());
  written.push({ id: item.id, png: out, x0, y0, width: img.width, height: img.height });
}

process.stdout.write(JSON.stringify({ resvg: resvgVersion, written }));
