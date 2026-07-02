# Handoff: Python Filled-SVG to Stroked-Line SVG Converter

## Purpose

This project converts SVG drawings where the visible “lines” are actually filled ribbon-like shapes into SVG drawings made from real stroked paths.

The original input SVG generally looks visually like a line drawing, but internally it contains filled shapes such as:

```xml
<path fill="#62A2E9" d="M ... Z" />
```

The desired output is an SVG that uses paths like:

```xml
<path d="M ... L ..." stroke="#62A2E9" stroke-width="12.4" fill="none" />
```

The output is useful when the downstream drawing system expects actual line paths with stroke weight, rather than filled blobs. This is especially relevant for children’s drawing apps, animation workflows, line-editing tools, SVG simplification, or any system that needs to treat drawn marks as strokes.

## Current Script

The working Python script is named:

```bash
convert_filled_svg_to_stroked_lines.py
```

The script was built for SVGs generated from simple digital line drawings, where each stroke has been converted by the generator into a filled outline/ribbon. It is not a general-purpose SVG semantic converter. Instead, it performs a raster-based centerline reconstruction.

## Recommended Usage

Install dependencies:

```bash
pip install cairosvg pillow numpy scikit-image opencv-python
```

Run the converter:

```bash
python convert_filled_svg_to_stroked_lines.py large-image-drawing.svg \
  --output large-image-drawing-lines.svg
```

The default settings were the ones used to produce the cleaner earlier output:

```bash
python convert_filled_svg_to_stroked_lines.py large-image-drawing.svg \
  --output large-image-drawing-lines.svg
```

## Why This Approach Was Chosen

### The core problem

The input SVG only looks like a stroked drawing. Its geometry is not actually represented as centerlines plus stroke widths. Instead, each line is already expanded into an enclosed filled shape. Once a stroke is expanded to an outline, the original centerline path is lost.

For example, a simple line drawn by a user might originally be:

```xml
<path d="M 10 10 L 100 100" stroke="#EC534E" stroke-width="12" fill="none" />
```

But the generated SVG may represent the same line as a closed polygon/ribbon:

```xml
<path d="M 5 14 C ... L 95 106 C ... Z" fill="#EC534E" />
```

There is no direct, reliable way to recover the original path from the filled outline using only SVG path commands. The script must infer the centerline.

### Why not parse the SVG paths directly?

A direct vector approach would require understanding each filled outline as the boundary of an expanded stroke, then computing its medial axis in vector space. That is possible in theory, but difficult in practice because generated SVGs may contain:

- Bezier-heavy outlines
- Irregular stroke widths
- Self-overlaps
- Closed blobs
- Anti-aliased color edges
- Multiple colors
- Filled loops or shapes that are visually intended as lines
- Non-uniform path construction from the generator

A vector-native solution would require robust computational geometry libraries and many special cases.

### Why rasterize first?

Rasterizing turns the problem into an image-processing problem:

1. Render the SVG to pixels.
2. Find the colored regions.
3. Reduce each region to its 1-pixel centerline.
4. Trace those centerlines back into SVG paths.
5. Estimate stroke width from the original filled region thickness.

This is more robust for generated artwork because the visual output is what matters. The script reconstructs the strokes from the rendered appearance rather than from the generator’s internal path structure.

## High-Level Pipeline

The script performs these steps:

1. Read the input SVG.
2. Extract the SVG `viewBox`.
3. Extract explicit hex fill colors.
4. Rasterize the SVG to an RGBA image at native viewBox dimensions.
5. Determine which pixels are visible using an alpha threshold.
6. Assign each visible pixel to the closest original fill color.
7. Process each color independently.
8. Clean each color mask with morphological operations.
9. Skeletonize the mask into a 1-pixel centerline.
10. Estimate stroke width from the distance between centerline pixels and the region edge.
11. Trace the skeleton pixels into ordered point chains.
12. Simplify point chains with OpenCV’s Douglas-Peucker algorithm.
13. Emit a new SVG containing only stroked paths with `fill="none"`.

## Detailed Walkthrough

### 1. Reading the SVG and viewBox

The script expects the SVG to contain a `viewBox`:

```xml
<svg viewBox="0 0 1024 1024">
```

