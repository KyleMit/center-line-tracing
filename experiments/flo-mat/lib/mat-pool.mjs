// Run findMats for each element in a worker thread with a hard timeout, so a
// single pathological element degrades to a recorded failure instead of
// hanging the whole bench. See normalize.mjs QUANTIZE for why this is needed.

import { Worker } from 'node:worker_threads';
import { fileURLToPath } from 'node:url';

const WORKER = fileURLToPath(new URL('./mat-worker.mjs', import.meta.url));

export function matInWorker({ loops, options, sourceElementId, tol, satSweep }, timeoutMs) {
  return new Promise((resolve) => {
    const w = new Worker(WORKER, { workerData: { loops, options, sourceElementId, tol, satSweep } });
    const timer = setTimeout(() => {
      w.terminate();
      resolve({ error: 'timeout', timeoutMs });
    }, timeoutMs);
    w.on('message', (msg) => { clearTimeout(timer); w.terminate(); resolve(msg); });
    w.on('error', (err) => { clearTimeout(timer); resolve({ error: String(err.message || err) }); });
    w.on('exit', () => clearTimeout(timer));
  });
}

/** Sequentially compute per-element MAT graphs with a per-element timeout. */
export async function computeMatGraphs(elements, { options, tol, satSweep, timeoutMs = 20000 }) {
  const out = [];
  for (const el of elements) {
    /* eslint-disable no-await-in-loop */
    const res = await matInWorker({
      loops: el.loops, options, sourceElementId: el.id, tol, satSweep,
    }, timeoutMs);
    out.push({ el, ...res });
  }
  return out;
}
