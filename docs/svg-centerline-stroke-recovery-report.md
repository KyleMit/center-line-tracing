# Recovering Centerline Paths from Filled SVG Strokes

**Engineering research report — August 7, 2026**

## Executive summary

The problem is best described as **inverse stroke recovery**: given a filled two-dimensional region that was plausibly created by stroking one or more one-dimensional paths, infer one or more centerline paths that can be traced, animated, edited, or re-stroked.

That is a different problem from ordinary bitmap vectorization. A normal vectorizer such as Potrace or VTracer finds the **boundary** of a filled mark. Here the input may already be vector geometry, and the desired output is the **curve running through the interior** of that geometry.

For roughly constant-width, round-capped pen strokes, the mathematical object closest to the desired centerline is the **Euclidean medial axis / medial axis transform (MAT)**. The MAT is, informally, the locus of centers of maximal disks contained inside the shape. A useful production system normally adds **pruning** because tiny boundary perturbations can create disproportionately large medial-axis branches.

The strongest programmatic options found are:

1. **[`flo-mat`](https://github.com/FlorisSteenkamp/MAT)** — the most directly applicable SVG-native JavaScript/TypeScript library. It computes the Medial Axis Transform and Scale Axis Transform directly over closed line/quadratic/cubic Bézier loops and returns a graph whose branches are Bézier curves. This is the first option I would prototype when the source really is SVG path geometry.
2. **[AutoTrace](https://github.com/autotrace/autotrace)** — the easiest end-to-end baseline. Rasterize the SVG, then run `autotrace -centerline` and receive SVG centerline paths. It has both a CLI and a C library. It is mature and valuable as a comparison implementation, although rasterization loses the principal advantage of already having vector geometry.
3. **[`pygeoops.centerline`](https://pygeoops.readthedocs.io/en/stable/api/pygeoops.centerline.html)** — a strong Python polygon-centerline API with useful built-in densification, branch filtering, simplification, and width-relative automatic parameters. It is not SVG-native: Béziers must first be flattened/converted to polygon geometry.
4. **[`centerline`](https://github.com/fitodic/centerline)** — another Python/CLI option based on a Voronoi construction over polygons. It is GIS-oriented but provides a convenient baseline through a Shapely API and the `create_centerlines` CLI.
5. **[`scikit-image`](https://scikit-image.org/docs/stable/api/skimage.morphology.html) + [`Skan`](https://skeleton-analysis.org/) + [`fit-curve`](https://github.com/soswow/fit-curve)** — probably the best highly configurable raster pipeline. `medial_axis(..., return_distance=True)` gives both a raster skeleton and local radius information; Skan turns the skeleton into a graph; `fit-curve` or Paper.js can fit clean Bézier paths afterward.
6. **[Tegaki](https://github.com/gkurt/tegaki)** — not currently a general-purpose published centerline package, but an unusually relevant TypeScript reference implementation. Its internal generator converts font outlines by flattening, rasterizing, skeletonizing, tracing, pruning, estimating width, and ordering strokes. It implements several skeletonizers, including thinning, distance-transform medial axis, and Voronoi medial axis. Its generator is an internal CLI/library in the monorepo, so it is best viewed as code to study, vendor, or adapt rather than a drop-in npm dependency.
7. **[`skeleton-tracing`](https://github.com/LingDong-/skeleton-tracing)** — an excellent post-skeletonization component that turns a binary 1-pixel skeleton into polylines. Implementations exist in JavaScript, WebAssembly, Python, C/C++, Rust, Swift, C#, Go, Java, and other languages.
8. **[Boost.Polygon Voronoi](https://www.boost.org/doc/libs/latest/libs/polygon/doc/index.htm)** — a strong C++ primitive for building a custom vector Voronoi/medial-axis implementation from points or line segments. It is not turnkey, but it is useful when numerical control and native performance matter.

A practical recommendation is to build **two interchangeable extraction backends**:

- **Primary vector backend:** SVG normalization → `flo-mat` MAT → Scale Axis Transform / custom pruning → graph decomposition → ordered path reconstruction.
- **Fallback raster backend:** high-resolution deterministic rasterization with `resvg` → Euclidean medial axis or thinning → graph/polyline tracing → width-aware pruning → Bézier fitting.

Then validate either backend by **re-stroking the recovered centerline and comparing it with the original filled shape**. That turns centerline extraction from a subjective visual operation into an optimizable reconstruction problem.

---

## 1. Problem definition

### 1.1 Input

Assume an SVG contains one or more filled regions resembling pen strokes:

```svg
<path d="..." fill="#000" />
```

The visible region may originally have been generated from something conceptually like:

```svg
<path
  d="M ... C ..."
  fill="none"
  stroke="#000"
  stroke-width="20"
  stroke-linecap="round"
  stroke-linejoin="round"
/>
```

but the original open path and its stroke semantics have been lost. Only the filled outline remains.

### 1.2 Desired output

The desired output is one or more open centerline paths:

```svg
<path
  d="M ... C ..."
  fill="none"
  stroke="..."
  stroke-width="..."
/>
```

Depending on the application, additional inferred information may be useful:

- nominal or spatially varying stroke width;
- path direction;
- stroke grouping;
- stroke order;
- junction connectivity;
- confidence that a particular branch represents an intentional stroke rather than a skeleton artifact.

### 1.3 A useful mathematical formulation

Let the observed filled region be `S` and the unknown centerline graph/path be `C`. For an approximately constant-width stroke of radius `r`, the forward operation is approximately a Minkowski sum:

```text
S ≈ C ⊕ disk(r)
```

or, in SVG terms, “stroke the path `C` with width `2r` and round caps/joins.”

The inverse problem is:

```text
Given S, infer C and optionally r(s)
so that stroke(C, r(s)) reconstructs S well.
```

This framing is useful because it makes clear that the desired answer is not merely “a line that looks centered.” It is a compact latent representation that should explain the observed filled geometry.

---

## 2. Why exact recovery is not always possible

The conversion from an open stroke to a filled shape is **many-to-one**. Once only the fill survives, some information may be irrecoverable.

### 2.1 Stroke order disappears

If one line was drawn over another, the union of the filled regions generally does not say which one came first.

### 2.2 Crossings and junctions are ambiguous

An X-shaped filled region might represent:

- two independent strokes crossing;
- four strokes meeting at one point;
- one continuous zig-zag plus another stroke;
- a single unusual branching stroke.

Geometry alone cannot always distinguish those histories.

### 2.3 Caps materially affect the medial axis

For a **round-capped constant-width stroke**, the medial axis often agrees very closely with the original stroke centerline.

For a **butt-capped rectangle-like stroke**, the exact medial axis contains branches induced by the end corners. Those branches are mathematically correct medial-axis features but are not part of the original drawing path.

Therefore a production system must usually be **stroke-aware**, not merely mathematically faithful to every medial-axis branch.

### 2.4 Joins create similar ambiguity

Sharp mitered joins, square joins, small protrusions, and vectorization irregularities can all create legitimate but undesirable skeleton branches.

### 2.5 Merged source elements are harder than preserved source elements

If the SVG still contains one filled element per original pen stroke, **do not union them before centerline extraction**. Centerline each element independently whenever possible.

Preserving element identity avoids much of the difficult semantic reconstruction at intersections.

---

## 3. Terminology: several similar-sounding problems are not the same

### Centerline extraction

Recover a line or graph through the middle of a thick region.

### Skeletonization

Reduce a shape to a thin topological representation. Depending on the algorithm, this may be a raster skeleton or a geometric graph.

### Medial axis

The set of interior points having multiple closest boundary points; equivalently, the centers of maximal inscribed disks under the usual Euclidean formulation.

### Medial Axis Transform (MAT)

The medial axis plus the radius/distance information of its corresponding maximal disks. The radius field is especially useful for recovering local stroke width.

### Scale Axis Transform (SAT)

A scale-based simplification of the MAT designed to remove insignificant medial branches while preserving larger-scale structure. This is particularly relevant because medial axes are sensitive to small boundary perturbations.

### Straight skeleton

A different construction generated by inward-moving polygon edges. It resembles a medial axis but is **not generally Euclidean-equidistant from polygon edges**. It is therefore not normally the ideal centerline for rounded pen strokes.

### Outline tracing / vectorization

Convert raster boundaries to vector contours. Potrace, VTracer, and ImageTracer primarily solve this problem, not centerline recovery.

### Stroke recovery

A higher-level problem: centerline extraction plus pruning, junction interpretation, path grouping, orientation, and perhaps stroke order.

---

## 4. Algorithm families

## 4.1 Direct vector medial-axis computation

This is the theoretically cleanest route when the input is already SVG geometry.

```text
SVG Bézier boundary
      ↓
Medial Axis Transform
      ↓
pruned / Scale Axis Transform
      ↓
centerline graph
      ↓
stroke-aware graph decomposition
      ↓
open SVG paths
```

### Advantages

- no pixel quantization;
- preserves vector precision;
- can retain curved centerline edges directly;
- deterministic for a fixed geometric input;
- avoids choosing a raster resolution;
- natural fit for already-vectorized artwork.

### Challenges

- SVG must be normalized into valid closed loops;
- transforms, compound paths, holes, and fill rules need careful handling;
- a raw medial axis still contains unwanted branches around caps/corners/noise;
- semantic stroke ordering remains application-specific.

**Best available implementation found:** `flo-mat`.

---

## 4.2 Vector/polygon Voronoi centerline

A common approximate technique is:

1. flatten or sample the shape boundary;
2. construct a Voronoi diagram from boundary points or line segments;
3. retain Voronoi edges lying inside the polygon;
4. discard irrelevant cells/branches;
5. simplify the surviving graph.

This is conceptually close to the medial axis and is common in GIS centerline packages.

### Advantages

- uses mature computational-geometry primitives;
- naturally vector-valued;
- works well with polygons and Shapely/GEOS-style geometry;
- easier to implement than an analytical Bézier medial axis.

### Challenges

- quality depends on boundary sampling/densification;
- dense sampling increases runtime significantly;
- straight-line flattening introduces approximation error;
- branch pruning and endpoint correction remain necessary.

**Turnkey options:** PyGeoOps and `centerline`.

**Custom C++ primitive:** Boost.Polygon Voronoi.

---

## 4.3 Raster Euclidean medial axis

Render the SVG to a binary mask, compute the distance transform, then recover ridges of that transform.

```text
SVG
 ↓
high-resolution binary mask
 ↓
Euclidean distance transform
 ↓
medial-axis ridge pixels
 ↓
graph / polyline tracing
 ↓
curve fitting
```

This approach is attractive because the distance transform simultaneously gives a skeleton and the local distance to the boundary.

At a skeleton point `p`:

```text
estimated local stroke width ≈ 2 × distance_to_boundary(p)
```

That width signal is extremely valuable for pruning branches and validating the result.

**Strong implementation:** `skimage.morphology.medial_axis(..., return_distance=True)`.

---

## 4.4 Raster morphological thinning

Thinning algorithms repeatedly remove boundary pixels while preserving topology until a one-pixel skeleton remains.

Examples include:

- Zhang-Suen;
- Guo-Hall;
- Lee-style thinning;
- morphological thin operators.

### Advantages

- simple;
- fast;
- robust on arbitrary rendered input;
- abundant implementations.

### Disadvantages

- a thin skeleton does not intrinsically carry radius/width information;
- small raster artifacts can affect branch topology;
- another stage is required to turn pixels into ordered polylines.

**Strong implementations:** OpenCV `ximgproc.thinning` and scikit-image `skeletonize`/`thin`.

---

## 4.5 Straight skeleton

Straight skeletons are worth knowing about because many geometry libraries implement them, but they are usually a **second-tier choice for this problem**.

CGAL's own documentation explicitly distinguishes a straight skeleton from a true medial axis: straight-skeleton bisectors are equidistant from supporting lines rather than from the actual polygon edges and therefore need not remain geometrically centered in a non-convex polygon.

They can still be useful for:

- predominantly polygonal/rectilinear input;
- a quick native C++/database implementation;
- shapes where exact Euclidean centering is not critical.

They are less compelling for smooth, round-capped pen strokes.

---

## 5. Solution matrix

Ratings below are relative to the specific goal of converting filled stroke-like SVG geometry into reusable centerline paths.

| Tool / project | Core approach | Interface | Input | Output | SVG-native? | License | Fit for this problem |
|---|---|---|---|---|---:|---|---|
| **flo-mat** | Analytical MAT + SAT over Bézier loops | npm JS/TS library | closed line/quadratic/cubic Bézier loops | medial-axis graph with Bézier branches | **Yes** | MIT | **Excellent / first prototype** |
| **AutoTrace** | Raster centerline tracing | CLI + C library | bitmap | SVG/EPS/PDF/DXF/etc. splines | No | GPL CLI / LGPL library | **Excellent baseline** |
| **PyGeoOps `centerline`** | Approximate polygon centerline with densification/pruning | Python package | Shapely/GeoSeries polygon | line geometry | No direct SVG | BSD-3-Clause | **Very good Python option** |
| **fitodic `centerline`** | Voronoi polygon centerline | Python API + CLI | polygon/vector GIS | line geometry | No direct SVG | MIT | **Good baseline** |
| **scikit-image `medial_axis`** | Raster Euclidean medial axis | Python package | binary ndarray | skeleton + optional distance field | No | BSD-3-Clause | **Excellent raster primitive** |
| **OpenCV `ximgproc.thinning`** | Zhang-Suen / Guo-Hall thinning | C++ / Python / Java ecosystem | binary image | 1-pixel raster skeleton | No | Apache-2.0 (current OpenCV) | **Excellent fast thinning primitive** |
| **Skan** | Skeleton → graph/path analysis | Python package | raster skeleton | sparse graph, branches, coordinates | No | BSD-3-Clause | **Excellent graph cleanup stage** |
| **skeleton-tracing** | 1-pixel skeleton → polylines | source libs in many languages / WASM | binary skeleton | arrays of polyline coordinates | No | MIT | **Excellent tracing stage** |
| **Tegaki generator** | Full rasterized stroke-recovery pipeline | internal TypeScript/Bun CLI + library in repo | font outlines internally | traced strokes + width/order metadata | Not generic SVG API | MIT | **Excellent reference / adaptable source** |
| **Boost.Polygon Voronoi** | Point/segment Voronoi | C++ library | points/segments | Voronoi graph | No direct SVG | Boost Software License | **Strong custom native building block** |
| **PostGIS `CG_ApproximateMedialAxis`** | Straight-skeleton-based approximate medial axis | SQL function | areal geometry | geometry | No | PostGIS/SFCGAL terms | **Useful sidecar, but geometry is less ideal** |
| **CGAL Straight Skeleton 2** | Straight skeleton | C++ library | polygon with holes | skeleton halfedge graph | No | CGAL licensing | **Powerful, but usually wrong target geometry** |
| **resvg** | Deterministic SVG rasterizer | Rust lib + C lib + CLI + WASM | SVG | raster image | Input is SVG | MIT/Apache-2.0 | **Excellent rasterization stage** |
| **SVGPathCommander** | SVG path normalization/manipulation | npm TS/JS library | SVG path/shapes | normalized/transformed paths | Yes | MIT | **Excellent preprocessing helper** |
| **Paper.js** | path geometry, simplify/smooth | JS library | points/paths | fitted/simplified paths | Yes-ish | MIT | **Strong post-processing helper** |
| **fit-curve** | Schneider cubic Bézier fitting | npm JS package | polyline points | cubic Bézier segments | N/A | MIT | **Strong post-processing helper** |
| **Inkscape centerline extension** | wrapper around AutoTrace centerline | old Inkscape extension | bitmap | vector centerline | No | GPL-2.0 | **Historical only; archived** |
| **Potrace** | contour/outline tracing | CLI + C library | bitmap | vector outlines | No | GPL | **Not a centerline solution** |
| **VTracer / ImageTracer** | raster → vector contours | CLI/libs depending project | bitmap | vector shapes | No | varies | **Not a centerline solution** |

---

# 6. Detailed review of the most promising tools

## 6.1 `flo-mat` — strongest direct fit

**Project:** <https://github.com/FlorisSteenkamp/MAT>  
**npm package:** `flo-mat`  
**Current package metadata checked:** version 4.1.0  
**Language:** TypeScript source / JavaScript distribution  
**License:** MIT  
**Interface:** ESM npm package; Node and browser usage

`flo-mat` describes itself as an SVG-focused **Medial (and Scale) Axis Transform** library. It accepts planar shapes composed of closed sequences of line, quadratic Bézier, and cubic Bézier curves; shapes may include holes and multiple loops. Its MAT/SAT representation is a graph/tree whose branches are Bézier curves.

This is unusually close to the target problem because it does not require reducing already-vectorized artwork to pixels first.

### Why it is promising

- Works directly on the same classes of Bézier geometry used by SVG.
- The output is already curved vector geometry rather than a pixel skeleton.
- Includes **Scale Axis Transform** functionality intended to suppress insignificant MAT branches.
- Usable directly from JavaScript/TypeScript.
- MIT license is straightforward for most application contexts.

### Basic API shape

The project's example uses the following sequence:

```ts
import {
  findMats,
  getPathsFromStr,
  traverseEdges,
  toScaleAxis,
  getCurveToNext,
  isTerminating,
} from 'flo-mat';

const loops = getPathsFromStr(pathD);
const mats = findMats(loops, 3);
const sats = mats.map((mat) => toScaleAxis(mat, 1.5));

for (const sat of sats) {
  if (!sat.cpNode) continue;

  traverseEdges(sat.cpNode, (node) => {
    if (isTerminating(node)) return;
    const curve = getCurveToNext(node);
    if (!curve) return;

    // `curve` is a line / quadratic / cubic Bézier represented by control points.
    // Accumulate it into the centerline graph here.
  });
}
```

Install:

```bash
npm install flo-mat
```

### What it does *not* solve

`flo-mat` produces medial-axis geometry; it does not magically reconstruct the exact user's drawing history.

Application-specific work still includes:

- determining which MAT/SAT branches correspond to intended strokes;
- removing cap/corner artifacts;
- deciding whether a degree-4 crossing should be two crossing strokes or one four-way graph;
- orienting each path;
- ordering multiple strokes;
- merging the library's graph edges into compact SVG `d` strings.

### Primary risk to prototype

The highest-risk area is **behavior at ends and merged intersections**. Test the library on representative shapes before committing to the architecture.

Suggested synthetic cases:

1. straight capsule with round caps;
2. same stroke with butt caps;
3. 90-degree round join;
4. acute round join;
5. C-shaped curve;
6. loop/circle;
7. X crossing made from a union of two strokes;
8. T junction;
9. closely parallel strokes that nearly touch;
10. noisy/vectorized outline with small bumps.

---

## 6.2 AutoTrace — best one-command baseline

**Project:** <https://github.com/autotrace/autotrace>  
**Language:** C  
**Interfaces:** CLI + `libautotrace` C library  
**License:** CLI GPL-2.0; library LGPL-2.1

AutoTrace explicitly supports **centerline tracing**, which makes it one of the few truly turnkey tools in this landscape.

Example:

```bash
autotrace input.png -centerline -output-file output.svg
```

The project also exposes `libautotrace`, with a C API for reading a bitmap, fitting splines, and writing output.

### Why it is worth keeping in the evaluation

- Minimal engineering effort to obtain a real centerline result.
- Emits vector output directly.
- Mature codebase.
- Available on multiple platforms and package managers.
- Useful as a benchmark even if it is not selected for production.

### Main downside

AutoTrace fundamentally consumes **bitmap input**. For already-vectorized SVG, the pipeline becomes:

```text
SVG → rasterize → AutoTrace → SVG
```

That means:

- centerline location becomes resolution-dependent;
- antialiasing/thresholding become variables;
- very small gaps can close or break depending on rasterization;
- subpixel vector precision is discarded before being reconstructed.

### Licensing consideration

The CLI and library have different GNU licenses. If embedding or redistributing AutoTrace, review the actual integration model and applicable license with appropriate legal guidance.

### Recommendation

Even if `flo-mat` wins, keep AutoTrace in a test harness. If a supposedly superior custom solution cannot consistently outperform `autotrace -centerline` on representative art, the added complexity may not yet be justified.

---

## 6.3 PyGeoOps `centerline` — strong Python polygon API

**Docs:** <https://pygeoops.readthedocs.io/en/stable/api/pygeoops.centerline.html>  
**Repository:** <https://github.com/pygeoops/pygeoops>  
**Language:** Python  
**Interface:** Python package  
**License:** BSD-3-Clause  
**Docs checked:** 0.6.0

API:

```python
pygeoops.centerline(
    geometry,
    densify_distance=-1,
    min_branch_length=-1,
    simplifytolerance=-0.25,
    extend=False,
)
```

The design is attractive because it exposes precisely the practical controls centerline extraction needs:

- boundary densification;
- minimum branch length;
- output simplification;
- endpoint extension;
- negative parameter values that derive defaults relative to average geometry width.

### Example

```python
import pygeoops
from shapely.geometry import Polygon

polygon = Polygon(boundary_points)

line = pygeoops.centerline(
    polygon,
    densify_distance=-0.5,
    min_branch_length=-1.0,
    simplifytolerance=-0.15,
    extend=False,
)
```

The exact values should be tuned against representative stroke widths.

### Advantages

- simple Python API;
- useful built-in pruning knobs;
- width-relative defaults align well with stroke geometry;
- returns standard geometry objects that can be serialized or further processed with Shapely/GeoPandas.

### Disadvantages for SVG artwork

- SVG Béziers must be flattened to polygon segments first;
- SVG transforms/fill rules are outside its scope;
- polygon-oriented output may require additional curve fitting before producing compact smooth SVG paths.

### Best use

A very good **server-side or offline comparison backend**, and potentially a production backend if Python is already convenient.

---

## 6.4 `centerline` by fitodic — convenient Voronoi baseline

**Repository:** <https://github.com/fitodic/centerline>  
**Docs:** <https://centerline.readthedocs.io/>  
**Language:** Python  
**Interfaces:** Python class + CLI  
**License:** MIT

The package constructs polygon centerlines using a **Voronoi diagram**.

Python:

```python
from shapely.geometry import Polygon
from centerline.geometry import Centerline

polygon = Polygon(points)
centerline = Centerline(polygon)
result = centerline.geometry
```

CLI:

```bash
create_centerlines input.shp output.geojson
```

### Assessment

This package is intentionally targeted at roads, rivers, and similar GIS polygons rather than artistic strokes. That does not make it unusable, but its assumptions and output cleanup are less tailored to pen-style outlines than `flo-mat` or a custom distance-aware raster pipeline.

Use it primarily as:

- a quick Python/Voronoi prototype;
- an independent comparison implementation;
- a source of ideas for polygon sampling and Voronoi filtering.

---

## 6.5 scikit-image `medial_axis` — strongest general raster primitive

**Docs:** <https://scikit-image.org/docs/stable/api/skimage.morphology.html>  
**Language:** Python/Cython ecosystem  
**Interface:** Python package  
**License:** BSD-3-Clause  
**Stable docs checked:** 0.26.0

The relevant API is:

```python
from skimage.morphology import medial_axis

skeleton, distance = medial_axis(mask, return_distance=True)
```

The documentation describes the medial axis as ridges of the distance transform. The ability to return the distance field is especially useful.

### Why `return_distance=True` matters

At every skeleton pixel, the distance field provides an estimate of radius to the boundary. That allows branch metrics such as:

```text
branch length / local width
radius consistency along branch
branch radius / dominant stroke radius
```

These are much better pruning signals than raw branch length alone.

### Example width extraction

```python
import numpy as np
from skimage.morphology import medial_axis

skeleton, distance = medial_axis(mask, return_distance=True)
local_widths = 2.0 * distance[skeleton]
median_width = np.median(local_widths)
```

### Recommendation

If rasterization is acceptable, this is the primitive I would prefer over plain thinning for the main algorithm because width information is so valuable.

Plain `skeletonize()` or OpenCV thinning can still be useful as alternate algorithms for difficult topology.

---

## 6.6 OpenCV `ximgproc.thinning` — fast production-friendly raster thinning

**Docs:** <https://docs.opencv.org/4.13.0/df/d2d/group__ximgproc.html>  
**Languages/interfaces:** C++, Python, Java ecosystem  
**Module:** OpenCV contrib `ximgproc`  
**Current OpenCV license:** Apache-2.0 for OpenCV 4.5+

OpenCV exposes:

```cpp
cv::ximgproc::thinning(src, dst, thinningType)
```

and the Python binding:

```python
cv.ximgproc.thinning(src, thinningType=cv.ximgproc.THINNING_ZHANGSUEN)
```

Supported thinning variants include Zhang-Suen and Guo-Hall.

### Best use

- high-throughput skeletonization;
- native/mobile code where OpenCV is already present;
- alternate skeletonizer in a benchmark ensemble.

### Limitation

The result is still a raster skeleton. You need a second component to extract branches/polylines, plus a distance transform if local width is needed.

---

## 6.7 Skan — excellent skeleton graph layer

**Docs:** <https://skeleton-analysis.org/>  
**Repository:** <https://github.com/jni/skan>  
**Language:** Python  
**Interface:** Python package  
**License:** BSD-3-Clause

Skan is not a skeletonizer. It takes a thin skeleton image and exposes it as graph/path data.

Its `Skeleton` representation provides:

- sparse pixel adjacency graph;
- path lists;
- path coordinates;
- path lengths;
- branch pruning;
- connectivity/degree analysis;
- conversion to graph-oriented workflows.

Conceptually:

```python
from skan import Skeleton

sk = Skeleton(skeleton_image)

for path_index in range(sk.n_paths):
    coords = sk.path_coordinates(path_index)
    length = sk.path_lengths()[path_index]
```

### Why it matters

A production centerline algorithm is mostly a **graph cleanup problem after skeletonization**. Skan provides a mature representation for that stage rather than forcing you to reinvent pixel-neighbor traversal and branch extraction.

---

## 6.8 `skeleton-tracing` — turn skeleton pixels into polylines

**Repository:** <https://github.com/LingDong-/skeleton-tracing>  
**License:** MIT

This project addresses a very specific and useful gap: traditional thinning produces a **raster skeleton**, while downstream SVG needs **ordered coordinates**.

The algorithm takes a binary skeleton and returns sets of polylines.

Implementations are present for many environments, including:

- JavaScript;
- WebAssembly;
- Python;
- C;
- C++;
- Rust;
- Swift;
- C#/Unity;
- Go;
- Java;
- additional languages/frameworks.

### Best use

```text
scikit-image/OpenCV thinning
        ↓
skeleton-tracing
        ↓
polyline arrays
        ↓
fit-curve / Paper.js
        ↓
SVG Béziers
```

### Caveat

The repository is more of a multi-language reference/source distribution than a polished single package with one universal package-manager experience. Depending on runtime, vendoring the implementation or using the WASM/JS variant may be appropriate.

---

## 6.9 Tegaki — unusually relevant full reference pipeline

**Repository:** <https://github.com/gkurt/tegaki>  
**Language/runtime:** TypeScript + Bun  
**License:** MIT

Tegaki's public product is animated handwriting generated from fonts. Its **internal generator** is directly relevant because font glyphs start as filled vector outlines and need to become stroke-like centerline animations.

The repository documents this internal pipeline:

```text
Font download
→ parse outlines
→ adaptive Bézier flattening
→ rasterize
→ skeletonize
→ trace skeleton pixels into polylines
→ prune short spurs / RDP simplify
→ compute width from distance transform
→ group/order/orient strokes
→ JSON / animated SVG output
```

Its generator supports multiple skeletonization approaches:

- Zhang-Suen;
- Guo-Hall;
- Lee;
- morphological thinning;
- distance-transform medial axis;
- Voronoi-based medial axis.

### Why this is important

Most individual libraries stop at the skeleton. Tegaki demonstrates the **entire downstream problem**:

- branch/spur removal;
- width estimation;
- connected-component grouping;
- stroke orientation;
- stroke ordering.

Those are exactly the stages required to turn “a mathematically correct skeleton” into “something that can be drawn as strokes.”

### Important packaging caveat

The published `tegaki` npm package is the renderer. The repository documents `packages/generator` / `tegaki-generator` as an **internal CLI + library that is not published**. The website calls the same pipeline in-browser.

Therefore the practical options are:

1. study it as a reference implementation;
2. fork/vendor the generator modules;
3. adapt its processing stages to generic SVG shapes;
4. upstream/generalize the generator if the project accepts that scope.

It is not currently a drop-in `npm install tegaki-generator` solution.

---

## 6.10 Boost.Polygon Voronoi — strong native building block

**Docs:** <https://www.boost.org/doc/libs/latest/libs/polygon/doc/index.htm>  
**Language:** C++

Boost.Polygon includes a sweep-line implementation for constructing Voronoi diagrams from **points and line segments**. Its documentation explicitly notes the relationship to medial axes.

This can support a custom vector algorithm:

```text
SVG curves
→ adaptive flattening into line segments
→ Boost segment-site Voronoi
→ retain interior Voronoi edges
→ classify boundary generators
→ prune graph
→ fit smooth centerline curves
```

### Advantages

- native performance;
- robust, mature Boost ecosystem;
- line-segment sites are better than naïvely sampling only isolated boundary points;
- total control over filtering/pruning.

### Disadvantages

- not turnkey;
- SVG parsing/flattening is your responsibility;
- clipping and classifying Voronoi edges requires nontrivial geometry code;
- output still needs semantic stroke reconstruction.

Use this when a custom C++ geometry core is justified, not for the fastest prototype.

---

## 6.11 PostGIS `CG_ApproximateMedialAxis`

**Docs:** <https://postgis.net/docs/CG_ApproximateMedialAxis.html>

PostGIS 3.5+ exposes:

```sql
SELECT CG_ApproximateMedialAxis(geom)
```

The function returns an approximate medial axis for areal input using SFCGAL and is based on a **straight skeleton**.

### Why it is interesting

- completely programmatic SQL interface;
- convenient if geometry is already in PostGIS;
- can be exposed behind a small service without writing computational geometry code.

### Why it is not a first choice

The PostGIS documentation explicitly says it is based on a straight skeleton. As discussed above, that is not generally the Euclidean medial axis desired for smooth strokes.

This also requires PostgreSQL/PostGIS/SFCGAL, so it is a comparatively heavy dependency if the application does not already use that stack.

---

## 6.12 CGAL Straight Skeleton 2

**Docs:** <https://doc.cgal.org/latest/Straight_skeleton_2/index.html>  
**Language:** C++

CGAL provides a high-quality implementation of straight skeletons and polygon offsetting.

The most important fact is in CGAL's own documentation: a straight skeleton is only *similar* to a medial axis; in general its bisectors are equidistant to the **supporting lines** of polygon edges and may not lie in the geometric center of a non-convex polygon.

### Assessment

CGAL is an excellent geometry library, but this particular construction is not automatically the right construction for centerlining pen strokes.

Use it if:

- the shapes are polygonal and the deviation is acceptable;
- straight skeleton behavior happens to align with your artwork;
- an existing C++ stack makes it cheap to test.

Do not choose it merely because the name “skeleton” sounds like the target operation.

---

# 7. Supporting tools that make a production pipeline much easier

## 7.1 `resvg` — deterministic SVG rasterization

**Repository:** <https://github.com/linebender/resvg>  
**Interfaces:** Rust library, C library, CLI; portable to WASM  
**License:** MIT or Apache-2.0

If a raster fallback is needed, rasterization quality and reproducibility matter. `resvg` is a strong choice because it is specifically built as a static SVG renderer and emphasizes deterministic output across supported platforms.

Recommended role:

```text
arbitrary SVG input
→ resvg at controlled scale
→ binary alpha mask
→ medial axis / thinning
```

This is preferable to ad hoc browser screenshots or platform-dependent rendering when reproducible conversion matters.

---

## 7.2 SVGPathCommander — SVG normalization

**Repository:** <https://github.com/thednp/svg-path-commander>  
**Language:** TypeScript  
**License:** MIT

Useful capabilities include:

- manipulate SVG `d` data;
- convert shapes such as circles/rectangles to paths;
- apply transforms to path commands;
- reverse path direction;
- geometric path utilities.

It does **not** compute centerlines, but it can remove a lot of SVG-format plumbing before handing clean loops to `flo-mat` or a polygonizer.

---

## 7.3 Paper.js — flattening, smoothing, simplification

**Docs:** <https://paperjs.org/reference/path/>

Paper.js `Path.simplify(tolerance)` fits as few curves as possible through path anchor points subject to an allowed maximum error. `Path.flatten(flatness)` performs the inverse style of operation by approximating curves with line segments.

Useful roles:

- flattening curves for a polygon/Voronoi backend;
- converting traced polyline skeletons into compact smooth curves;
- geometric nearest-point/containment operations during validation.

---

## 7.4 `fit-curve` — small focused Bézier fitting package

**Repository:** <https://github.com/soswow/fit-curve>  
**npm:** `fit-curve`  
**License:** MIT

This JavaScript implementation of Philip J. Schneider's Graphics Gems fitting algorithm takes a polyline and returns one or more cubic Bézier curves.

```js
const fitCurve = require('fit-curve');

const points = [[0, 0], [10, 10], [20, 12], [30, 5]];
const error = 1.0;
const cubicBeziers = fitCurve(points, error);
```

It is an excellent final stage after raster skeleton tracing.

---

# 8. Tools that look relevant but solve the wrong problem

## 8.1 Potrace

**Site:** <https://potrace.sourceforge.net/>

Potrace is excellent at raster **outline tracing**, but its own FAQ explicitly says it does **not** provide centerline tracing and that centerline algorithms are fundamentally different.

For this problem, feeding an image to Potrace simply recreates the boundary that you already have.

## 8.2 VTracer

**Repository:** <https://github.com/visioncortex/vtracer>

VTracer is a modern raster-to-vector converter designed to create compact SVG shapes from raster images. It is a contour/vectorization tool, not a centerline/stroke-recovery system.

## 8.3 ImageTracer / ImageTracerJS

Likewise, ImageTracer converts raster regions into SVG vector shapes. Useful for vectorization, but not for extracting the center path of an existing filled stroke.

## 8.4 Old Inkscape centerline extension

**Repository:** <https://github.com/fablabnbg/inkscape-centerline-trace>

This extension is historically informative because it demonstrates a practical centerline workflow, including threshold selection, but it is now archived and explicitly delegates the core work to `autotrace -centerline`. The repository notes that later Inkscape versions integrated AutoTrace-based centerline tracing.

For automation, use AutoTrace directly rather than depending on this old Python 2 extension.

---

# 9. Recommended architecture: vector-first with raster fallback

A robust application should avoid betting everything on one algorithm.

## 9.1 Stage 0: preserve source semantics

Before geometry processing:

- keep distinct SVG elements distinct;
- retain source element IDs;
- retain fill colors if they distinguish strokes;
- do not flatten all shapes into one union unless necessary;
- record transforms before baking them into geometry.

This is the cheapest and most powerful source of semantic information available.

## 9.2 Stage 1: normalize SVG

For each candidate filled stroke shape:

1. apply nested transforms to coordinates;
2. convert primitive shapes to paths;
3. resolve compound paths and fill rules;
4. ensure loops are closed;
5. separate disconnected components;
6. remove zero-area/degenerate segments;
7. normalize coordinates into a convenient scale.

Possible helper: SVGPathCommander.

## 9.3 Stage 2A: vector extraction

```text
normalized closed Bézier loops
        ↓
flo-mat findMats()
        ↓
MAT graph
        ↓
toScaleAxis() at candidate scales
        ↓
branch scoring and pruning
```

Do not assume a single global SAT scale will be optimal. Evaluate several values and score the reconstruction.

## 9.4 Stage 2B: raster fallback

```text
normalized SVG
    ↓
resvg render at high controlled resolution
    ↓
binary mask
    ↓
scikit-image medial_axis(return_distance=True)
    ↓
Skan or skeleton-tracing
    ↓
branch graph + local widths
```

Raster resolution should be defined **relative to stroke width**, not just image dimensions.

A reasonable starting benchmark is to ensure the typical stroke is represented by at least roughly 12–32 pixels across its width. More pixels improve subpixel recovery but increase runtime and memory.

## 9.5 Stage 3: graph cleanup

Represent the result as a graph:

- degree 1 → endpoint;
- degree 2 → ordinary continuation point;
- degree 3+ → junction;
- each maximal degree-2 chain → candidate stroke segment.

Then prune and merge.

## 9.6 Stage 4: stroke reconstruction

At each junction, consider candidate pairings using:

1. tangent continuity;
2. curvature continuity;
3. local width similarity;
4. source element identity;
5. angle through the junction;
6. whether the pairing creates implausibly short strokes.

For a four-way X, the two pairs with the smallest change in tangent direction are usually strong candidates for the two original crossing strokes.

## 9.7 Stage 5: fit final curves

If the extracted centerline is a polyline:

- run Ramer-Douglas-Peucker for noise reduction if needed;
- fit cubic Béziers using `fit-curve` or Paper.js `simplify()`;
- preserve exact endpoints and junction positions where topology matters.

## 9.8 Stage 6: determine orientation/order

Direction cannot generally be recovered from a static filled shape, so use deterministic heuristics unless another information source exists.

Possible orientation rules:

- prefer top-to-bottom for mostly vertical strokes;
- prefer left-to-right for mostly horizontal strokes;
- choose the endpoint nearest a chosen origin;
- preserve original source-element ordering as a weak hint;
- for a child-tracing experience, choose the direction that produces the simplest/most natural gesture.

Order multiple strokes using:

- source DOM order if meaningful;
- spatial reading order;
- connected-component order;
- application-specific gesture heuristics.

Treat order as a separate optimization from centerline geometry.

---

# 10. Branch pruning: probably the most important custom logic

A raw medial axis is sensitive to tiny shape irregularities. Generic branch removal based only on length can remove real detail or keep ugly artifacts.

For stroke-like artwork, use **width-aware pruning**.

## 10.1 Useful branch features

For each terminal branch, calculate:

```text
L = branch arc length
R_med = median local radius
R_parent = radius near the branch's junction
ΔR = variation in radius along the branch
θ = tangent relationship to the parent/main path
```

Then useful normalized features include:

```text
L / (2 R_med)             # length in units of local stroke width
R_med / R_global          # branch scale relative to dominant stroke
std(R) / mean(R)          # width consistency
```

A tiny spur that is 0.15 stroke widths long should usually be treated differently from a branch three stroke widths long, regardless of absolute SVG units.

## 10.2 Repeated prune/reconstruct evaluation

Instead of selecting one hand-tuned threshold, generate candidate skeletons at several pruning strengths, re-stroke each, and select a Pareto-optimal result balancing:

- reconstruction fidelity;
- total centerline length;
- number of branches;
- number of control points;
- width consistency.

This turns pruning into model selection.

---

# 11. Reconstruction-based validation

This is the single most valuable quality technique to add.

Given candidate centerline `C` and inferred width `w`, generate:

```text
S_reconstructed = stroke_to_fill(C, w)
```

and compare it with original shape `S_original`.

## 11.1 Useful metrics

### Intersection over Union

```text
IoU = area(intersection) / area(union)
```

Easy to understand; good aggregate measure.

### Symmetric difference area

```text
area(S_original XOR S_reconstructed)
```

Very useful optimization loss.

### Boundary distance

Measure nearest-distance error between the reconstructed and original boundaries. Report both median and a high percentile such as P95/P99; a maximum can be dominated by one pathological point.

### Centerline complexity

Track:

- number of strokes;
- number of branches;
- number of Bézier segments;
- total centerline length.

Among two reconstructions with nearly identical geometry error, prefer the simpler path graph.

### Width error

If a constant-width model is desired, penalize variation in estimated local radii along the selected centerline.

---

# 12. Suggested benchmark suite

Before choosing a dependency, create a small deterministic corpus containing synthetic shapes plus representative real artwork.

## 12.1 Synthetic ground-truth shapes

Generate filled shapes from known source centerlines so the true answer is available.

Include:

1. horizontal straight line;
2. diagonal straight line;
3. circular arc;
4. S curve;
5. tight U curve;
6. closed loop;
7. round-capped stroke;
8. butt-capped stroke;
9. square-capped stroke;
10. round join;
11. bevel join;
12. miter join;
13. X crossing, kept as separate source shapes;
14. X crossing, boolean-unioned;
15. T junction;
16. Y junction;
17. almost-touching parallel lines;
18. small self-overlap;
19. variable-width stroke;
20. noisy vectorized boundary.

For each, retain the source open path so error can be measured against both:

- the ground-truth path;
- the reconstructed filled region.

## 12.2 Real examples

Add representative production artwork covering:

- simple isolated strokes;
- dense drawings;
- curves near other curves;
- overlaps;
- imperfect vectorization;
- multiple colors/elements;
- very short marks/dots.

## 12.3 Evaluate each backend

At minimum compare:

- `flo-mat` raw MAT;
- `flo-mat` SAT at several scale values;
- AutoTrace centerline at several raster resolutions;
- PyGeoOps centerline;
- scikit-image medial axis + custom graph processing;
- OpenCV thinning + skeleton tracing;
- Tegaki-derived algorithms if adapted.

Collect:

- centerline Hausdorff/P95 distance to known source path where available;
- reconstruction IoU;
- symmetric-difference area;
- branch count;
- endpoint count;
- runtime;
- output path complexity.

---

# 13. Recommended proof-of-concept sequence

Rather than building the whole system at once, de-risk it in this order.

## Experiment 1 — establish baselines

Run the same 20–50 shapes through:

1. `flo-mat`;
2. AutoTrace centerline;
3. PyGeoOps;
4. scikit-image medial axis.

Do not implement sophisticated pruning yet. The purpose is to learn which geometry backend best preserves the expected centerline.

## Experiment 2 — classify failure modes

Tag every failure:

- cap artifact;
- join artifact;
- outline noise branch;
- crossing ambiguity;
- disconnected skeleton;
- missing narrow segment;
- wrong endpoint;
- excessive curve complexity;
- raster quantization.

This identifies where application-specific logic actually earns its complexity.

## Experiment 3 — add width-aware pruning

Implement a common graph representation so vector and raster backends can share the same pruning/reconstruction layer.

Suggested normalized graph model:

```ts
interface CenterlineNode {
  id: string;
  x: number;
  y: number;
  radius?: number;
}

interface CenterlineEdge {
  id: string;
  from: string;
  to: string;
  geometry: Bezier[] | Point[];
  length: number;
  medianRadius?: number;
  sourceElementId?: string;
}
```

## Experiment 4 — re-stroke scoring

For several prune strengths, reconstruct the filled stroke and calculate geometric error. Select the simplest graph that remains within a chosen reconstruction tolerance.

## Experiment 5 — stroke semantics

Only after centerline geometry is stable, implement:

- branch pairing;
- stroke grouping;
- direction;
- order.

Keeping semantic inference separate makes the geometry layer much easier to test.

---

# 14. Concrete implementation choices by runtime

## TypeScript / Node / browser

### Preferred

```text
SVGPathCommander
    ↓
flo-mat
    ↓
custom graph/pruning layer
    ↓
SVG output
```

### Raster fallback

```text
resvg / resvg-WASM or browser-compatible renderer
    ↓
medial-axis/thinning implementation
    ↓
skeleton-tracing JS/WASM
    ↓
fit-curve or Paper.js
```

### Reference code worth studying

Tegaki's internal TypeScript generator.

---

## Python service / offline tool

### Preferred customizable pipeline

```text
SVG rasterizer or SVG→polygon converter
    ↓
scikit-image medial_axis(return_distance=True)
    ↓
Skan
    ↓
custom pruning
    ↓
curve fitting / SVG serialization
```

### Fast polygon prototype

```text
SVG → flattened Shapely Polygon
    ↓
pygeoops.centerline()
```

### Independent baseline

```text
centerline.geometry.Centerline
```

---

## Native C/C++

### Easiest end-to-end

`libautotrace` after rasterization.

### Custom vector geometry

Boost.Polygon Voronoi with segment sites.

### Straight-skeleton experiment

CGAL Straight Skeleton 2, understanding that the result is not a general Euclidean medial axis.

---

## SQL / service sidecar

PostGIS/SFCGAL `CG_ApproximateMedialAxis` can be useful for experimentation if PostGIS is already available, but is too heavy and too straight-skeleton-oriented to recommend solely for this feature.

---

# 15. Determinism considerations

For undo/state management or cached conversion, deterministic output is desirable.

### Vector backend

A purely geometric `flo-mat` pipeline should be deterministic for fixed inputs and parameters, subject to ordinary floating-point behavior.

Persist:

- normalized input `d`;
- library version;
- MAT tolerance/order settings;
- SAT scale;
- pruning thresholds;
- final centerline output.

### Raster backend

For determinism, pin:

- renderer and version;
- raster dimensions/scale;
- antialiasing strategy;
- threshold rule;
- skeletonizer and parameters;
- random seed where an API exposes tie-breaking randomness;
- curve-fitting tolerance.

Using a deterministic renderer such as `resvg` is attractive for this reason.

---

# 16. Performance considerations

### Vector MAT

Runtime is driven by boundary complexity and geometric computation. Simplifying pathological outlines before MAT computation can help, but aggressive simplification can change topology.

### Voronoi

Boundary densification is the main knob. Too sparse gives gaps or inaccurate centering; too dense increases memory/runtime.

### Raster

Pixel count dominates:

```text
work ∝ width × height
```

Doubling both image dimensions roughly quadruples the number of pixels processed.

Prefer choosing resolution based on **pixels per typical stroke width** and crop each connected component to a tight bounding box before skeletonization.

### Parallelization

Disconnected SVG elements/components can be processed independently and are natural units of parallel work.

---

# 17. Hosted API / SaaS landscape

No compelling specialist hosted API emerged from this review that clearly exposes **filled-shape → centerline stroke recovery** as a first-class operation.

Most commercial or hosted “vectorization” products focus on raster-to-outline conversion. That is not the same task.

The strongest programmatic ecosystem is therefore currently **local/open-source libraries and CLIs**, which is also beneficial for:

- deterministic behavior;
- no per-image API costs;
- offline operation;
- privacy;
- ability to customize pruning and stroke semantics.

If a hosted service is desired operationally, a small service wrapping one of the pipelines above is likely more controllable than depending on a general vectorization API.

---

# 18. Final ranking

## Tier 1 — prototype immediately

### 1. `flo-mat`

Best match for already-vectorized smooth SVG. It is the only package found that directly combines the right geometry model, SVG/Bézier input, JavaScript/TypeScript usability, and scale-aware medial-axis pruning.

### 2. AutoTrace

Best zero-custom-code centerline baseline. Keep it in the evaluation even if it does not become the production architecture.

### 3. scikit-image medial axis + Skan

Best foundation for a sophisticated raster backend. The distance field makes width-aware pruning much more powerful than ordinary thinning.

### 4. PyGeoOps

Best high-level Python polygon-centerline API found. Particularly attractive for rapid comparison because branch filtering and simplification are already exposed.

## Tier 2 — highly useful components/reference implementations

### 5. Tegaki generator

Exceptionally relevant end-to-end reference for turning filled outlines into animated strokes. Not packaged as a generic generator dependency, but likely worth studying closely.

### 6. skeleton-tracing

Very useful if any raster skeletonizer is chosen, especially for JS/WASM or cross-language deployment.

### 7. fit-curve / Paper.js

Strong final curve-fitting tools.

### 8. Boost.Polygon Voronoi

Best route to a fully controlled native vector implementation if the higher-level libraries prove inadequate.

## Tier 3 — situational

### 9. fitodic `centerline`

Useful Voronoi/GIS baseline, but less specifically tailored to smooth artistic strokes.

### 10. OpenCV thinning

Excellent primitive when OpenCV is already present, but only one stage of the pipeline.

### 11. PostGIS/SFCGAL approximate medial axis

Convenient SQL surface, but heavy and straight-skeleton based.

### 12. CGAL straight skeleton

High-quality library for a related geometric construction, but usually not the mathematical centerline wanted here.

---

# 19. Recommended technical direction

For the specific class of inputs described—**already-vectorized shapes representing fairly even-width pen strokes**—the strongest design is:

```text
                ┌─────────────────────┐
                │ Original SVG shapes │
                └──────────┬──────────┘
                           │
                 preserve element IDs
                           │
                ┌──────────▼──────────┐
                │  Normalize geometry │
                │ transforms/fill/etc │
                └──────────┬──────────┘
                           │
             ┌─────────────┴─────────────┐
             │                           │
   ┌─────────▼────────┐       ┌──────────▼─────────┐
   │ Vector backend    │       │ Raster fallback    │
   │ flo-mat MAT/SAT   │       │ resvg → medial axis│
   └─────────┬────────┘       └──────────┬─────────┘
             │                           │
             └─────────────┬─────────────┘
                           │
                ┌──────────▼──────────┐
                │ Common graph model  │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │ width-aware pruning │
                │ + junction pairing  │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │ curve fit / merge   │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │ re-stroke + compare │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │ final trace paths   │
                └─────────────────────┘
```

The most important architectural choice is the **common graph layer**. Once both vector and raster extractors emit the same nodes/edges/radius metadata, every difficult semantic operation—pruning, branch pairing, stroke grouping, ordering, validation—can be shared and tested independently from the extraction backend.

That also makes it possible to select a backend per shape:

- use `flo-mat` when it produces a clean vector skeleton;
- fall back to raster when a pathological SVG or MAT topology scores poorly;
- choose the result with better reconstruction/complexity metrics.

That hybrid strategy is likely to outperform a single universal algorithm on heterogeneous real-world drawings.

---

# 20. Primary sources and project links

The following were the principal first-party sources used for this report.

## Direct centerline / medial-axis tools

- **flo-mat / MAT:** <https://github.com/FlorisSteenkamp/MAT>
- **flo-mat documentation:** <https://mat-demo.appspot.com/docs/>
- **AutoTrace:** <https://github.com/autotrace/autotrace>
- **PyGeoOps centerline:** <https://pygeoops.readthedocs.io/en/stable/api/pygeoops.centerline.html>
- **PyGeoOps repository:** <https://github.com/pygeoops/pygeoops>
- **Python centerline:** <https://github.com/fitodic/centerline>
- **Python centerline docs:** <https://centerline.readthedocs.io/>
- **PostGIS `CG_ApproximateMedialAxis`:** <https://postgis.net/docs/CG_ApproximateMedialAxis.html>

## Raster skeletonization / graph extraction

- **scikit-image morphology:** <https://scikit-image.org/docs/stable/api/skimage.morphology.html>
- **OpenCV ximgproc thinning:** <https://docs.opencv.org/4.13.0/df/d2d/group__ximgproc.html>
- **Skan:** <https://skeleton-analysis.org/>
- **Skan repository:** <https://github.com/jni/skan>
- **skeleton-tracing:** <https://github.com/LingDong-/skeleton-tracing>
- **Tegaki:** <https://github.com/gkurt/tegaki>

## Computational geometry

- **CGAL Straight Skeleton 2:** <https://doc.cgal.org/latest/Straight_skeleton_2/index.html>
- **Boost.Polygon / Voronoi:** <https://www.boost.org/doc/libs/latest/libs/polygon/doc/index.htm>

## SVG preprocessing / rasterization / fitting

- **resvg:** <https://github.com/linebender/resvg>
- **SVGPathCommander:** <https://github.com/thednp/svg-path-commander>
- **Paper.js Path API:** <https://paperjs.org/reference/path/>
- **fit-curve:** <https://github.com/soswow/fit-curve>

## Useful negative comparisons

- **Potrace:** <https://potrace.sourceforge.net/>
- **Potrace FAQ (explicitly discusses lack of centerline tracing):** <https://potrace.sourceforge.net/faq.html>
- **VTracer:** <https://github.com/visioncortex/vtracer>
- **Archived Inkscape Centerline Trace extension:** <https://github.com/fablabnbg/inkscape-centerline-trace>

## Background on scale-aware medial-axis pruning

- **The Scale Axis Transform — ETH research collection:** <https://www.research-collection.ethz.ch/handle/20.500.11850/152561>
- **The Scale Axis Transform — EPFL/Infoscience record:** <https://infoscience.epfl.ch/entities/publication/86ade44c-5af7-4804-b924-eb295a88d30d>

---

## Bottom line

There is **not yet a single universally best package that accepts arbitrary filled SVG and returns the exact original human stroke paths with correct order**. That last part is fundamentally underdetermined for merged geometry.

There *are*, however, enough high-quality third-party components that the core computational geometry does not need to be invented from scratch.

The shortest path to a high-quality implementation is:

1. prototype `flo-mat` on the actual SVGs;
2. establish AutoTrace and scikit-image as independent raster baselines;
3. normalize all outputs into one centerline graph representation;
4. make pruning width-aware;
5. infer stroke semantics at graph junctions separately;
6. re-stroke every candidate and score how well it reconstructs the original shape;
7. retain a raster fallback for cases where the vector MAT behaves poorly.

That approach directly exploits the fact that the source is already vector geometry while still keeping a robust escape hatch for pathological shapes.
