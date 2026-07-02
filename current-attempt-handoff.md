# Current Attempt Handoff: Filled SVG to Stroked Lines

## Goal

Convert SVG drawings that visually look like pen/marker line art but are internally represented as filled shapes into SVGs made from real stroked paths:

```xml
<path d="..." fill="none" stroke="#..." stroke-width="..." />
```

The working examples are:

- `inputs/dinosaur.svg`
- `inputs/landscape.svg`

The final outputs currently live at:

- `outputs/dinosaur.svg`
- `outputs/landscape.svg`

Per the project convention, intermediate files and visual comparisons should stay under `debug/`. The only files intended to land in `outputs/` are final produced SVGs.

## Biggest Gap

The hard unresolved problem is reconstructing the original drawing gesture at stroke vertices and overlaps from filled outlines.

The input SVG has already discarded the original stroke centerlines, stroke order, pressure model, cap geometry, and join semantics. It only preserves the final filled regions. At places where a drawn stroke turns sharply, doubles back, or overlaps itself, multiple centerline explanations can produce nearly the same filled pixels. A human tracing by hand can infer the natural drawing motion, but the current automated pipeline often collapses the local geometry too early toward the vertex and then emits a short straight protruding segment. Pixel percentages can look good while these defects remain visually obvious.

This is the central gap: the converter is good at matching raster coverage, but it does not yet reliably infer natural stroke topology through ambiguous junctions, acute turns, and overlapping same-stroke segments.

## Current Best Implementation

The best current implementation is the Python converter:

```text
convert_filled_svg_to_stroked_lines.py
```

It uses a raster-first pipeline:

1. Parse the SVG and preserve the viewBox.
2. Process filled elements separately rather than merging all same-color regions.
3. Render each candidate filled stroke to a mask.
4. Skeletonize the mask.
5. Trace the skeleton graph into ordered centerline paths.
6. Estimate stroke width from the filled region.
7. Emit stroked SVG paths with `fill="none"`.

The current promoted landscape command is:

```bash
DYLD_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python convert_filled_svg_to_stroked_lines.py inputs/landscape.svg \
  --output outputs/landscape.svg \
  --mode elements \
  --scale 4 \
  --simplify-epsilon 0 \
  --max-stroke-width 30 \
  --skeleton-method zhang \
  --trace-mode paired \
  --stroke-scale 1.07 \
  --overlap-spur-max 80
```

The accepted dinosaur output should not be regressed. It currently remains:

```text
outputs/dinosaur.svg
```

## Current Metrics

Pixel comparisons use:

```bash
node compare.js <input.svg> <output.svg> 1200 <diff.png> <side-by-side.png>
```

Current final output checks:

```text
inputs/dinosaur.svg vs outputs/dinosaur.svg @ 1200px
differing pixels: 725/1440000 = 0.05%
similarity: 99.95%

inputs/landscape.svg vs outputs/landscape.svg @ 1200px
differing pixels: 12021/1440000 = 0.83%
similarity: 99.17%
```

Useful debug comparison files:

- `debug/current-dinosaur-side-by-side.png`
- `debug/current-dinosaur-diff.png`
- `debug/current-landscape-side-by-side.png`
- `debug/current-landscape-diff.png`
- `debug/landscape-overlap-spur-final-side-by-side.png`
- `debug/landscape-overlap-spur-final-diff.png`

## Iterations Tried

### Original Node approach

The initial script was:

```text
convert-filled-svg-to-stroked-lines.mjs
```

It used a raster centerline approach and worked acceptably for the dinosaur compared with the target from the earlier ChatGPT session, but it produced patchier landscape output and larger visible gaps.

### Python element-mode approach

The Python rewrite improved the architecture by processing elements independently. This avoided merging same-color strokes that should remain separate.

Notable results:

- Python color-mode baseline: good dinosaur, bad landscape because same-color elements merged.
- Python element mode at scale 4: landscape improved substantially.
- Zhang skeletonization generally performed best or competitively.
- Medial-axis and Lee skeletonization were tested but did not solve the visual overlap issue.

### Paired graph tracing

The tracer was changed to pair skeleton branches through junctions instead of splitting aggressively at every junction. This helped reduce some blobs and disconnected-looking joins.

Related options:

