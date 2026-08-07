#!/usr/bin/env python3
"""Investigate the "some tracers emit outlines for thick structures" failure.

Traces every element of one drawing, prints the per-subpath evidence used by the
outline detector, and dumps a crop of any element that trips it so the verdict
can be checked by eye rather than trusted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

import atrace  # noqa: E402
import pipeline  # noqa: E402
import width as W  # noqa: E402
from svgio import Document, Renderer  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
DEBUG = REPO / "debug" / "autotrace"
SCRATCH = Path("/tmp/claude-0/-home-user-center-line-tracing/"
               "06888930-c1d3-5025-96f2-3d47c53efe6c/scratchpad/autotrace-inspect")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--scale", type=float, default=4.0)
    ap.add_argument("--outline-frac", type=float, default=0.40)
    a = ap.parse_args()

    inp = REPO / "inputs" / f"{a.image}.svg"
    doc = Document(inp)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    r = Renderer(SCRATCH)
    outdir = DEBUG / "mixed" / a.image
    outdir.mkdir(parents=True, exist_ok=True)
    flagged = 0
    try:
        for el in doc.elements:
            box = pipeline._bbox_of(doc, r, [el], 2.0)
            if box is None:
                continue
            mask, frame = r.mask(doc.sub_svg([el], box), box, a.scale)
            if not mask.any():
                continue
            dist = W.edt(mask)
            sps, _, _ = atrace.run(mask, SCRATCH / "at", atrace.TraceParams(), stem=el.eid)
            r_shape = W.measure(sps, mask, dist, "trimmed", outline_frac=a.outline_frac)
            hits = [s for s in sps if s.outline_like]
            line = (f"{el.eid} {el.tag:7s} fill={el.fill} r_shape={r_shape:5.2f}px "
                    f"subpaths={len(sps):3d} outline_like={len(hits)}")
            if hits:
                flagged += 1
                for s in hits:
                    line += (f"\n    med_edt={s.stats['radius_median_px']:.2f}px "
                             f"len={s.stats['length_px']:.0f}px "
                             f"closed={s.stats['closed']} "
                             f"(threshold {max(1.6, a.outline_frac * r_shape):.2f}px)")
                # dump a picture so the verdict can be checked by eye
                img = np.full((*mask.shape, 3), 255, np.uint8)
                img[mask] = (200, 200, 200)
                for s in sps:
                    pts = np.round(s.points()).astype(int)
                    ok = ((pts[:, 0] >= 0) & (pts[:, 0] < mask.shape[1])
                          & (pts[:, 1] >= 0) & (pts[:, 1] < mask.shape[0]))
                    pts = pts[ok]
                    col = (220, 20, 20) if s.outline_like else (20, 90, 220)
                    img[pts[:, 1], pts[:, 0]] = col
                Image.fromarray(img).save(outdir / f"{el.eid}.png")
            print(line, flush=True)
    finally:
        r.close()
    print(f"\n{flagged} of {len(doc.elements)} elements tripped the outline detector "
          f"-> {outdir}")


if __name__ == "__main__":
    main()
