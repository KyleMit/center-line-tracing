// Worker side of the MAT pool: one element in, one graph out.
// Isolated in a worker thread so a flo-mat hang can be terminated (see the
// QUANTIZE note in normalize.mjs).

import { parentPort, workerData } from 'node:worker_threads';
import { runMat, applySat, matToGraph, mergeGraphs } from './mat.mjs';

const { loops, options, sourceElementId, tol, satSweep } = workerData;

const t0 = Date.now();
const { mats } = runMat(loops, options);
const finalMats = satSweep && satSweep > 1 ? applySat(mats, satSweep) : mats;
const graph = mergeGraphs(finalMats.map((m) => matToGraph(m, { sourceElementId, tol })));
parentPort.postMessage({ graph, ms: Date.now() - t0, mats: finalMats.length });