The viewBox determines the output coordinate system and the rasterization size. The script intentionally rasterizes at the same dimensions as the viewBox so that raster pixel coordinates map directly back to SVG coordinates.

Relevant function:

```python
def read_viewbox(svg_text: str) -> tuple[int, int, int, int]
```

It returns:

```python
(x, y, width, height)
```

The current output writer assumes a `0 0 width height` viewBox. If non-zero viewBox origins matter in future use cases, the output writer should preserve the original `x` and `y` values.

### 2. Extracting fill colors

The script currently extracts explicit six-digit hex colors from `fill` attributes:

```python
colors = sorted(set(re.findall(r'fill="(#[0-9a-fA-F]{6})"', svg_text)))
```

This is enough for the current generated SVG because the source paths use direct hex fills.

Limitations:

- Does not detect three-digit hex colors such as `#fff`.
- Does not detect `rgb(...)` or `rgba(...)`.
- Does not detect named colors.
- Does not fully parse CSS classes or inherited styles.
- Does not inspect gradients.

Future extensions can improve color parsing.

### 3. Rasterizing the SVG

The script uses CairoSVG to render the input SVG into a temporary PNG:

```python
cairosvg.svg2png(
    url=str(svg_path),
    write_to=str(tmp_path),
    output_width=width,
    output_height=height,
    background_color=None,
)
```

Then Pillow loads it as RGBA:

```python
np.array(Image.open(tmp_path).convert("RGBA"))
```

The output image is a NumPy array with shape:

```python
(height, width, 4)
```

The channels are red, green, blue, and alpha.

### 4. Visible pixel detection

The script treats a pixel as visible when its alpha is above the threshold:

```python
visible_mask = alpha > alpha_threshold
```

Default:

```bash
--alpha-threshold 48
```

This removes mostly-transparent anti-aliasing artifacts while keeping real edge pixels.

Lowering the threshold includes more faint edge pixels. Raising it makes masks thinner and may increase breaks.

### 5. Assigning pixels to source colors

Anti-aliasing creates edge pixels that are not exactly equal to the source fill color. For example, a red stroke on transparent background may render edge pixels as semi-transparent or blended red values.

To handle this, the script assigns every visible pixel to the closest original fill color by squared RGB distance:

```python
color_distance = ((rgb[..., None, :] - palette[None, None, :, :]) ** 2).sum(axis=-1)
nearest_color_index = color_distance.argmin(axis=-1)
```

This gives each color a clean binary mask.

Why color-by-color processing matters:

- Each original drawing color should remain separate.
- Overlapping or adjacent colors should not merge into one skeleton.
- Stroke width can be estimated per color.
- Output paths preserve the original visual palette.

### 6. Morphological cleanup

For each color, the script creates a binary mask:

```python
color_mask = visible_mask & (nearest_color_index == color_index)
```

It then applies two cleanup steps:

```python
color_mask = closing(color_mask, disk(1))
color_mask = remove_small_objects(color_mask, min_size=min_object_size)
```

#### Closing

Morphological closing fills tiny gaps and smooths small holes. This is helpful because anti-aliasing and color assignment can create small breaks in what should be a continuous stroke.

The default structuring element is:

```python
disk(1)
```

This is intentionally conservative. A larger disk may join nearby unrelated marks.

#### Small object removal

Small isolated color blobs are discarded:

```bash
--min-object-size 20
```

This removes noise and tiny artifacts that would otherwise become tiny output path fragments.

### 7. Skeletonization

The key operation is skeletonization:

```python
skeleton = skeletonize(color_mask)
```

This uses `skimage.morphology.skeletonize` to reduce each filled region to a 1-pixel-wide medial centerline.

Conceptually:

- A thick filled ribbon becomes a thin centerline.
- A circle-like filled ring becomes a loop centerline.
- A filled blob becomes a skeleton graph.

This is the step that recovers the approximate original “drawn line.”

The result is still a raster image: a binary array where `True` pixels are centerline pixels.

### 8. Stroke width estimation

To convert the skeleton back into a stroked SVG, the script needs a stroke width.

It estimates thickness using OpenCV’s distance transform:

