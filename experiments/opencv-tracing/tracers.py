"""Skeleton -> polyline tracers, all consuming an identical 1-pixel skeleton.

Three of them wrap LingDong-'s `skeleton-tracing` (vendored, MIT) in three
different runtimes, which is the portability claim this track exists to test:

    st_c      C implementation via ctypes (production speed)
    st_py     the vendored pure-Python implementation (reference, slow)
    st_js     the vendored vanilla-JS implementation, run under node

The fourth, `bespoke`, is a verbatim port of the incumbent pipeline's
hand-rolled tracer (`src/convert_filled_svg_to_stroked_lines.py`
:func:`trace_skeleton_paths`), copied here rather than imported so the
incumbent stays untouched per Common Setup's directory rules. It is the
comparison point for "does a vendored library match a bespoke tracer".

Every tracer returns `list[list[(x, y)]]` in *pixel* coordinates.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
VENDOR = HERE / "vendor" / "skeleton-tracing"

CSIZE_DEFAULT = 10
MAX_ITER_DEFAULT = 999

NEIGHBORS_8 = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]


# ---------------------------------------------------------------------------
# skeleton-tracing, C implementation (ctypes)
# ---------------------------------------------------------------------------

_LIB = None


def _lib():
    global _LIB
    if _LIB is None:
        so = VENDOR / "c" / "libtraceskeleton.so"
        if not so.exists():
            raise RuntimeError(f"{so} missing; run experiments/opencv-tracing/build.sh")
        lib = ctypes.CDLL(str(so))
        lib.trace_pre_thinned.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int]
        lib.trace_pre_thinned.restype = None
        lib.trace.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int]
        lib.trace.restype = None
        lib.pop_polyline.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
        lib.pop_polyline.restype = ctypes.c_int
        _LIB = lib
    return _LIB


def st_c(skeleton: np.ndarray, csize: int = CSIZE_DEFAULT,
         max_iter: int = MAX_ITER_DEFAULT, thin_first: bool = False):
    """skeleton-tracing, C. `thin_first` runs upstream's own Zhang-Suen first."""
    lib = _lib()
    h, w = skeleton.shape
    buf = np.ascontiguousarray((skeleton > 0).astype(np.uint8))
    ptr = buf.ctypes.data_as(ctypes.c_char_p)
    (lib.trace if thin_first else lib.trace_pre_thinned)(ptr, w, h, csize, max_iter)

    cap = max(1024, h * w // 4)
    out = (ctypes.c_int * (2 * cap))()
    polys = []
    while True:
        n = lib.pop_polyline(out, cap)
        if n < 0:
            break
        polys.append([(out[2 * i], out[2 * i + 1]) for i in range(n)])
    return polys


# ---------------------------------------------------------------------------
# skeleton-tracing, vendored pure Python
# ---------------------------------------------------------------------------

def st_py(skeleton: np.ndarray, csize: int = CSIZE_DEFAULT,
          max_iter: int = MAX_ITER_DEFAULT):
    sys.path.insert(0, str(VENDOR / "py"))
    import trace_skeleton as ts  # noqa: E402  (vendored module)

    h, w = skeleton.shape
    im = (skeleton > 0).astype(np.uint8)
    return [[tuple(p) for p in poly]
            for poly in ts.traceSkeleton(im, 0, 0, w, h, csize, max_iter, [])]


# ---------------------------------------------------------------------------
# skeleton-tracing, vendored vanilla JS (node)
# ---------------------------------------------------------------------------

def st_js(skeleton: np.ndarray, csize: int = CSIZE_DEFAULT,
          max_iter: int = MAX_ITER_DEFAULT):
    h, w = skeleton.shape
    flat = (skeleton > 0).astype(np.uint8).tobytes()
    proc = subprocess.run(
        ["node", str(HERE / "st_js_runner.mjs"), str(w), str(h), str(csize), str(max_iter)],
        input=flat, capture_output=True, check=True)
    return [[tuple(p) for p in poly] for poly in json.loads(proc.stdout)]


# ---------------------------------------------------------------------------
# The incumbent's hand-rolled tracer
# ---------------------------------------------------------------------------

def _degree(skeleton, y, x):
    h, w = skeleton.shape
    count = 0
    for dy, dx in NEIGHBORS_8:
        yy, xx = y + dy, x + dx
        if 0 <= yy < h and 0 <= xx < w and skeleton[yy, xx]:
            count += 1
    return count


def bespoke(skeleton: np.ndarray):
    """Port of src/convert_filled_svg_to_stroked_lines.py::trace_skeleton_paths.

    Upstream works in (y, x); output is converted to (x, y) here so every
    tracer in this module shares one convention.
    """
    skeleton = skeleton > 0
    h, w = skeleton.shape
    pts = np.argwhere(skeleton)
    if len(pts) == 0:
        return []

    deg = np.zeros(skeleton.shape, dtype=np.uint8)
    for y, x in pts:
        deg[y, x] = _degree(skeleton, int(y), int(x))

    nodes = set(map(tuple, np.argwhere(skeleton & (deg != 2))))
    visited = set()
    paths = []

    def edge_key(a, b):
        return tuple(sorted((a, b)))

    def neighbors(p):
        y, x = p
        out = []
        for dy, dx in NEIGHBORS_8:
            q = (y + dy, x + dx)
            if 0 <= q[0] < h and 0 <= q[1] < w and skeleton[q]:
                out.append(q)
        return out

    for node in list(nodes):
        for nb in neighbors(node):
            key = edge_key(node, nb)
            if key in visited:
                continue
            path = [node, nb]
            visited.add(key)
            prev, cur = node, nb
            while cur not in nodes:
                nxt_pixels = [q for q in neighbors(cur) if q != prev]
                if not nxt_pixels:
                    break
                nxt = nxt_pixels[0]
                visited.add(edge_key(cur, nxt))
                path.append(nxt)
                prev, cur = cur, nxt
            paths.append(path)

    remaining = []
    for y, x in pts:
        p = (int(y), int(x))
        for q in neighbors(p):
            if edge_key(p, q) not in visited:
                remaining.append((p, q))

    while remaining:
        start, nb = remaining.pop()
        if edge_key(start, nb) in visited:
            continue
        path = [start, nb]
        visited.add(edge_key(start, nb))
        prev, cur = start, nb
        guard = 0
        while cur != start and guard < 100000:
            guard += 1
            nxt_pixels = [q for q in neighbors(cur) if q != prev]
            if not nxt_pixels:
                break
            nxt = nxt_pixels[0]
            if edge_key(cur, nxt) in visited and nxt != start:
                break
            visited.add(edge_key(cur, nxt))
            path.append(nxt)
            prev, cur = cur, nxt
        if len(path) > 2:
            paths.append(path)

    return [[(int(x), int(y)) for (y, x) in path] for path in paths]


TRACERS = {
    "st-c": st_c,
    "st-py": st_py,
    "st-js": st_js,
    "bespoke": bespoke,
}
