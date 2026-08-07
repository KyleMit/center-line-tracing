"""Work out which SVG a graph file was extracted from.

Necessary because the seven tracks each generated their OWN synthetic corpus, in
their own directory, with their own naming. A graph must be scored against the
drawing it actually came from — score flo-mat's `20-noisy-boundary` against
polygon-voronoi's differently-generated case 20 and every number is meaningless
(measured: IoU 0.0000, because the shapes do not even overlap).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
INPUTS = REPO / "inputs"

# Per-track corpus directories, searched after inputs/.
CORPUS_DIRS = ("corpus", "synthetic", "synth")

# Variant suffixes tracks append to a graph filename. Order matters: longest first.
_VARIANT_SPLITTERS = ("__", "+")
_VARIANT_SUFFIXES = (
    "-sat13", "-pygeoops", "-fitodic", "-boost", "-cgal", "-filter", "-varwidth",
)
_PREFIXES = ("case-",)


def _stem_candidates(stem: str) -> list[str]:
    """Progressively strip variant decoration from a graph filename stem."""
    out: list[str] = []

    def push(s: str) -> None:
        if s and s not in out:
            out.append(s)

    push(stem)
    for splitter in _VARIANT_SPLITTERS:
        if splitter in stem:
            push(stem.split(splitter)[0])
    # dotted variants: house-wide.final -> house-wide
    base = out[-1]
    if "." in base:
        push(base.split(".")[0])
    for s in list(out):
        for suf in _VARIANT_SUFFIXES:
            if s.endswith(suf):
                push(s[: -len(suf)])
        for pre in _PREFIXES:
            if s.startswith(pre):
                push(s[len(pre):])
    # numeric-prefixed synthetic names sometimes differ only in the descriptive tail
    for s in list(out):
        m = re.match(r"^(\d{2})-", s)
        if m:
            push(m.group(1))
    return out


@lru_cache(maxsize=4096)
def _dir_index(directory: str) -> tuple[tuple[str, str], ...]:
    d = Path(directory)
    if not d.is_dir():
        return ()
    return tuple((p.stem, str(p)) for p in sorted(d.glob("*.svg")))


def resolve_source_svg(graph_path: str | Path, *, slug: str | None = None) -> Path | None:
    """Return the SVG a graph was extracted from, or None if it cannot be found."""
    gp = Path(graph_path)
    if not gp.is_absolute():
        gp = REPO / gp

    # 1. an explicit `source` field always wins
    try:
        doc = json.loads(gp.read_text())
    except Exception:  # noqa: BLE001
        doc = {}
    for candidate in (
        doc.get("source"),
        (doc.get("meta") or {}).get("source") if isinstance(doc.get("meta"), dict) else None,
    ):
        if isinstance(candidate, str) and candidate:
            p = Path(candidate)
            if not p.is_absolute():
                p = REPO / p
            if p.suffix.lower() == ".svg" and p.exists():
                return p

    # 2. fall back to name matching, inside this track's own directories first
    if slug is None:
        parts = gp.relative_to(REPO).parts
        slug = parts[1] if len(parts) > 2 and parts[0] == "debug" else None

    search: list[str] = []
    if slug:
        search += [str(REPO / "debug" / slug / d) for d in CORPUS_DIRS]
    search.append(str(INPUTS))

    stems = _stem_candidates(gp.stem)
    for directory in search:
        index = dict(_dir_index(directory))
        for stem in stems:
            if stem in index:
                return Path(index[stem])
        # numeric-prefix match: "20" matches "20-noisy-boundary.svg"
        for stem in stems:
            if re.fullmatch(r"\d{2}", stem):
                for cand_stem, path in _dir_index(directory):
                    if cand_stem.startswith(stem + "-"):
                        return Path(path)
    return None


def is_real_input(svg: Path | None) -> bool:
    """True when the drawing is one of the ten real inputs (not a synthetic case)."""
    return svg is not None and svg.parent.resolve() == INPUTS.resolve()


def track_slug(graph_path: str | Path) -> str:
    gp = Path(graph_path)
    if not gp.is_absolute():
        gp = REPO / gp
    parts = gp.relative_to(REPO).parts
    return parts[1] if len(parts) > 2 and parts[0] == "debug" else "unknown"


def image_key(svg: Path) -> str:
    """Canonical image name used to join results across tracks.

    Synthetic corpora differ per track, so their keys are prefixed to make it
    impossible to compare two tracks' case 20 as if they were the same drawing.
    """
    p = Path(svg)
    if is_real_input(p):
        return p.stem
    return f"synthetic:{p.stem}"
