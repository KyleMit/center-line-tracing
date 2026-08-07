# Track 8 — Width-Aware Pruning, Re-Stroke Scoring, Common Graph Layer

Slug `pruning-scoring` · branch `claude/centerline-pruning-scoring` · report §10, §11, §13, §19

> ## 📣 THE GRAPH SCHEMA IS PUBLISHED AND FROZEN: [`SCHEMA.md`](./SCHEMA.md)
>
> Version string `centerline-graph/1`. Run the validator against your own output:
>
> ```bash
> python3 experiments/pruning-scoring/validate_graphs.py debug/<your-slug>/graphs
> ```
>
> **All 387 graph files from all seven extraction tracks conform today.** The schema
> was written to describe what you already emit, so nothing should need to change.
> Two things are worth fixing on your side, both listed in SCHEMA.md: add the
> `"schema": "centerline-graph/1"` string, and (tegaki, flo-mat) check why edge
> geometry endpoints drift from their node coordinates by up to 13.7 user units.

---

## Log

### Day 1 — graph layer first

The situation is better than the handoff assumed: all seven extraction tracks had
already pushed and merged before this session started, so instead of bootstrapping
from the incumbent alone I have 387 real graph files spanning every backend. The
schema work therefore became descriptive rather than speculative — I wrote the
validator against the real corpus and fixed the *schema* wherever it disagreed with
data that was obviously correct.

One schema decision came directly out of that: **dot edges**. tegaki emits 227
edges whose geometry is a single point. My first validator called them errors. They
are not — they are isolated marks (single-pixel skeleton components), all of them
self-loops with `length == 0`, and rejecting them would mean silently deleting
artwork. Schema v1 admits them explicitly, with rules (`from == to`, `length == 0`,
`medianRadius` required to reconstruct).

Measured conformance, first full run:

| track | files | conform | notable |
|---|---|---|---|
| autotrace | 10 | 10 | no `schema` string |
| flo-mat | 42 | 42 | 28 files with endpoint drift |
| native-geometry | 59 | 59 | no `schema` string; 2 length mismatches |
| opencv-tracing | 24 | 24 | clean |
| polygon-voronoi | 50 | 50 | no `schema` string |
| skimage-skan | 84 | 84 | clean |
| tegaki | 118 | 118 | 87 files with endpoint drift (P99 8.3, max 13.7 units) |

The endpoint drift is the one finding that is not cosmetic: it is larger than a
stroke radius in places, which means node coordinates and edge geometry disagree
about where a stroke ends. The graph layer resolves this by **trusting `geometry`
and treating node coordinates as advisory**, since geometry is what gets
reconstructed and scored.