```python
distance_to_edge = cv2.distanceTransform(color_mask.astype(np.uint8), cv2.DIST_L2, 5)
skeleton_distances = distance_to_edge[skeleton]
stroke_width = median(skeleton_distances) * 2
```

The distance transform computes how far each foreground pixel is from the nearest background pixel. At the skeleton, that distance approximates the stroke radius. Multiplying by 2 gives a stroke width.

The result is clamped:

```python
stroke_width = max(min_stroke_width, min(max_stroke_width, stroke_width))
```

Defaults:

```bash
--min-stroke-width 6
--max-stroke-width 18
```

This prevents outlier blobs or loops from producing absurdly thin or thick strokes.

### 9. Skeleton tracing

Skeletonization gives pixels, but SVG needs ordered paths.

The script traces the skeleton graph into chains of connected pixels.

Relevant function:

```python
def trace_skeleton_paths(skeleton: np.ndarray) -> list[list[tuple[int, int]]]
```

The algorithm:

1. Find all skeleton pixels.
2. Compute each pixel’s 8-neighbor degree.
3. Treat pixels with degree not equal to 2 as graph nodes.
   - Degree 1: endpoint.
   - Degree 3+: branch point.
   - Degree 0: isolated point.
4. Walk from node to node through degree-2 pixels.
5. Record each walk as one path.
6. Separately handle closed loops where every pixel has degree 2.

Coordinates are stored internally as `(y, x)` because NumPy arrays are row-major. They are converted to SVG `(x, y)` before output.

### 10. Path simplification

Raw traced skeleton paths can contain hundreds or thousands of pixel-by-pixel points. The script simplifies them with OpenCV’s `approxPolyDP`:

```python
approx = cv2.approxPolyDP(contour, epsilon, closed)
```

Default:

```bash
--simplify-epsilon 2.2
```

Lower values preserve more detail but produce larger SVGs. Higher values create simpler paths but can make curves too angular or distort the drawing.

The script emits only `M`, `L`, and `Z` path commands. It does not currently fit Bezier curves.

### 11. Path filtering

The script skips very short paths:

```python
if len(path) < 8:
    continue

if len(points) < 2 or path_length(points) < min_path_length:
    continue
```

Default:

```bash
--min-path-length 15
```

This reduces specks and fragments.

### 12. Output SVG generation

The output SVG contains a group with shared stroke styling:

```xml
<g fill="none" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke">
```

Each traced path is emitted as:

```xml
<path d="..." stroke="#AB71E1" stroke-width="12.4"/>
```

Important styling choices:

- `fill="none"`: ensures these are real stroked paths, not filled shapes.
- `stroke-linecap="round"`: makes endpoints look like natural drawn strokes.
- `stroke-linejoin="round"`: softens corners after simplification.
- `vector-effect="non-scaling-stroke"`: preserves stroke width during SVG scaling.

## Current CLI Options

```bash
python convert_filled_svg_to_stroked_lines.py input.svg \
  --output output.svg \
  --alpha-threshold 48 \
  --min-object-size 20 \
  --min-path-length 15 \
  --simplify-epsilon 2.2 \
  --min-stroke-width 6 \
  --max-stroke-width 18
```

### `--alpha-threshold`

Visible-pixel cutoff. Pixels with alpha less than or equal to this value are ignored.

Increase when:

- The output includes too much edge noise.
- There are faint artifacts.

Decrease when:

- Strokes become broken.
- Thin or anti-aliased regions disappear.

### `--min-object-size`

Removes isolated blobs smaller than this many pixels.

Increase when:

- Output has many tiny junk paths.

Decrease when:

- Small intentional marks disappear.

### `--min-path-length`

Removes traced paths shorter than this length in SVG units.

Increase when:

- Output has many tiny fragments.

Decrease when:

- Small intentional details are missing.

### `--simplify-epsilon`

Controls Douglas-Peucker simplification.

Increase when:

- Output has too many points.
- File size is too large.
- Curves can be more approximate.

Decrease when:

- Curves look too angular.
- Important detail is lost.

### `--min-stroke-width` and `--max-stroke-width`

Clamp emitted stroke widths.

Increase `--min-stroke-width` when:

- Output lines are too thin.
- Broken fragments should visually connect more easily.

Increase `--max-stroke-width` when:

