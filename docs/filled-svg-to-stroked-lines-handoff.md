# Filled SVG to Stroked Line SVG Conversion Handoff

## Project summary

This project converts a generated SVG that visually looks like a line drawing, but is internally built from filled outline shapes, into an SVG composed of actual stroked line paths.

The original problem case was a simple childlike line drawing of a dinosaur, sun, clouds, hills, and ground lines. Visually, the drawing used solid colored strokes. Structurally, however, the SVG did not contain real stroked paths. Each visible “line” was represented as a filled ribbon shape, usually a closed path with a solid `fill` color and no meaningful `stroke` data.

The goal was to produce a new SVG where the same drawing is represented using paths such as:

```xml
<path d="M ... L ..." fill="none" stroke="#AB71E1" stroke-width="10" stroke-linecap="round" stroke-linejoin="round" />
```

instead of filled outline shapes such as:

```xml
<path d="M ... C ... Z" fill="#AB71E1" />
```

This matters because many drawing apps, editors, animation tools, and kid-art pipelines treat filled SVG blobs differently from true line strokes. A true stroked-line SVG is easier to edit, recolor, animate, simplify, replay, or combine with a drawing app’s native line model.

## Repository artifact

The current standalone Node.js implementation is:

```text
src/convert-filled-svg-to-stroked-lines.mjs
```

It is an ES module script intended to be run directly with Node:

```bash
node src/convert-filled-svg-to-stroked-lines.mjs input.svg --output output-lines.svg
```

Runtime dependencies:

```bash
npm install sharp pngjs
```

The script depends on `sharp` for SVG rasterization and `pngjs` for reading the rendered PNG pixel buffer. The rest of the image-processing pipeline is implemented directly in JavaScript.

## Important filename note

The user asked whether this could be converted into a Node `*.msj` file. The intended Node ESM extension is `*.mjs`, not `*.msj`. The delivered script uses the correct `.mjs` extension.

## Why the chosen approach is raster-to-centerline reconstruction

### The obvious SVG-parser approach was not enough

At first glance, it may seem like this should be solved by parsing the original SVG paths and converting every filled shape into a stroke. In practice, that is difficult and brittle for generated SVGs because the filled shapes are not semantically meaningful strokes. They are geometric outlines of strokes.

For example, a single curved purple dinosaur contour might be represented as a closed filled path describing both sides of a thick curve. To convert that back into a stroke, a parser would need to:

1. Identify that the filled path is intended to be a thickened line.
2. Determine which boundary is the left side of the stroke and which is the right side.
3. Recover the centerline between those two boundaries.
4. Estimate the original stroke width.
5. Handle joins, caps, loops, overlaps, and anti-aliased or malformed generated geometry.

This is a hard computational-geometry problem, especially for arbitrary generated SVG paths. It is also highly dependent on the exact output style of the SVG generator.

### The raster approach is more robust for this use case

The drawing is visually simple: colored line art on a background. The visual result is the source of truth. Because the desired output is a visual approximation using true strokes, it is practical to rasterize the SVG, process it as an image, and reconstruct centerlines from the colored filled regions.

The conversion process therefore treats each filled colored ribbon as a binary mask, skeletonizes that mask down to a one-pixel-wide centerline, traces that skeleton into ordered paths, estimates the ribbon thickness, and emits a new SVG with strokes.

This approach is not a perfect semantic SVG conversion, but it is a good fit for generated line drawings where:

- The image is simple.
- There are a small number of flat colors.
- Each color represents linework.
- There are no gradients, textures, shadows, or complex filled illustrations.
- The visual drawing matters more than preserving original SVG path topology.

## High-level pipeline

The script follows this pipeline:

1. Parse command-line arguments.
2. Read the input SVG text.
3. Extract the SVG `viewBox`.
4. Extract explicit hex fill colors.
5. Rasterize the SVG to a PNG at the viewBox size.
6. Assign each visible pixel to the nearest source fill color.
7. Build a binary mask for each color.
8. Clean each mask with small morphological operations.
9. Remove tiny disconnected artifacts.
10. Skeletonize each cleaned mask using Zhang-Suen thinning.
11. Estimate stroke width using a distance transform.
12. Trace skeleton pixels into ordered polylines.
13. Simplify each polyline using Douglas-Peucker simplification.
14. Emit a new SVG with `fill="none"` stroked paths.