```bash
--trace-mode paired
--pair-dot-cutoff
```

### Overlap spur handling

An overlap-spur pass was added for short terminal branches near junctions:

```bash
--overlap-spur-max 80
```

The idea was to fold short local branches into a passing stroke as an out-and-back excursion rather than treating them as independent dangling line fragments. This improved some cases but did not fully resolve the visually glaring angular protrusions.

### Stroke-width tuning

`--stroke-scale 1.07` is the current promoted width scale for landscape. A sweep showed the best landscape metric around this value.

### Join and cap experiments

Tried variants such as round, bevel, miter, butt, and endpoint-style caps. Some reduced pixel differences locally, but bevel/miter looked mechanically chopped and did not match the expected natural drawing motion.

### Alternative outline approaches

Naive outline-centerline and farthest-split experiments were much worse and were not promoted.

### External CLI tools

Homebrew-installed tools tested:

```bash
brew install autotrace potrace
```

`autotrace` can emit centerline SVG paths:

```bash
autotrace -centerline -preserve-width -background-color FFFFFF \
  -output-format svg \
  -output-file debug/autotrace-landscape-centerline.svg \
  inputs/landscape.svg
```

However, raw autotrace centerline output did not preserve usable stroke widths.

Results:

```text
Autotrace dinosaur raw: 3.10% differing pixels
Autotrace landscape raw: 15.61% differing pixels
Best autotrace dinosaur fixed-width sweep: 0.17% at width 16
Best autotrace landscape fixed-width sweep: 1.79% at width 24
```

This is worse than the current Python output.

`potrace` is not appropriate for the final requirement. It traces filled outlines and emits output like:

```xml
fill="#000000" stroke="none"
```

That violates the requirement that the output use lines rather than shape fills.

## Literature And Tooling Notes

The relevant research category is sketch, line-art, and handwriting vectorization, not ordinary raster-to-vector outline tracing.

Most production vectorizers such as Potrace, Illustrator Image Trace, VTracer, and standard Inkscape tracing are primarily outline/fill vectorizers. They can reproduce a silhouette, but they do not recover the original pen stroke centerline and drawing gesture.

More relevant directions:

- OpenToonz/Tahoma2D style cleanup and centerline vectorization.
- Scan2CAD/WinTopo-style centerline modes.
- Research on line drawing vectorization via junction-aware fields, especially approaches similar to PolyVector fields.
- Sketch reconstruction or offline handwriting reconstruction methods that infer stroke trajectory from raster ink.

For this project, the most relevant missing capability is junction disambiguation: deciding how stroke branches should pass through acute turns, overlaps, and self-intersections.

## Environment Notes

Python dependencies were installed into:

```text
.venv/
```

Native Cairo was installed with Homebrew. Python commands that use CairoSVG currently require:

```bash
DYLD_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python ...
```

The virtual environment is ignored by Git.

Node comparison tooling uses:

```bash
node compare.js ...
```

The comparison script renders both SVGs to the same square canvas, runs `pixelmatch`, and optionally writes diff and side-by-side PNGs.

## Current Git State Notes

Important commits from this attempt:

```text
86cf7a1 Add Python paired-trace SVG converter
037b9d3 Handle overlap spurs in SVG stroke tracing
```

At the time this handoff was written, many debug artifacts were untracked under `debug/`. That is expected. There was also a modified `.DS_Store`, which is unrelated to the converter work.

## Recommended Next Step

Do not keep only tuning global thresholds. The remaining issue is not mainly stroke width, skeleton method, or simplification epsilon.

The next serious attempt should focus on local topology reconstruction around ambiguous skeleton junctions:

1. Detect acute-turn and overlap neighborhoods in each filled element.
2. Preserve more local geometry than the one-pixel skeleton alone provides, possibly by sampling both outline rails.
3. Infer candidate stroke trajectories through the neighborhood.
4. Score candidates by both pixel coverage and natural drawing motion: curvature continuity, tangent continuity, and avoidance of short unnatural straight protrusions.
5. Replace only the ambiguous local segment while keeping the rest of the current high-accuracy pipeline.

The current output is already strong by pixel metrics. The remaining gap is perceptual and geometric: reconstructing the line as a plausible pen stroke, especially where a same-stroke segment overlaps itself or turns into a point.