- Original strokes are very thick and are being capped too aggressively.

## Known Limitations

### The script is visual, not semantic

It reconstructs from the rendered image, not from original drawing intent. It cannot know the exact original stroke path if the generated SVG has already expanded it into a filled outline.

### Branches can create splits

Skeletons are graphs, not always simple paths. When strokes overlap or touch, skeletonization creates branch points. The tracer splits paths at those branch points.

This can be acceptable visually, because round caps and joins often make adjacent paths look continuous. But it can matter if the downstream system expects one path per original user stroke.

### Output uses line segments, not Bezier curves

The simplified output paths use `M`, `L`, and sometimes `Z`. Curves are approximated by polylines. This is usually fine for simple drawing-app output, but it is not as elegant as fitted cubic Bezier paths.

### Color parsing is narrow

Only explicit six-digit hex fills are handled. More robust parsing is needed for SVGs using CSS classes, inherited styles, `style` attributes, named colors, or gradients.

### Stroke width is per color, not per path

The current script estimates one stroke width per color layer. If a single color contains both thin and thick strokes, the emitted width may be a compromise.

This can be improved by estimating width per traced path.

### Filled shapes that are not intended as strokes may become skeletons

If the SVG contains a filled circle, square, or decorative area, the script will try to skeletonize it. That may produce unwanted internal centerlines.

The script works best when all filled shapes are actually expanded strokes.

### Raster resolution affects quality

The script rasterizes at native viewBox size. If the viewBox is small, skeletons may be jagged or lossy. If it is very large, processing may be slower.

A future version could support oversampling.

## Troubleshooting

### Output is patchy or broken

Try:

```bash
python convert_filled_svg_to_stroked_lines.py input.svg \
  --output output.svg \
  --alpha-threshold 24 \
  --min-object-size 8 \
  --min-path-length 6 \
  --simplify-epsilon 1.4 \
  --min-stroke-width 8 \
  --max-stroke-width 22
```

Why this helps:

- Lower alpha threshold keeps more edge pixels.
- Lower minimum object/path thresholds preserve small segments.
- Lower simplification keeps more detail.
- Higher minimum stroke width helps visually bridge small breaks.

### Output has too many tiny artifacts

Try:

```bash
python convert_filled_svg_to_stroked_lines.py input.svg \
  --output output.svg \
  --alpha-threshold 64 \
  --min-object-size 50 \
  --min-path-length 25
```

### Curves are too angular

Try:

```bash
--simplify-epsilon 1.0
```

### Output SVG is too large

Try:

```bash
--simplify-epsilon 3.5
--min-path-length 25
```

### Lines are too thick or too thin

Adjust:

```bash
--min-stroke-width 4
--max-stroke-width 24
```

## Suggestions for Project Structure

For a standalone maintained project, use a layout like:

```text
filled-svg-to-stroked-lines/
  README.md
  pyproject.toml
  src/
    filled_svg_to_stroked_lines/
      __init__.py
      cli.py
      convert.py
      colors.py
      rasterize.py
      skeleton.py
      trace.py
      svg_write.py
  tests/
    fixtures/
      dinosaur-filled.svg
      dinosaur-expected.svg
    test_colors.py
    test_viewbox.py
    test_trace.py
    test_cli.py
  examples/
    input.svg
    output.svg
  docs/
    algorithm.md
    tuning.md
```

Recommended module responsibilities:

- `cli.py`: argparse entry point.
- `convert.py`: orchestrates the pipeline.
- `colors.py`: color extraction and nearest-color assignment.
- `rasterize.py`: CairoSVG/Pillow rendering.
- `skeleton.py`: mask cleanup, skeletonization, distance transform.
- `trace.py`: skeleton graph tracing and path simplification.
- `svg_write.py`: output SVG formatting.

## Suggested `pyproject.toml`

```toml
[project]
name = "filled-svg-to-stroked-lines"
version = "0.1.0"
description = "Convert filled-ribbon SVG line art into stroked SVG paths"
requires-python = ">=3.10"
dependencies = [
  "cairosvg",
  "pillow",
  "numpy",
  "scikit-image",
  "opencv-python",
]

[project.scripts]
filled-svg-to-stroked-lines = "filled_svg_to_stroked_lines.cli:main"
```