## Detailed walkthrough of the Node script

### Command-line parsing

The script starts with `parseArgs(process.argv)`. It accepts:

```bash
node src/convert-filled-svg-to-stroked-lines.mjs input.svg --output output.svg
```

Supported options:

```text
--output, -o               Output SVG path
--alpha-threshold          Minimum alpha for a rendered pixel to count as visible
--min-object-size          Remove connected color blobs smaller than this pixel count
--min-path-length          Skip traced paths shorter than this length
--simplify-epsilon         Douglas-Peucker simplification tolerance
--min-stroke-width         Lower clamp for estimated stroke width
--max-stroke-width         Upper clamp for estimated stroke width
```

The defaults are tuned for the original dinosaur drawing:

```js
alphaThreshold: 48,
minObjectSize: 20,
minPathLength: 15,
simplifyEpsilon: 2.2,
minStrokeWidth: 6,
maxStrokeWidth: 18,
```

These defaults assume a fairly clean, simple line-art SVG.

### ViewBox parsing

The script uses `readViewBox(svgText)` to find the source SVG coordinate system:

```js
const match = svgText.match(/viewBox=["']([^"']+)["']/i);
```

The output SVG preserves this same viewBox. The rasterization step also uses the viewBox width and height as the target pixel dimensions.

This keeps the generated coordinates aligned with the original SVG’s coordinate system. For example, if the input has:

```xml
<svg viewBox="0 0 1024 576">
```

then the script renders the SVG as a 1024×576 image and emits output paths in that same coordinate space.

Current limitation: the script expects an explicit `viewBox`. It does not currently fall back to `width` and `height` if the viewBox is missing.

### Fill color extraction

The script uses `extractFillColors(svgText)` to find explicit hex fill colors in two forms:

```xml
fill="#AB71E1"
```

and:

```xml
style="fill:#AB71E1"
```

Only six-digit hex colors are currently extracted:

```js
/fill=["'](#[0-9a-fA-F]{6})["']/g
/fill:\s*(#[0-9a-fA-F]{6})/g
```

The script assumes that the meaningful linework colors are represented as explicit flat fills. This was true for the generated SVG in this conversation.

Current limitations:

- It does not parse `rgb(...)`, `rgba(...)`, `hsl(...)`, named colors, CSS variables, inherited styles, external stylesheets, or three-digit hex colors.
- It may include background fill colors if the background is represented as an explicit fill. In the original use case, the line colors were explicit and visually distinct.

A future version should include a real CSS/SVG style parser if broader SVG support is needed.

### SVG rasterization

The script rasterizes the SVG with `sharp`:

```js
const pngBuffer = await sharp(svgPath)
  .resize(width, height, { fit: 'fill' })
  .png()
  .toBuffer();
```

Then it decodes the PNG using `pngjs`:

```js
const png = PNG.sync.read(pngBuffer);
```

The result is an RGBA buffer. Each pixel has red, green, blue, and alpha channels.

This step converts complicated SVG geometry into a simple pixel grid. From this point forward, the script does image processing, not SVG path parsing.

### Pixel-to-color assignment

Because rasterization introduces anti-aliasing, edge pixels are often not exactly equal to the original fill colors. A purple line edge may produce pixels that are light purple or partially blended with the background.

The script handles this by assigning each visible pixel to the nearest extracted fill color in RGB space:

```js
const d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2;
```

Only pixels with alpha greater than `alphaThreshold` are considered visible.

The output is an array where each pixel is assigned a color index, or `-1` if it is not visible enough to count.

This makes the script resilient to anti-aliased SVG output.

### Per-color binary masks

For each extracted fill color, the script builds a binary mask:

```js
colorMask[p] = nearestColorIndex[p] === colorIndex ? 1 : 0;
```

Each mask is a one-channel image where:

- `1` means this pixel belongs to the current colored linework.
- `0` means it does not.

Processing each color independently is important because different visual strokes should retain their original colors in the final SVG.

