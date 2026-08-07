/*
 * st_shim.c — thin ctypes-friendly shim over LingDong-'s skeleton-tracing
 * (vendored from github.com/LingDong-/skeleton-tracing @ f5dd65e, MIT).
 *
 * The upstream SWIG entry point `trace()` runs its own Zhang-Suen thinning
 * before tracing. This track needs to feed it a skeleton produced by
 * cv2.ximgproc.thinning instead, so the upstream .c is included verbatim and
 * one extra entry point is added here that skips the internal thinning pass.
 *
 * Nothing in the upstream file is modified.
 */

#include "trace_skeleton.c"

/* Trace an ALREADY-THINNED 1-pixel skeleton; skips upstream's thinning_zs(). */
void trace_pre_thinned(char *img, int w, int h, int csize, int maxIter) {
  W = w;
  H = h;
  destroy_polylines(polylines);
  destroy_rects();
  im = img;
  polylines = trace_skeleton(0, 0, W, H, 0, csize, maxIter);
}

/* Drain the current polyline into a caller-supplied buffer in one call, so
 * Python does not pay a ctypes round trip per point. Returns point count, or
 * -1 when no polylines remain. */
int pop_polyline(int *out, int cap) {
  if (!polylines) {
    return -1;
  }
  int n = 0;
  point_t *p = polylines->head;
  while (p && n < cap) {
    out[2 * n] = p->x;
    out[2 * n + 1] = p->y;
    point_t *next = p->next;
    free(p);
    p = next;
    n++;
  }
  polyline_t *q = polylines->next;
  if (q) {
    q->prev = NULL;
  }
  free(polylines);
  polylines = q;
  return n;
}
