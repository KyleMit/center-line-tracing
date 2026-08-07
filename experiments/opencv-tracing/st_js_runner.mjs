// Runs the vendored vanilla-JS skeleton-tracing over a raw uint8 skeleton read
// from stdin, and prints the polylines as JSON. Used both by tracers.st_js and
// by the cross-runtime portability check, so the JS and C implementations can
// be diffed on byte-identical skeletons.
//
// usage: node st_js_runner.mjs <width> <height> [csize] [maxIter]

import TraceSkeleton from './vendor/skeleton-tracing/js/trace_skeleton.vanilla.js';

const [w, h, csize = '10', maxIter = '999'] = process.argv.slice(2);
const W = Number(w), H = Number(h);

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const raw = Buffer.concat(chunks);
if (raw.length !== W * H) {
  throw new Error(`expected ${W * H} bytes, got ${raw.length}`);
}

const im = new Array(W * H);
for (let i = 0; i < raw.length; i++) im[i] = raw[i] ? 1 : 0;

// traceSkeleton() directly, NOT trace(): the skeleton is already thinned by
// cv2.ximgproc, and running upstream's Zhang-Suen again would change it.
const polys = TraceSkeleton.traceSkeleton(
  im, W, H, 0, 0, W, H, Number(csize), Number(maxIter), []);

process.stdout.write(JSON.stringify(polys));
