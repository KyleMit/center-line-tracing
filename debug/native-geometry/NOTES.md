# Track 7 — Native Geometry Engines (`native-geometry`)

Report §6.10 (Boost.Polygon Voronoi), §6.12 (CGAL Straight Skeleton 2),
§6.11 (PostGIS `CG_ApproximateMedialAxis`), §4.5.

**Verdict in one line:** Boost.Polygon's *segment-site* Voronoi is a genuine,
numerically exact Euclidean medial axis and it works — mean IoU **0.9944** as a
medial-axis transform and **0.9636** as a constant-width re-stroke across all ten
real inputs, 0.9–2.5 s per image, ~600 lines of code total. The integration cost
is real but small and one-time. The straight-skeleton engines are **not** the
disaster the report expects on stroke-shaped artwork — the honest reason to skip
them is cost and robustness, not geometry, and that distinction is recorded below.

---

## 1. What was built

```
SVG ─ svgpoly.py ─→ shapely polygons ─→ [engine] ─→ CenterlineGraph ─→ re-stroke ─→ metrics
     (adaptive flattening,          boost: cpp/voronoi_medial      (common graph model,
      even-odd rings)               cgal:  cpp/straight_skeleton    §13 Experiment 3)
```

| file | role |
|---|---|
| `experiments/native-geometry/cpp/voronoi_medial.cpp` | Boost.Polygon segment-site Voronoi kernel; emits finite primary edges + clearance radius |
| `experiments/native-geometry/cpp/straight_skeleton.cpp` | CGAL `create_interior_straight_skeleton_2`; emits inner skeleton edges + offset time |
| `py/svgpoly.py` | SVG → flattened polygons. **Shared by all engines** so the comparison is clean |
| `py/backend_boost.py`, `py/backend_cgal.py` | engine adapters → common graph model |
| `py/graph.py` | common graph model, chain contraction, tip pruning, re-stroke |
| `py/metrics.py` | IoU / symmetric difference / boundary distance / centerline error / clearance error / complexity |
| `py/synthetic.py` | 23-case ground-truth corpus |
| `py/run.py` | one re-runnable `bench` command |
| `py/sheets.py` | contact sheets (PNG + HTML) |

Build (both kernels, ~15 s):

```bash
apt-get install -y libboost-dev libcgal-dev
g++ -O2 -std=c++17 cpp/voronoi_medial.cpp    -o cpp/voronoi_medial
g++ -O2 -std=c++17 cpp/straight_skeleton.cpp -o cpp/straight_skeleton -lgmp -lmpfr
python3 py/synthetic.py debug/native-geometry/synthetic
python3 py/run.py bench --set synthetic --engine boost
python3 py/run.py bench --set real --engine boost
```

### Reproducibility (report §15)

| knob | value | why |
|---|---|---|
| Boost | 1.83.0 (`libboost-dev` 1.83.0.1ubuntu2), header-only `boost/polygon/voronoi.hpp` | — |
| CGAL | 5.6-1build3, `Exact_predicates_inexact_constructions_kernel` | — |
| g++ | 13.3.0, `-O2 -std=c++17` | — |
| coordinate lattice | `SCALE = 100` → sites on a 0.01-user-unit integer lattice | Boost's Voronoi predicates are **exact for integer input**; this is where the "exact numerical control" actually comes from |
| polygon snapping | `shapely.set_precision(poly, 0.01)` before segment extraction | the polygon we containment-test against is *identical* to the sites the kernel sees; also guarantees non-crossing sites |
| curve flattening | 0.05 user units, adaptive midpoint subdivision | |
| parabola discretization | 0.1 user units chord tolerance | Voronoi edges between a point site and a segment site are parabolic arcs |
| clearance filter | `r_eps = 0.25` user units | |
| tip pruning | `k = 1.0` (drop leaf chains shorter than the clearance radius at their anchor) | swept, see §5 |
| output simplification | RDP 0.1 user units, applied only when writing the stroke path | graph JSON keeps full precision; see §5 |

Runs are deterministic: same input → byte-identical graph JSON. Nothing samples,
nothing seeds an RNG, and no metric is measured on pixels.

---

## 2. Headline result — Boost segment Voronoi

Every real input, `bench --set real --engine boost`:

