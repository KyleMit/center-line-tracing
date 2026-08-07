#!/usr/bin/env python3
"""Canonical complexity, so complexity comparisons are actually fair.

Why this exists: the automatic pruning path canonicalizes (splices degree-2 chains)
before it prunes, and the tracks' published graphs generally do not. Comparing raw
edge counts therefore credits automatic pruning with a 6x "simplification" that is
mostly a change of REPRESENTATION — flo-mat's house-wide graph has 277 edges that
merge to 36 branches with no geometry removed at all.

So every complexity number in the reports is measured after canonicalization, on
both sides. What is left is the part pruning is actually responsible for.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clg import CenterlineGraph  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=2048)
def canonical_stats(graph_path: str) -> tuple[int, int, int, float]:
    """(branches, strokes, control points, total length) after chain merging."""
    p = Path(graph_path)
    if not p.is_absolute():
        p = REPO / p
    g = CenterlineGraph.load(p)
    g.merge_chains()
    s = g.stats()
    return (s["edges"], s["strokes"], s["controlPoints"], s["totalLength"])


def index(branches: float, control_points: float) -> float:
    """One readable number: branches + control points / 100."""
    return branches + control_points / 100.0


def canonical_index(graph_path: str) -> float:
    b, _, cp, _ = canonical_stats(graph_path)
    return index(b, cp)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        b, s, cp, ln = canonical_stats(arg)
        print(f"{arg}: branches {b} strokes {s} controlPoints {cp} "
              f"length {ln:.1f} index {index(b, cp):.1f}")
