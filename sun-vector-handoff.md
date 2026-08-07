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

## Sample

`inputs/sun-square.svg` is a pure-polyline outline, so it is already an exact polygon
and does not introduce bezier/arc flattening error. Its generated result is
`outputs/sun-square.svg`.

## Tradeoff vs the raster pipeline

- Raster on the sun: ~4.2% differing pixels but **blunt tips** (the complaint).
- Vector on the sun: ~6.3% but **sharp tips**.

The vector output costs a couple points of pixel-diff (thin-hatching edge
penalty + the reconstructed snake reads slightly busier, since it exposes the
true single continuous stroke) while fixing the perceptual defect the raster
cannot. The sample output is therefore generated with the vector engine.

## Usage

```bash
DYLD_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python sun_vectorize.py \
    inputs/sun-square.svg --output outputs/sun-square.svg
# deps: numpy scipy shapely  (shapely was pip-installed into .venv)
```

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