| image | IoU (stroke) | IoU (MAT) | boundary med / p95 | strokes | ms |
|---|---|---|---|---|---|
| house-wide | 0.9776 | 0.9967 | 0.06 / 1.02 | 39 | 895 |
| butterfly-wide | 0.9685 | 0.9925 | 0.05 / 0.36 | 31 | 1115 |
| boat-tall | 0.9806 | 0.9957 | 0.05 / 0.29 | 38 | 1229 |
| island-tall | 0.9742 | 0.9940 | 0.06 / 0.52 | 61 | 1314 |
| balloon-tall | 0.9762 | 0.9942 | 0.05 / 0.39 | 67 | 1212 |
| home-wide | 0.9597 | 0.9953 | 0.09 / 1.09 | 60 | 958 |
| house-tall | 0.9742 | 0.9949 | 0.08 / 0.79 | 63 | 1606 |
| dinosaur-wide | 0.9672 | 0.9970 | 0.14 / 1.01 | 80 | 1587 |
| landscape-square | 0.9447 | 0.9942 | 0.12 / 3.34 | 147 | 2406 |
| sun-square | 0.9135 | 0.9895 | 0.35 / 4.06 | 32 | 169 |
| **mean** | **0.9636** | **0.9944** | | | |

The two IoU columns are the most important number this track produced.

* **IoU (MAT)** re-fills the shape from the *full* medial-axis transform — the
  union of inscribed discs using the per-point clearance radius the kernel
  computes. It measures the geometry engine alone.
* **IoU (stroke)** re-fills from the deliverable — one `<path>` per graph edge at
  one constant `stroke-width` (`2 × median radius`), round caps and joins, with
  the polyline simplified at 0.1 px. The table above is the unsimplified run;
  simplification costs 0.0005 mean IoU and 4.4× the file size.

**The engine is not the bottleneck.** At 0.989–0.997 MAT IoU, the axis and its
radius function describe the artwork almost exactly; every visible defect in the
re-stroked output comes from collapsing an edge to a single width and from
deciding which branches are strokes. That is Track 8's territory (§10, §11), and
this track hands it a graph that is already correct.

### Synthetic corpus (ground truth known)

23 cases; centerline error is measured against the *known* source path.

* Cases 1–4, 6, 7, 10–13, 15–17, 22 — **centerline median error 0.000–0.002 px,
  p95 ≤ 0.04 px** on a 400×300 canvas with radius 8. Case 1 recovers a 280.000 px
  line as 280.007 px at radius 7.99. This is exact recovery, not approximation.
* Cases 8, 9 (butt/square cap) — centerline error **0.0**, IoU 0.978/0.980. The
  axis is perfect; the loss is entirely that a round-capped re-stroke cannot
  reproduce a butt or square cap. Cap style is a *re-stroke* parameter to infer,
  not a geometry failure — tagged `cap artifact`.
* Case 19 (variable width) IoU 0.724, case 23 (taper) IoU 0.604 — with centerline
  error **0.000**. Same story, louder: the axis is exact, one stroke width cannot
  represent a tapered stroke. MAT IoU for these is 0.99+.
* Case 20 (noisy boundary) IoU 0.965 but **59 strokes / 29 branch nodes** — the
  predicted `outline noise branch` explosion. `k=1.0` tip pruning is not enough
  against boundary noise of 0.9 px on a radius-8 stroke.
* Case 5 (tight U) IoU 0.951 — the two arm tips are buried inside the U's own
  curve, their medial branches are shorter than the local radius, and pruning
  eats them: `wrong endpoint` / `missing narrow segment`. Visible as the two red
  blobs in `sheets/comparison-boost-synthetic.png`.
* Case 21 (shallow X crossing) IoU 0.964, centerline p95 4.9 — `crossing
  ambiguity`. At a shallow crossing the true medial axis genuinely leaves the
  drawn strokes; no engine can fix this, only stroke-level semantics can (§2.2).

Full numbers: `metrics-boost-synthetic.json`, `metrics-boost-real.json`.

---

## 3. Straight skeleton (CGAL) — the expected burial did not happen

The report (§3, §4.5, §6.12) predicts a straight skeleton will be visibly wrong
for pen strokes: bisectors equidistant from the *supporting lines* of edges, so
piecewise-straight geometry that cannot follow a curve, plus different cap
behaviour. **It ran the whole 23-case corpus and three real inputs and that is
not what the numbers say.**

| | Boost Voronoi | CGAL straight skeleton |
|---|---|---|
| synthetic mean IoU (23 cases) | 0.9617 | **0.9653** |
| synthetic mean IoU (MAT) | 0.9937 | **0.9962** |
| synthetic total strokes | **103** | 124 |
| synthetic total runtime | **1.2 s** | 537 s |
| real (first 3) mean IoU | 0.9756 | **0.9774** |
| real (first 3) strokes | **108** | 176 |
| real (first 3) runtime | **3.2 s** | 6.0 s |

Why the prediction misses: the divergence between an angular bisector and a true
medial bisector is concentrated at **reflex vertices**. A pen stroke is a ribbon
of near-constant width, and the bisector of two near-parallel offset edges is the
centerline under *either* definition. Densely flattening a smooth curve creates
many convex vertices and almost no reflex ones, so the two constructions agree
almost everywhere on this artwork.