Then usage becomes:

```bash
filled-svg-to-stroked-lines input.svg --output output.svg
```

## Testing Strategy

### Unit tests

Test small pure functions:

- `read_viewbox`
- `extract_fill_colors`
- `hex_to_rgb`
- `path_length`
- `svg_path_d`
- skeleton graph tracing on hand-built masks

### Fixture tests

Keep a few representative input SVGs and compare the output structurally.

Avoid exact full-file snapshot comparisons if path ordering or simplification changes often. Instead assert properties:

- Output parses as SVG.
- Output contains no filled paths except `fill="none"`.
- Output contains expected colors.
- Output has nonzero path count.
- Output path count is within a reasonable range.
- Stroke widths are within expected min/max.
- Output rendered image is visually close to the original.

### Visual regression tests

For best results, render both input and output to PNG and compare:

- Pixel difference
- Structural similarity
- Alpha coverage
- Per-color overlap

A practical CI check could allow some tolerance rather than requiring exact pixel equality.

## Extension Ideas

### 1. Better color parsing

Support:

- `fill="#fff"`
- `fill="rgb(255, 0, 0)"`
- `style="fill:#EC534E"`
- CSS classes in `<style>` blocks
- inherited fill from parent groups

Potential libraries:

- `tinycss2`
- `cssselect2`
- `lxml`

### 2. Oversampling

Rasterize at 2x or 4x resolution, skeletonize at high resolution, then scale coordinates back down.

Potential benefits:

- Smoother centerlines.
- Fewer diagonal artifacts.
- Better handling of thin shapes.

Potential costs:

- Slower processing.
- More memory use.
- Need to adjust thresholds and stroke-width estimation.

CLI idea:

```bash
--scale 2
```

### 3. Per-path stroke width

Currently stroke width is estimated per color. A better approach is:

1. Trace each path.
2. Sample distance-transform values along that path.
3. Use median distance for that specific path.
4. Emit path-specific stroke width.

This would better support drawings that mix thin and thick lines of the same color.

### 4. Fragment joining

If skeleton tracing creates too many broken paths, add a post-processing stage that merges path fragments when:

- They are the same color.
- Their endpoints are close.
- Their tangent directions are compatible.
- Joining them would not cross another color or large blank region.

This could reduce patchiness in difficult generated SVGs.

### 5. Bezier curve fitting

Instead of outputting polylines, fit cubic Bezier curves to simplified point chains.

Potential benefits:

- Smaller SVGs.
- Smoother paths.
- More natural vector output.

Possible approaches:

- Use a Python Bezier fitting implementation.
- Use Potrace-style curve fitting.
- Fit splines with SciPy, then convert to cubic Beziers.

### 6. Preserve metadata and dimensions

The current output writes a simple fresh SVG. A production version might preserve:

- Original `width` and `height`
- Original non-zero viewBox origin
- `<title>` and `<desc>`
- Accessibility attributes
- Metadata
- Layer/group names

### 7. Debug outputs

Add optional debug files:

```bash
--debug-dir debug/
```

Possible debug artifacts:

- Rendered input PNG
- Per-color masks
- Cleaned masks
- Skeleton images
- Traced path overlay
- Final output preview PNG

This would make tuning much easier.

### 8. Library API

Expose a Python API in addition to the CLI:

```python
from filled_svg_to_stroked_lines import convert_svg

convert_svg("input.svg", "output.svg")
```

This would allow integration into a larger image pipeline.

### 9. Batch mode

Support converting many SVGs at once:

```bash
filled-svg-to-stroked-lines ./input-dir --output-dir ./output-dir
```

Useful for processing many generated drawings.

### 10. Browser or Node version

A Node/browser version is possible but harder to match the Python quality unless equivalent image-processing primitives are used. The earlier Node port used hand-rolled skeletonization and tracing and produced patchier output on some inputs.

For production parity, a Node version should probably call:

- A WebAssembly skeletonization library, or
- OpenCV.js, or
- A Python worker/service, or
- A native image-processing binary.

The Python version is currently the better reference implementation.

## Recommended Maintenance Priorities

