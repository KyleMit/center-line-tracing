"""Stroke semantics — report §13 Experiment 5. INTERFACES ONLY, deliberately.

The report is explicit that branch pairing, stroke grouping, direction and order
come AFTER centerline geometry is stable, and that keeping semantic inference
separate is what makes the geometry layer testable. So this module defines the
seams and does not implement the inference:

  * `StrokeGrouper` — the protocol an implementation must satisfy;
  * `StrokeGroup`   — the result type, so downstream code can be written now;
  * `read_stroke_order` — reads the ONE piece of stroke semantics that already
    exists in the corpus (tegaki emits per-edge `strokeOrder`), so it survives a
    round trip through this layer instead of being silently dropped.

When Experiment 5 is opened, an implementation registers here and everything
downstream (serialization, scoring, sheets) already knows what to do with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class StrokeGroup:
    """One inferred pen stroke: an ordered run of edges through the graph.

    `edges` is the traversal order; `reversed_edges` marks the ones traversed
    against their stored `from -> to` direction, which is what a direction-aware
    consumer needs and what a naive edge list loses.
    """

    id: str
    edges: list[str] = field(default_factory=list)
    reversed_edges: set[str] = field(default_factory=set)
    order: int | None = None          # index within the drawing, if known
    confidence: float | None = None
    source: str | None = None         # which implementation produced this
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "edges": list(self.edges),
            "reversed": sorted(self.reversed_edges),
            **({"order": self.order} if self.order is not None else {}),
            **({"confidence": self.confidence} if self.confidence is not None else {}),
            **({"source": self.source} if self.source else {}),
            **({"meta": self.meta} if self.meta else {}),
        }


@runtime_checkable
class StrokeGrouper(Protocol):
    """What an Experiment 5 implementation has to provide.

    Pairing branches at a junction (which two legs are the same pen stroke passing
    through) is the hard part; grouping and ordering fall out of it. An
    implementation gets the finished, pruned graph and returns groups — it must not
    modify the geometry, which is the whole point of the separation.
    """

    def group(self, graph) -> list[StrokeGroup]:
        ...


def read_stroke_order(graph) -> list[StrokeGroup]:
    """Recover stroke groups from `strokeOrder` metadata a backend already emitted.

    tegaki is currently the only track producing this (report §9.8 / §6.9 — its
    generator is the one reference implementation of stroke ordering we have). This
    is a reader, not an inference: it reports what the backend claimed, so the
    information is not lost when a graph passes through pruning and scoring.
    """
    groups: list[StrokeGroup] = []
    for edge in graph.edges.values():
        so = edge.extra.get("strokeOrder")
        if not isinstance(so, dict):
            continue
        groups.append(
            StrokeGroup(
                id=f"s{so.get('index', len(groups))}",
                edges=[edge.id],
                reversed_edges={edge.id} if so.get("reversed") else set(),
                order=so.get("index"),
                source="backend:strokeOrder",
                meta={k: v for k, v in so.items()
                      if k in ("direction", "class", "t")},
            )
        )
    groups.sort(key=lambda g: (g.order is None, g.order))
    return groups


def has_stroke_semantics(graph) -> bool:
    return any("strokeOrder" in e.extra for e in graph.edges.values())