Where they do diverge is exactly where theory says, and the `clearance_err`
metric isolates it. That metric asks the one question that defines a medial axis:
*is the radius stored at this node equal to the distance from the node to the
boundary?*

| case | Boost clearance err med / p95 | CGAL clearance err med / p95 |
|---|---|---|
| 05-tight-u | 0.003 / 0.006 | **0.295 / 2.630** |
| 14-x-crossing-union | 0.003 / 0.003 | 0.000 / **1.262** |
| 16-y-junction | 0.003 / 0.003 | **0.569 / 0.569** |
| 18-self-overlap | 0.002 / 0.002 | 0.000 / **0.614** |
| 20-noisy-boundary | 0.002 / 0.005 | 0.000 / **0.685** |
| everything else | ≈0.003 (the 0.01 lattice) | 0.000 |

So the straight skeleton **is** non-medial, but only at junctions, self-overlaps
and reflex corners — a localised error of 0.6–2.6 px, not a systematic one. Boost's
0.003 px floor is the coordinate lattice, i.e. the exactness knob, and it can be
lowered by raising `SCALE`.

**The real case against CGAL here is cost, not geometry:**

1. **Pathological runtimes.** Case 19 (variable width, a union of 400 discs)
   took **438 seconds**; Boost took 0.31 s — a 1400× gap. Case 23 (taper) took
   96 s vs 0.25 s. Both are ordinary polygons with many near-collinear vertices;
   that is what vectorized artwork looks like. A backend that occasionally takes
   seven minutes on a legal input is not deployable without a watchdog.
2. **A more fragmented graph** for the same picture (61 vs 39 strokes on
   house-wide, 65 vs 31 on butterfly-wide). Common Setup's tie-break — prefer
   the simpler graph — goes to Boost.
3. **No radius you can trust** at exactly the places pruning needs one most
   (junctions), per the clearance table.
4. Heavier dependency (`libcgal-dev` + gmp + mpfr, ~13 s to compile one TU vs
   ~2 s for the Boost tool), and GPL/LGPL licensing to check.

Straight skeletons are therefore still the wrong tool — but the reason to say so
is "slow, fragmented, and non-medial exactly where it matters", not "it can't
follow a curve". Nobody needs to spend another session on this; the code is in
the branch and `bench --engine cgal` reruns it in a minute.

---

## 4. PostGIS `CG_ApproximateMedialAxis` — deliberately skipped

Not attempted, per the handoff's own priority 3, and I would not spend the time
on a re-run either. The reasoning, so this is a decision and not an omission:

* PostGIS's own documentation says the function is **based on a straight
  skeleton**, implemented via SFCGAL — i.e. it is the CGAL construction of §3
  above, wrapped in SQL (report §6.11).
* Track 7 has now measured that construction directly, at the C++ level, with no
  database in the loop. Standing up PostgreSQL + PostGIS + SFCGAL could only
  reproduce §3's numbers with more moving parts and less control — it cannot
  produce a *different* geometric answer, and it has no knob the direct CGAL call
  lacks.
* The report already rates it "too heavy and too straight-skeleton-oriented to
  recommend solely for this feature" (§6.11, §18.11).

If the application ever already runs PostGIS, the one thing worth re-checking is
whether SFCGAL's approximation post-processes the skeleton differently from a raw
`create_interior_straight_skeleton_2` call. Nothing else about it is open.

---

## 5. Experiments run, including the ones that failed