1. Package the Python script as a real CLI project.
2. Add fixture-based tests for the current dinosaur/sample SVG.
3. Add debug-output mode.
4. Improve color parsing.
5. Add per-path stroke width estimation.
6. Add optional oversampling.
7. Add path-fragment joining only if patchiness remains a frequent problem.
8. Add visual regression tests.
9. Consider Bezier fitting after correctness is stable.

## Practical Notes

### Why Python is preferred for the reference implementation

The Python ecosystem provides high-quality, mature libraries for the exact operations needed:

- CairoSVG for SVG rasterization
- Pillow for image loading
- NumPy for array operations
- scikit-image for skeletonization and morphology
- OpenCV for distance transforms and path simplification

The Node version can be made to work, but matching `skimage.skeletonize`, OpenCV distance transforms, and OpenCV contour simplification reliably requires either complex custom code or additional native/WASM dependencies.

### What “success” means

The goal is not to perfectly recover the original pre-expanded drawing data. That information is gone. The goal is to produce a clean, visually similar SVG made only from stroked paths.

A successful output should:

- Visually resemble the input.
- Use no filled shape paths for the drawing marks.
- Preserve the original colors.
- Have reasonable stroke widths.
- Avoid excessive tiny fragments.
- Be editable as line paths in downstream tools.

### When not to use this script

This script is not ideal for:

- Complex illustrations with large filled areas.
- SVGs with gradients, shadows, textures, or transparency effects.
- Text converted to outlines.
- Icons where filled shapes are semantically important.
- Drawings where exact original stroke order is required.

## Reference Command for Current Known-Good Output

```bash
pip install cairosvg pillow numpy scikit-image opencv-python

python convert_filled_svg_to_stroked_lines.py large-image-drawing.svg \
  --output large-image-drawing-lines.svg
```

This was the command used for the clean output discussed in the original conversation.

## Appendix: Full Reference Script