For example, the dinosaur body remains purple, the sun remains yellow, the hills remain green, and the clouds remain blue.

### Morphological closing

The script applies a simple morphological closing operation:

```js
return erode(dilate(mask, width, height), width, height);
```

Closing means dilation followed by erosion. It helps close tiny gaps and smooth small holes in a binary mask.

Why this helps:

- Anti-aliasing can leave tiny breaks around thin or curved shapes.
- Rasterization can produce small holes inside otherwise continuous line ribbons.
- Skeletonization is very sensitive to tiny gaps.

This implementation uses an 8-connected neighborhood, so each pixel considers its surrounding eight neighbors.

### Removing small objects

The script removes small disconnected components using `removeSmallObjects(...)`. It performs a flood-fill / connected-component search over the binary mask.

For each connected component:

- If its pixel count is below `minObjectSize`, it is removed.
- Otherwise, it is retained.

This prevents tiny noise blobs from turning into stray SVG paths.

### Skeletonization using Zhang-Suen thinning

The core operation is skeletonization. The script uses the Zhang-Suen thinning algorithm, implemented in `skeletonizeZhangSuen(...)`.

Skeletonization reduces a thick filled region to a one-pixel-wide approximation of its centerline. For a filled ribbon that visually represents a line stroke, the skeleton is close to the original intended line.

Zhang-Suen thinning works by repeatedly deleting boundary pixels while preserving connectivity. Each iteration has two sub-steps with slightly different deletion rules. A pixel is deleted only if it satisfies constraints related to:

- Its number of filled neighbors.
- The number of 0→1 transitions around its neighborhood.
- Connectivity-preserving neighborhood products.

The implementation loops until no more pixels can be deleted.

This turns the filled ribbon masks into thin skeleton masks.

### Distance transform for stroke width estimation

Once the centerline skeleton exists, the script estimates stroke width by measuring how far skeleton pixels are from the edge of the original mask.

It uses a chamfer-style distance transform implemented in `distanceTransformChamfer(...)`.

The distance transform assigns each mask pixel an approximate distance to the nearest background pixel. For a skeleton pixel near the center of a thick ribbon, this distance approximates half the stroke width.

The script collects distance values at all skeleton pixels:

```js
if (skeleton[p]) {
  skeletonDistances.push(distance[p]);
}
```

Then it estimates stroke width as:

```js
let strokeWidth = median(skeletonDistances) * 2 || 8;
```

Finally, it clamps the result:

```js
strokeWidth = Math.max(minStrokeWidth, Math.min(maxStrokeWidth, strokeWidth));
```

Using the median is more stable than using the mean because it reduces the influence of odd joins, caps, crossings, or local artifacts.

Current limitation: this assigns one stroke width per color, not one stroke width per individual path. That worked well for the original drawing because each color used a mostly consistent line thickness.

### Skeleton path tracing

A skeleton mask is just unordered pixels. SVG paths need ordered point sequences. The script converts skeleton pixels to paths in `traceSkeletonPaths(...)`.

It does this by:

1. Finding all skeleton pixels.
2. Calculating each pixel’s degree, meaning how many skeleton neighbors it has.
3. Treating pixels with degree other than 2 as graph nodes.
4. Walking from each node through neighboring skeleton pixels until reaching another node.
5. Recording each walk as a path.
6. Handling remaining unvisited loops separately.

This turns a skeleton graph into a list of pixel paths.

The tracing model is useful for line drawings because most strokes are either:

- Open paths with endpoints.
- Curves that branch or meet at junctions.
- Closed loops, such as the sun circle or dinosaur eye.

### Path simplification

Raw skeleton paths contain one point per pixel. That is much too verbose for a usable SVG.

The script simplifies each path using Douglas-Peucker simplification in `simplifyDouglasPeucker(...)`.

Douglas-Peucker recursively removes points that do not significantly change the shape of the polyline. The tolerance is controlled by:

```text
--simplify-epsilon
```

A higher value produces fewer points and smoother, simpler paths. A lower value preserves more detail but creates larger output.

The default is:

```js
simplifyEpsilon: 2.2
```

This was chosen as a reasonable compromise for the attached line drawing: simple enough to be editable, but still close to the original visual shape.

