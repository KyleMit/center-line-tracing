"""Visual verification: recovered centerlines in red over the source fill in grey.

This exists to catch coordinate/scale round-trip errors BEFORE any number is
believed -- the handoff calls that out as the most common source of
misleadingly bad scores for a rasterise-then-trace backend.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from PIL import Image

from svgio import Document, Renderer

SCRATCH = Path("/tmp/claude-0/-home-user-center-line-tracing/"
               "06888930-c1d3-5025-96f2-3d47c53efe6c/scratchpad/autotrace-work/overlay")


def hairline(svg_text: str, width: float) -> str:
    """Force every stroke-width to a hairline, so we see path *position* only."""
    return re.sub(r'stroke-width="[^"]*"', f'stroke-width="{width:g}"', svg_text)


def render(renderer, svg, box, scale):
    m, f = renderer.mask(svg, box, scale)
    return m, f


def write_overlay(input_svg: Path, out_svg_text: str, dest: Path, px=1400,
                  crop=None):
    """grey source fill + red hairline centerlines + red filled reconstruction ghost."""
    doc = Document(input_svg)
    box = crop or (doc.vx, doc.vy, doc.vw, doc.vh)
    scale = px / max(box[2], box[3])
    r = Renderer(SCRATCH)
    try:
        src, f = render(r, input_svg.read_text(), box, scale)
        rec, _ = render(r, out_svg_text, box, scale)
        line, _ = render(r, hairline(out_svg_text, max(box[2], box[3]) / px * 1.6),
                         box, scale)
    finally:
        r.close()
    h = min(src.shape[0], rec.shape[0], line.shape[0])
    w = min(src.shape[1], rec.shape[1], line.shape[1])
    src, rec, line = src[:h, :w], rec[:h, :w], line[:h, :w]

    img = np.full((h, w, 3), 255, np.uint8)
    img[src] = (185, 185, 185)               # source fill, grey 40%-ish
    img[rec & ~src] = (255, 190, 190)        # reconstruction spilling outside
    img[line] = (220, 20, 20)                # traced centerline, hairline red
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(dest)
    return dest


def write_quad(input_svg: Path, out_svg_text: str, dest: Path, px=700):
    """input | output | diff | overlay, side by side."""
    doc = Document(input_svg)
    box = (doc.vx, doc.vy, doc.vw, doc.vh)
    scale = px / max(box[2], box[3])
    r = Renderer(SCRATCH)
    try:
        src, f = render(r, input_svg.read_text(), box, scale)
        rec, _ = render(r, out_svg_text, box, scale)
        line, _ = render(r, hairline(out_svg_text, max(box[2], box[3]) / px * 1.6),
                         box, scale)
    finally:
        r.close()
    h = min(src.shape[0], rec.shape[0], line.shape[0])
    w = min(src.shape[1], rec.shape[1], line.shape[1])
    src, rec, line = src[:h, :w], rec[:h, :w], line[:h, :w]

    def panel(fn):
        p = np.full((h, w, 3), 255, np.uint8)
        fn(p)
        return p

    a = panel(lambda p: p.__setitem__(src, (40, 40, 40)))
    b = panel(lambda p: p.__setitem__(rec, (40, 40, 40)))

    d = np.full((h, w, 3), 255, np.uint8)
    d[src & rec] = (220, 220, 220)
    d[src & ~rec] = (30, 90, 220)   # missing
    d[rec & ~src] = (220, 30, 30)   # extra
    o = np.full((h, w, 3), 255, np.uint8)
    o[src] = (185, 185, 185)
    o[line] = (220, 20, 20)

    strip = np.concatenate([a, b, d, o], axis=1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(strip).save(dest)
    return dest
