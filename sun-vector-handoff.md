# Sun scribble: vector sharp-tip reconstruction

## Problem this solves

The raster skeleton pipeline (`convert_filled_svg_to_stroked_lines.py`) blunts
sharp zigzag tips. At a hairpin fold, the medial axis of the outlined stroke
pulls back from the true point, and skeletonization + round caps render the
fold as a rounded blob instead of a sharp point:

```
\           \
 \           \
  --   vs.    \      (raster = blunt,  wanted = sharp)
 /            /
/            /
```

See `debug/sun/tip3way.png` (input | raster | vector) for the exact defect.

## Approach

`sun_vectorize.py` reconstructs the pen centerline **in vector space** from the
filled outline's path data (no rasterization), using a triangulation
(chordal-axis) medial axis. Terminal triangles of the triangulated ribbon
point straight into the outline's sharp corners, so the fold tips are recovered
as sharp vertices instead of being rounded away.

Pipeline (scribble = path 1, one closed outline of a single pen stroke):

1. Flatten the outline path to a polygon (`flatten_path` handles L/Q/C/A/Z).
2. Resample the polygon boundary uniformly (~2 px).
3. Delaunay-triangulate; keep triangles inside the polygon.
4. Classify each triangle by boundary-edge count: terminal (2) → segment to the
   sharp corner; sleeve (1) → segment between the two internal midpoints;
   junction (0) → segments from centroid to each midpoint.
5. Build a graph, prune tip-fork spurs, then **contract fold clusters**:
   nodes joined by short fork/bridge edges collapse to one sharp fold-vertex
   (the outermost corner in the cluster, backed off by one stroke radius so a
   rendered round join lands exactly on the outline corner).
6. Trace the snake through the fold-vertices; render as `fill="none"` strokes.

The outer ring (path 0) is reconstructed as its actual wavy mid-loop between the
two edge loops (`ring_centerline`), which matches the hand-drawn ring far better
than a fitted circle.

## The five input variants

`inputs/sun-*.svg` are the same drawing with different outline primitives:

| file | path commands | vector metric* |
|------|---------------|----------------|
| sun-1 | arcs + cubics + quadratics (A/C/Q) | 7.38% |
| sun-2, sun-3 | cubics + quadratics (C/Q) | 6.70% |
| sun-4 | quadratic-dominant (Q) | 6.78% |
| sun-5 | **pure polylines (L)** | **6.26%** |

\* differing pixels vs input at 1200px; lower is better.

**Recommendation: sun-5 (pure polylines) is the strongest starting point.** It
is already an exact polygon, so there is no bezier/arc flattening approximation,
and it scores best. All variants work through the flattener; sun-1's arcs incur
the most flattening error. (Note: the raster pipeline is blind to this
distinction — it rasterizes first, so all five collapse to identical pixels.)

## Tradeoff vs the raster pipeline

- Raster on the sun: ~4.2% differing pixels but **blunt tips** (the complaint).
- Vector on the sun: ~6.3% but **sharp tips**.

The vector output costs a couple points of pixel-diff (thin-hatching edge
penalty + the reconstructed snake reads slightly busier, since it exposes the
true single continuous stroke) while fixing the perceptual defect the raster
cannot. For the sun family the sharp tips are the point, so `outputs/sun-*.svg`
were generated with the vector engine.

## Usage

```bash
DYLD_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python sun_vectorize.py \
    inputs/sun-5.svg --output outputs/sun-5.svg
# deps: numpy scipy shapely  (shapely was pip-installed into .venv)
```

## Prototype trail (debug/sun/)

- `chordal.py` / `chordal2.py` / `chordal3.py` — incremental prototypes;
  superseded by the consolidated top-level `sun_vectorize.py`.
- `chordal-overlay.png` — outline + recovered axis + detected tip corners.
- `tip3way.png` — input vs raster vs vector at one fold.
- `montage.png` — input vs vector output for all five variants.

## Not done yet / next steps

1. **Integration.** The engine is standalone and assumes the sun's 2-path
   structure (ring + scribble). To fold into the main converter it needs
   per-element dispatch: use the vector medial axis for scribble-like filled
   outlines, keep the raster path for the rest.
2. **Coverage.** Teeth are a touch thin/short in places (the ~6% residual);
   per-path width or extending teeth fully into folds before the radius
   back-off would tighten it.
3. **Generalize** the ring assumption (currently fits the two edge loops of a
   roughly circular band).