### SVG output

The script writes a new SVG with:

```xml
<g fill="none" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke">
```

Each traced path becomes:

```xml
<path d="M ... L ..." stroke="#COLOR" stroke-width="WIDTH"/>
```

Important output choices:

- `fill="none"` ensures the output is line-based, not shape-filled.
- `stroke-linecap="round"` approximates the rounded ends of the original filled ribbons.
- `stroke-linejoin="round"` prevents sharp jagged joins.
- `vector-effect="non-scaling-stroke"` preserves stroke width under SVG scaling in editors/viewers that support it.

## How the approach was arrived at

The original SVG was visually a line drawing but structurally made of filled shapes. The desired output was not simply “outline all filled shapes,” because outlining a filled ribbon would create two boundary lines rather than the single centerline the user wanted.

The key insight was that the visible fill shape represents the area swept out by a stroke. To recover the stroke, the useful representation is the medial axis or skeleton of that area.

The process moved from this conceptual model:

```text
filled ribbon shape → centerline + stroke width
```

to this implementation model:

```text
SVG → raster pixels → color masks → skeletons → traced paths → stroked SVG
```

This mirrors common image-processing techniques used for centerline extraction, bitmap vectorization, and line-art cleanup.

The generated result was good enough for the provided SVG because the drawing has these favorable properties:

- Flat color regions.
- Simple rounded linework.
- High contrast between line colors and background.
- Minimal overlap between colors.
- Consistent stroke thickness.
- No textured brush effects.
- No gradients or semi-transparent paint.

## Known limitations

### It is visual reconstruction, not semantic SVG conversion

The output approximates the visual drawing. It does not preserve original path commands, Bézier curves, grouping, layer names, transforms, comments, or metadata.

### It currently emits polylines, not Bézier curves

The generated SVG paths use `M` and `L` commands. Curves are represented by many straight segments. This is valid SVG and usually visually acceptable, but not as clean as hand-authored cubic Bézier paths.

A future extension could fit quadratic or cubic Bézier curves to simplified point sequences.

### It assumes flat explicit fill colors

The script works best when the input SVG has explicit flat fill colors. It does not currently handle complex CSS or inherited styling robustly.

### It does not distinguish foreground line colors from background fills

If the SVG includes a filled white or cream background, the script may extract it as a fill color unless filtered out. In the original case, this was not a serious problem because the meaningful line colors were the prominent non-background colors.

A production version should add background-color filtering.

### It assigns one stroke width per color

If one color contains both thin and thick strokes, the script will currently choose one median width for all paths of that color.

A better version could estimate stroke width per connected component or per traced path.

### Branches and intersections can produce imperfect paths

Skeleton graphs with branches are harder to trace than simple lines. At intersections, the script may split paths in ways that are visually fine but not semantically ideal.

For example, a dinosaur body contour that touches a leg may become multiple path segments.

### Small details can be lost

Tiny shapes may be removed by `minObjectSize` or skipped by `minPathLength`. This is often good for noise removal but can remove intentional small details such as dots or short accent marks.

Tuning these options may be necessary depending on the input.

### Anti-aliasing and color blending can cause color assignment mistakes

The nearest-color classifier works well when colors are distinct. If two line colors are similar, anti-aliased edge pixels may be assigned to the wrong color.

A more advanced version could use alpha-aware compositing, perceptual color distance, or clustering.

## Tuning guide

### Preserve more detail

Use a lower simplification tolerance:

```bash
node src/convert-filled-svg-to-stroked-lines.mjs input.svg \
  --output output.svg \
  --simplify-epsilon 1.0
```

This produces more path points and a closer visual match.

### Make paths simpler

Use a higher simplification tolerance:

```bash
node src/convert-filled-svg-to-stroked-lines.mjs input.svg \
  --output output.svg \
  --simplify-epsilon 4.0
```

This produces fewer points, but curves may look more angular.

### Keep tiny details

Lower `min-object-size` and `min-path-length`:

```bash
node src/convert-filled-svg-to-stroked-lines.mjs input.svg \
  --output output.svg \
  --min-object-size 4 \
  --min-path-length 4
```

