# Centerline Graph Schema — `centerline-graph/1`

**Status: FROZEN.** This is the interface Tracks 1–7 write and Track 8 reads.
Breaking changes require a new version string, never an edit to this one.

Normative implementation: `experiments/pruning-scoring/clg/schema.py`.
Validator (run it against your own output):

```bash
python3 experiments/pruning-scoring/validate_graphs.py debug/<your-slug>/graphs
python3 experiments/pruning-scoring/validate_graphs.py --all --strict   # everyone
```

Exit code 0 = no errors. As of the latest run, **387/387 graph files across all
seven extraction tracks conform** — the schema below was derived from what the
tracks already emit, not imposed on them.

---

## Document

```jsonc
{
  "schema": "centerline-graph/1",   // REQUIRED (warn if absent; "schemaVersion" accepted as an alias)
  "backend": "flo-mat",             // recommended: which extractor produced this
  "image":   "house-wide",          // recommended: input stem, for cross-track joins
  "source":  "inputs/house-wide.svg",
  "units":   "svg-user",            // all coordinates are in the SOURCE SVG user space
  "viewBox": [0, 0, 1024, 768],     // optional; object form {x,y,w,h} also accepted
  "radiusSource": "native",         // "native" | "derived" — see below
  "nodes": [ ... ],                 // REQUIRED
  "edges": [ ... ],                 // REQUIRED
  "meta":  { }                      // free-form; also: options, params, stats, raster
}
```

**Coordinates are always in the original SVG user space.** A backend that works in
raster pixels must map back before serializing. This is the single most important
rule — everything downstream (scoring against the source fill, cross-backend
comparison) assumes it.

`radiusSource` is `"native"` when radius comes from the algorithm itself (a true
MAT, or `medial_axis(return_distance=True)`) and `"derived"` when it was recovered
afterwards by sampling a distance transform. Both are fine; the scorer records which.

## `CenterlineNode`

```jsonc
{ "id": "n12", "x": 512.5, "y": 300.25, "radius": 6.1, "degree": 3 }
```

| field | required | meaning |
|---|---|---|
| `id` | yes | unique non-empty string |
| `x`, `y` | yes | finite, SVG user units |
| `radius` | strongly recommended | local stroke radius (half-width) at this node |
| `degree` | no | informational; the graph layer recomputes it |

Without `radius`, width-aware pruning degrades to length-only pruning — which the
report (§10) says is exactly the thing that does not work. Emit it.

## `CenterlineEdge`

```jsonc
{
  "id": "e7", "from": "n12", "to": "n13",
  "geometry": [[512.5, 300.2], [520.0, 301.1], ...],
  "geometryType": "polyline",
  "length": 84.3,
  "medianRadius": 6.0,
  "radiusProfile": [6.1, 6.0, 5.9, ...],
  "sourceElementId": "path23",
  "closed": false
}
```

| field | required | meaning |
|---|---|---|
| `id` | yes | unique non-empty string |
| `from`, `to` | yes | node ids that must exist in `nodes` |
| `geometry` | yes | see encodings below |
| `length` | yes | arc length in user units |
| `geometryType` | no | `"polyline"` \| `"beziers"`; inferred when absent |
| `medianRadius` | strongly recommended | median local radius along the edge |
| `radiusProfile` | recommended | per-vertex radius; `radii` accepted as an alias |
| `sourceElementId` | recommended | id of the filled element this came from |
| `closed` | no | edge is a closed loop (`from == to`, non-zero length) |

### Geometry encodings — all three are legal

| form | example | used by |
|---|---|---|
| `polyline-pairs` | `[[x,y], [x,y], ...]` | autotrace, opencv-tracing, skimage-skan, native-geometry |
| `polyline-objects` | `[{"x":x,"y":y}, ...]` | polygon-voronoi, tegaki |
| `beziers` | `[[[x,y],[x,y],[x,y],[x,y]], ...]` (cubic segments) | flo-mat |

The graph layer normalizes all three to a flattened polyline (tolerance 0.05 user
units) and retains the bezier form when present, so control-point complexity is
scored honestly rather than being inflated by flattening.

### Dot edges

An edge with **exactly one** geometry point is a **dot** — an isolated mark with no
extent. It must satisfy `from == to` and `length == 0`, and it needs
`medianRadius` to be reconstructible. This form was adopted because tegaki emits
227 of them for single-pixel skeleton components; they are real marks, not noise,
and deleting them would silently lose artwork.

---

## Conventions the validator checks

1. Node and edge ids are unique; `from`/`to` resolve to declared nodes.
2. `geometry` has ≥ 2 points (or exactly 1, as a dot).
3. `length` is within 5% of the polyline length of `geometry` (beziers exempt).
4. Edge geometry endpoints sit on their referenced nodes (warn beyond 0.1% of the
   coordinate magnitude).
5. All numbers finite; radii ≥ 0.

Unknown keys are **preserved, never rejected** — they surface as notes. Extension
fields already in use and reserved by name: `beziers`, `corners`, `branchType`,
`meanRadius`, `minRadius`, `maxRadius`, `radiusCv`, `radiusStd`, `normLength`,
`widthRuns`, `outlineLike`, `strokeOrder`, `sourceElementFill`.

## Known conformance notes (as measured, not hypothetical)

| finding | tracks affected | impact |
|---|---|---|
| `schema` string absent | autotrace, native-geometry, polygon-voronoi (119 files) | cosmetic — add `"schema": "centerline-graph/1"` |
| edge geometry endpoints drift from node coords | tegaki (87 files, P99 8.3 units, max 13.7), flo-mat (28 files) | **not cosmetic** — larger than a stroke radius in places. The graph layer trusts `geometry` and treats node coords as advisory. Likely cap extension applied to geometry but not written back to the node. |
| `radiusProfile` length ≠ vertex count | widespread (4168 edges) | handled — the layer resamples the profile onto the vertices |
| `length` mismatch | native-geometry (2 files) | minor |

## Using the library

```python
import sys; sys.path.insert(0, "experiments/pruning-scoring")
from clg import CenterlineGraph

g = CenterlineGraph.load("debug/flo-mat/graphs/house-wide-sat13.json")
g.merge_chains()                 # splice degree-2 chains: canonical form for counting
print(g.stats())                 # nodes, edges, strokes, terminals, junctions, length
for edge, tip, anchor in g.terminal_edges():
    ...                          # every prunable branch, oriented tip -> anchor
```