| change | result | kept? |
|---|---|---|
| Segment sites (vs. the point sampling Track 4's libraries use) | exact medial axis; 130 boundary segments on case 1 give a 1-stroke, 0-branch answer | yes — this is the whole point of the track |
| Lattice snapping before site extraction | fixed NaN Voronoi vertices on case 20 (rounding had made boundary segments cross, which Boost's builder does not accept) | yes |
| Clearance filter `min(ra, rb) < r_eps` | removes the spoke every convex polygon vertex sends to the boundary; without it case 1 yields 139 strokes instead of 1 | yes |
| Chain contraction seeded from anchors only | **bug** — dropped every pure-cycle component (closed strokes: the cloud in house-wide, the sun ring, case 6) whenever another component in the same graph had anchors. Real-set mean IoU 0.851 → 0.965 when fixed | fixed |
| Degenerate-blob fallback | a dot's medial axis is a single point, so the Voronoi has no interior edge at all; emit a zero-length round-capped stroke at the inscribed centre | yes |
| Tip extension along the tangent ("cap extension by radius", §9.6) | **no-op, +0.0002 IoU.** The Voronoi axis of a round-capped stroke already ends exactly at the cap centre; there is nothing to extend. This technique is for raster/thinning backends whose skeletons stop short — it is not needed here | off by default (`--no-extend`), code kept |
| Stroke width = 40th / 25th percentile of edge radii instead of median | worse everywhere: real mean IoU 0.9636 → 0.9622 (p40) → 0.9541 (p25) | rejected, median kept |
| Polyline simplification (RDP) at 0.1 px before writing the stroke path | promoted output 1.5 MB → 340 kB (4.4×) for −0.0005 mean IoU; 0.3 px costs −0.004 | **0.1 px, adopted for the promoted SVGs** |
| Tip prune sweep on sun-square, `k ∈ {0, 0.5, 1, 2, 4}` | IoU 0.9114 / 0.9042 / **0.9135** / 0.9108 / 0.8662 with 151 / 69 / **32** / 30 / 24 strokes. `k=1` is both the best score and 5× simpler than no pruning | `k=1.0` |

Progress sheet for the sweep: `progress/progress-sun-square.png`.

---

## 6. Failure modes seen (report §13 Experiment 2 taxonomy)

| tag | where | cause |
|---|---|---|
| `cap artifact` | cases 8, 9; every butt/square-capped stroke | axis is exact; the re-stroke has only round caps |
| `outline noise branch` | case 20 (59 strokes), landscape-square | boundary noise creates real medial branches; `k=1` tip pruning is too weak |
| `crossing ambiguity` | cases 14, 21; sun-square | at a crossing the true medial axis leaves the drawn strokes — inherent (§2.2), needs stroke semantics |
| `wrong endpoint` / `missing narrow segment` | case 5 tight-U arm tips | tip branch shorter than the local radius, eaten by pruning |
| `excessive curve complexity` | landscape-square (147 strokes, 14 557 points) | no curve fitting yet — geometry is emitted as polylines |
| `raster quantization` | **none** | this is a fully vector pipeline; the only quantization is the 0.01 lattice |
| `disconnected skeleton` | CGAL only (extra components on cases 3, 6) | inner-edge filtering fragments the skeleton at contour vertices |

Not yet done, and honestly out of scope for this track: Bézier fitting of the
polyline geometry (§9.7 / `fit-curve`), and stroke-level pruning (Track 8). The
graph JSON in `graphs/boost/` is the handoff for both.

---

## 7. Answering the track's question

> Is a lower-level, numerically-controlled geometry kernel worth the integration
> cost?

**Yes, for Boost.Polygon, and the cost is lower than the report implies.** The
kernel is ~250 lines of C++ against a header-only, apt-installable dependency; a
day's work, not a project. What it buys:

* a **true Euclidean medial axis** with an exact clearance radius at every node —
  the radius is what width-aware pruning (§10) and width recovery (§11) both need,
  and it is free here rather than estimated;
* **segment sites**, so a flattened boundary of 130 segments produces one clean
  stroke where point-sampled Voronoi produces densification hair (the specific
  advantage §6.10 claims — confirmed);
* **exactness you can dial** (`SCALE`), with a measured 0.003 px floor at 0.01;
* determinism with no raster stage anywhere;
* 0.9–2.5 s for a whole illustration, single-threaded, subprocess overhead included.

Its cost is exactly what §6.10 says: flattening, interior classification and
pruning are yours to write. All three turned out to be short, and they are
written and benched in this branch.

The one caveat worth carrying forward: at MAT IoU 0.994 the geometry question is
essentially closed, and **every remaining point of quality lives in stroke
semantics** — pruning, junction resolution, width and cap inference, curve
fitting. If a higher-level library (Track 1's `flo-mat`, Track 4's PyGeoOps) hands
Track 8 a comparable graph with less code, prefer it. Boost is the answer to
"what if the higher-level libraries prove inadequate" (§6.10), and this branch
shows that answer works and how much it costs.

---

## 8. Artifacts

```
debug/native-geometry/
  NOTES.md                       this file
  metrics-boost-synthetic.json   23 cases, ground-truth centerline error
  metrics-boost-real.json        all 10 real inputs
  metrics-cgal-synthetic.json    23 cases
  metrics-cgal-real.json         first 3 real inputs (bounded probe)
  graphs/<engine>/<set>/*.json   common graph model — the cross-track deliverable
  restroke/<engine>/<set>/*.svg  re-stroked output
  synthetic/                     23 generated cases + ground-truth centerlines
  sheets/comparison-*.png|html   input | re-stroked | diff | overlay
  progress/progress-sun-square.png
outputs/native-geometry/*.svg    promoted results (Boost, all 10 real inputs)
```

Diff sheets read: grey = both, **red = original only** (missed), **blue =
reconstruction only** (extra). Overlay draws recovered centerlines in red,
junction nodes blue, endpoints green.