This helps preserve dots, tiny rays, small marks, or short decorative details.

### Remove more noise

Increase `min-object-size` and `min-path-length`:

```bash
node src/convert-filled-svg-to-stroked-lines.mjs input.svg \
  --output output.svg \
  --min-object-size 50 \
  --min-path-length 25
```

This helps if the output contains many small stray paths.

### Adjust stroke thickness

Use min and max stroke width clamps:

```bash
node src/convert-filled-svg-to-stroked-lines.mjs input.svg \
  --output output.svg \
  --min-stroke-width 4 \
  --max-stroke-width 22
```

If the output looks too thin or too thick globally, these clamps are the easiest first adjustment.

## Suggested project structure

For a standalone maintained project, a practical structure would be:

```text
filled-svg-to-stroked-lines/
  package.json
  README.md
  LICENSE
  src/
    cli.mjs
    convert.mjs
    colors.mjs
    rasterize.mjs
    morphology.mjs
    skeletonize.mjs
    trace.mjs
    simplify.mjs
    svg-output.mjs
  test/
    fixtures/
      dinosaur-input.svg
      dinosaur-expected.svg
    convert.test.mjs
  examples/
    dinosaur-input.svg
    dinosaur-output.svg
  docs/
    handoff.md
```

The current single-file script is convenient for portability, but a real project should split the pipeline into testable modules.

## Suggested package.json

A minimal package could look like:

```json
{
  "name": "filled-svg-to-stroked-lines",
  "version": "0.1.0",
  "type": "module",
  "bin": {
    "filled-svg-to-stroked-lines": "./src/cli.mjs"
  },
  "scripts": {
    "test": "node --test",
    "convert:example": "node src/cli.mjs examples/dinosaur-input.svg --output examples/dinosaur-output.svg"
  },
  "dependencies": {
    "pngjs": "^7.0.0",
    "sharp": "^0.33.0"
  },
  "devDependencies": {}
}
```

Version numbers should be checked and updated when creating the actual project.

## Testing strategy

### Golden-file visual tests

Use a fixture SVG and compare the generated output to an expected SVG or expected rendered PNG.

Because the algorithm may produce slightly different path orders or point sequences after refactors, pixel-level visual regression tests may be more useful than exact SVG text comparisons.

Suggested test flow:

1. Convert fixture input SVG to output SVG.
2. Render output SVG to PNG with `sharp`.
3. Render original SVG to PNG with `sharp`.
4. Compare the two PNGs using a pixel-difference threshold.

### Structural SVG tests

Check that the output only contains stroked paths:

- No filled path linework.
- Every path has `fill="none"` or inherits `fill="none"` from a parent group.
- Every path has `stroke`.
- Every path has `stroke-width`.

### Unit tests

Good unit-test targets:

- `readViewBox`
- `extractFillColors`
- `removeSmallObjects`
- `skeletonizeZhangSuen`
- `traceSkeletonPaths`
- `simplifyDouglasPeucker`
- `distanceTransformChamfer`
- `svgPathD`

### Fixture diversity

Useful fixtures:

- A straight horizontal filled ribbon.
- A curved filled ribbon.
- A closed ring/circle.
- Multiple colors.
- Tiny dots/details.
- Branching/intersecting strokes.
- SVG with a background rectangle.
- SVG with similar colors.

## Possible extensions

### 1. Better color parsing

Add support for:

- Three-digit hex colors.
- `rgb(...)` and `rgba(...)`.
- `hsl(...)` and `hsla(...)`.
- Named CSS colors.
- CSS classes in `<style>` blocks.
- Inherited `fill` attributes from parent groups.
- CSS variables.

This would make the tool work on a much wider range of SVGs.

### 2. Background filtering

Add options like:

```bash
--ignore-color '#FFFFFF'
--ignore-near-white
--ignore-largest-region
```

This would prevent backgrounds from being skeletonized into large unwanted paths.

A reasonable default could be to ignore the largest connected component if it touches all or most edges of the canvas and is near white.

### 3. Per-component stroke width

Instead of estimating one stroke width per color, estimate stroke width per connected component or per traced path.

That would better support drawings where the same color is used with multiple pen widths.