```python
#!/usr/bin/env python3
"""
Convert a filled-shape SVG line drawing into a stroked-line SVG.

This is designed for SVGs like AI-generated coloring/line drawings where each
visible “line” is actually a filled ribbon shape. The script rasterizes the SVG,
segments colored pixels by fill color, skeletonizes each colored region to a
1-pixel centerline, traces those centerlines into SVG paths, and writes a new
SVG whose paths use stroke/stroke-width with fill="none".

Example:
    python convert_filled_svg_to_stroked_lines.py large-image-drawing.svg \
        --output large-image-drawing-lines.svg

Install dependencies:
    pip install cairosvg pillow numpy scikit-image opencv-python
"""

from __future__ import annotations

import argparse
import math
import re
import tempfile
import warnings
from pathlib import Path

import cairosvg
import cv2
import numpy as np
from PIL import Image
from skimage.morphology import closing, disk, remove_small_objects, skeletonize

SVG_NS = "http://www.w3.org/2000/svg"
NEIGHBORS_8 = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]


def read_viewbox(svg_text: str) -> tuple[int, int, int, int]:
    match = re.search(r'viewBox="([^"]+)"', svg_text)
    if not match:
        raise ValueError("Input SVG must have a viewBox.")
    values = [float(v) for v in re.split(r"[\s,]+", match.group(1).strip())]
    if len(values) != 4:
        raise ValueError(f"Expected four viewBox values, got: {match.group(1)!r}")
    x, y, width, height = values
    return int(round(x)), int(round(y)), int(round(width)), int(round(height))


def extract_fill_colors(svg_text: str) -> list[str]:
    """Return explicit hex fill colors used by filled paths/shapes."""
    colors = sorted(set(re.findall(r'fill="(#[0-9a-fA-F]{6})"', svg_text)))
    if not colors:
        raise ValueError("No explicit hex fill colors found. This script expects filled line-shape SVGs.")
    return colors


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def render_svg_to_rgba(svg_path: Path, width: int, height: int) -> np.ndarray:
    """Rasterize at native viewBox size so pixel coordinates match SVG coordinates."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        cairosvg.svg2png(
            url=str(svg_path),
            write_to=str(tmp_path),
            output_width=width,
            output_height=height,
            background_color=None,
        )
        return np.array(Image.open(tmp_path).convert("RGBA"))
    finally:
        tmp_path.unlink(missing_ok=True)


def degree(skeleton: np.ndarray, y: int, x: int) -> int:
    h, w = skeleton.shape
    count = 0
    for dy, dx in NEIGHBORS_8:
        yy, xx = y + dy, x + dx
        if 0 <= yy < h and 0 <= xx < w and skeleton[yy, xx]:
            count += 1
    return count


def trace_skeleton_paths(skeleton: np.ndarray) -> list[list[tuple[int, int]]]:
    """
    Convert a 1-pixel skeleton image into ordered pixel chains.

    Coordinates are stored internally as (y, x). They are converted to SVG
    (x, y) when the path data is emitted.
    """
    h, w = skeleton.shape
    skeleton_points = np.argwhere(skeleton)
    if len(skeleton_points) == 0:
        return []

    deg = np.zeros(skeleton.shape, dtype=np.uint8)
    for y, x in skeleton_points:
        deg[y, x] = degree(skeleton, int(y), int(x))

    nodes = set(map(tuple, np.argwhere(skeleton & (deg != 2))))
    visited_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    paths: list[list[tuple[int, int]]] = []

    def edge_key(a: tuple[int, int], b: tuple[int, int]):
        return tuple(sorted((a, b)))

    def skel_neighbors(p: tuple[int, int]) -> list[tuple[int, int]]:
        y, x = p
        output = []
        for dy, dx in NEIGHBORS_8:
            q = (y + dy, x + dx)
            if 0 <= q[0] < h and 0 <= q[1] < w and skeleton[q]:
                output.append(q)
        return output

    for node in list(nodes):
        for neighbor in skel_neighbors(node):
            key = edge_key(node, neighbor)
            if key in visited_edges:
                continue
            path = [node, neighbor]
            visited_edges.add(key)
            previous, current = node, neighbor
            while current not in nodes:
                next_pixels = [q for q in skel_neighbors(current) if q != previous]
                if not next_pixels:
                    break
                nxt = next_pixels[0]
                visited_edges.add(edge_key(current, nxt))
                path.append(nxt)
                previous, current = current, nxt
            paths.append(path)

    remaining_edges = []
    for y, x in skeleton_points:
        p = (int(y), int(x))
        for q in skel_neighbors(p):
            if edge_key(p, q) not in visited_edges:
                remaining_edges.append((p, q))

    while remaining_edges:
        start, neighbor = remaining_edges.pop()
        if edge_key(start, neighbor) in visited_edges:
            continue
        path = [start, neighbor]
        visited_edges.add(edge_key(start, neighbor))
        previous, current = start, neighbor
        guard = 0
        while current != start and guard < 100000:
            guard += 1
            next_pixels = [q for q in skel_neighbors(current) if q != previous]
            if not next_pixels:
                break
            nxt = next_pixels[0]
            if edge_key(current, nxt) in visited_edges and nxt != start:
                break
            visited_edges.add(edge_key(current, nxt))
            path.append(nxt)
            previous, current = current, nxt
        if len(path) > 2:
            paths.append(path)

    return paths


def simplify_path(path: list[tuple[int, int]], epsilon: float) -> tuple[list[tuple[float, float]], bool]:
    """Simplify the pixel chain with Douglas-Peucker and return SVG x/y points."""
    contour = np.array([[p[1], p[0]] for p in path], dtype=np.float32).reshape((-1, 1, 2))
    closed = False
    if len(path) > 3:
        dx = path[0][1] - path[-1][1]
        dy = path[0][0] - path[-1][0]
        closed = (dx * dx + dy * dy) <= 4

    approx = cv2.approxPolyDP(contour, epsilon, closed)
    points = [(float(point[0][0]), float(point[0][1])) for point in approx]
    if closed and points and points[0] != points[-1]:
        points.append(points[0])
    return points, closed


def path_length(points: list[tuple[float, float]]) -> float:
    return sum(
        math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
        for i in range(1, len(points))
    )


def format_number(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def svg_path_d(points: list[tuple[float, float]], closed: bool) -> str:
    if not points:
        return ""
    parts = [f"M {format_number(points[0][0])} {format_number(points[0][1])}"]
    for x, y in points[1:]:
        parts.append(f"L {format_number(x)} {format_number(y)}")
    if closed:
        parts.append("Z")
    return " ".join(parts)


def convert_svg(
    input_svg: Path,
    output_svg: Path,
    alpha_threshold: int = 48,
    min_object_size: int = 20,
    min_path_length: float = 15,
    simplify_epsilon: float = 2.2,
    min_stroke_width: float = 6.0,
    max_stroke_width: float = 18.0,
) -> None:
    svg_text = input_svg.read_text(encoding="utf-8")
    _, _, width, height = read_viewbox(svg_text)
    colors = extract_fill_colors(svg_text)
    color_rgb = {color: hex_to_rgb(color) for color in colors}

    rgba = render_svg_to_rgba(input_svg, width, height)
    alpha = rgba[..., 3]
    rgb = rgba[..., :3].astype(np.int16)

    visible_mask = alpha > alpha_threshold

    palette = np.array([color_rgb[color] for color in colors], dtype=np.int16)
    color_distance = ((rgb[..., None, :] - palette[None, None, :, :]) ** 2).sum(axis=-1)
    nearest_color_index = color_distance.argmin(axis=-1)

    output_paths: list[tuple[str, float, str]] = []

    for color_index, color in enumerate(colors):
        color_mask = visible_mask & (nearest_color_index == color_index)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            color_mask = closing(color_mask, disk(1))
            color_mask = remove_small_objects(color_mask, min_size=min_object_size)

        skeleton = skeletonize(color_mask)

        distance_to_edge = cv2.distanceTransform(color_mask.astype(np.uint8), cv2.DIST_L2, 5)
        skeleton_distances = distance_to_edge[skeleton]
        stroke_width = float(np.median(skeleton_distances) * 2) if skeleton_distances.size else 8.0
        stroke_width = max(min_stroke_width, min(max_stroke_width, stroke_width))

        for path in trace_skeleton_paths(skeleton):
            if len(path) < 8:
                continue

            points, closed = simplify_path(path, simplify_epsilon)

            if len(points) < 2 or path_length(points) < min_path_length:
                continue

            d = svg_path_d(points, closed=closed)
            output_paths.append((color, stroke_width, d))

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="{SVG_NS}" version="1.1" viewBox="0 0 {width} {height}">',
        '  <g fill="none" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke">',
    ]

    for color, stroke_width, d in output_paths:
        lines.append(f'    <path d="{d}" stroke="{color}" stroke-width="{stroke_width:.1f}"/>')

    lines.extend([
        '  </g>',
        '</svg>',
    ])

    output_svg.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert filled-ribbon SVG line art into fill=none stroked SVG paths.")
    parser.add_argument("input", type=Path, help="Input SVG whose apparent lines are filled shapes.")
    parser.add_argument("--output", "-o", type=Path, help="Output SVG path. Defaults to <input>-lines.svg.")
    parser.add_argument("--alpha-threshold", type=int, default=48, help="Visible-pixel alpha cutoff. Default: 48.")
    parser.add_argument("--min-object-size", type=int, default=20, help="Remove color blobs smaller than this many pixels. Default: 20.")
    parser.add_argument("--min-path-length", type=float, default=15, help="Discard traced paths shorter than this. Default: 15.")
    parser.add_argument("--simplify-epsilon", type=float, default=2.2, help="Douglas-Peucker simplification amount. Lower preserves more detail. Default: 2.2.")
    parser.add_argument("--min-stroke-width", type=float, default=6.0, help="Minimum emitted stroke width. Default: 6.")
    parser.add_argument("--max-stroke-width", type=float, default=18.0, help="Maximum emitted stroke width. Default: 18.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_svg = args.input
    output_svg = args.output or input_svg.with_name(f"{input_svg.stem}-lines.svg")

    convert_svg(
        input_svg=input_svg,
        output_svg=output_svg,
        alpha_threshold=args.alpha_threshold,
        min_object_size=args.min_object_size,
        min_path_length=args.min_path_length,
        simplify_epsilon=args.simplify_epsilon,
        min_stroke_width=args.min_stroke_width,
        max_stroke_width=args.max_stroke_width,
    )

    print(f"Wrote {output_svg}")


if __name__ == "__main__":
    main()
```