### 4. Bézier curve fitting

Convert simplified polylines into smoother Bézier paths.

Possible approaches:

- Fit cubic curves to point sequences.
- Use a library such as `fit-curve`.
- Use Potrace-like curve optimization.

This would produce more natural, editable SVG paths.

### 5. Preserve or reconstruct drawing order

The current script processes colors in sorted color order. The output order may not match the original drawing order.

Future versions could:

- Preserve source element order when possible.
- Infer layering from the original SVG.
- Allow custom color order.
- Sort paths by approximate position.

### 6. Browser version

The algorithm could be ported to run in the browser for integration into a drawing app.

Browser equivalents:

- Use `<canvas>` or `OffscreenCanvas` for rasterization.
- Use `ImageData` instead of `pngjs`.
- Use the same JavaScript morphology, skeletonization, tracing, and simplification code.

The main challenge is reliably rendering arbitrary SVG to a canvas while respecting CORS and embedded resources.

### 7. TypeScript conversion

A maintained project would benefit from TypeScript types for:

- Raster image buffers.
- Binary masks.
- Points and paths.
- Conversion options.
- SVG output path records.

The current script is plain JavaScript for easy copy/paste use.

### 8. Batch conversion

Add CLI support for directories:

```bash
filled-svg-to-stroked-lines ./inputs --output-dir ./outputs
```

Useful options:

- Recursive mode.
- Preserve folder structure.
- Skip existing outputs.
- Emit preview PNGs.
- Emit JSON diagnostics.

### 9. Diagnostic artifacts

For debugging, add flags to write intermediate images:

```bash
--debug-dir debug-output
```

Potential outputs:

- Rendered PNG.
- Per-color masks.
- Cleaned masks.
- Skeleton masks.
- Traced path overlays.
- Final rendered output.

This would make tuning much easier.

### 10. Library API

Expose a library function in addition to the CLI:

```js
import { convertFilledSvgToStrokedLines } from 'filled-svg-to-stroked-lines';

await convertFilledSvgToStrokedLines({
  input: 'input.svg',
  output: 'output.svg',
  simplifyEpsilon: 2.2,
});
```

This would make it easier to integrate into build scripts, design pipelines, or the drawing app.

## Recommended README content

The README should include:

1. What problem the tool solves.
2. Before/after screenshots.
3. Installation instructions.
4. CLI usage.
5. Explanation that the tool uses visual centerline reconstruction.
6. Supported input assumptions.
7. Known limitations.
8. Tuning options.
9. Development instructions.
10. Test fixture examples.

## Development priorities

Recommended next steps for turning this into a maintained project:

1. Split the single `.mjs` file into modules.
2. Add a `package.json` with a `bin` entry.
3. Add test fixtures.
4. Add visual regression tests.
5. Add debug-output mode.
6. Improve color parsing and background filtering.
7. Add per-component stroke width estimation.
8. Consider TypeScript.
9. Add browser-compatible build if this needs to run inside the drawing app.

## Production readiness assessment

The current script is a useful prototype and can be used as a repeatable conversion utility for SVGs similar to the provided example. It is not yet a general-purpose SVG optimizer or vectorizer.

It is production-useful when the input SVGs are controlled or generated from the same source style:

- Flat colors.
- Filled ribbons representing line strokes.
- Simple childlike line art.
- No gradients or textures.
- Reasonably consistent stroke widths.

It needs additional hardening before being marketed as a general SVG conversion tool.

## Mental model for future maintainers

The script is best understood as answering this question:

> Given the colored pixels occupied by each fake stroke, what centerline and stroke width would recreate those pixels as a real SVG stroke?

Everything in the implementation supports that goal:

- Rasterization gets the visible colored pixels.
- Color classification separates the drawing into layers.
- Mask cleanup removes pixel noise.
- Skeletonization finds the centerline.
- Distance transform estimates thickness.
- Path tracing turns centerline pixels into SVG-compatible paths.
- Simplification makes the paths manageable.
- SVG writing emits true strokes.

That mental model should guide future changes. If an extension improves the recovery of centerlines, stroke widths, or visual fidelity while keeping output as editable stroked paths, it fits the project.
