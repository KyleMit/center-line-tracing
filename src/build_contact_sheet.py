#!/usr/bin/env python3
"""Build the reviewable contact sheet: docs/contact-sheet.html.

    python3 src/run.py                    # emit the SVGs
    node    src/render_pairs.mjs          # render the matched WebP pairs
    python3 src/build_contact_sheet.py    # -> docs/contact-sheet.html

The sheet is one row per drawing, source against traced output, with a
drag-to-wipe comparison and a difference view. Open the file in a browser; it is
self-contained and needs no server.

It has to be self-contained because that is the only form in which a reviewer can
be handed it, so the images ride inside the page as data URIs — about 780 KB of
base64, which is far too much to keep in a source file anyone would want to read
or diff. The template carries the markup; this step injects the data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ASSETS = REPO / "runs" / "sheet-assets.json"
OUT = REPO / "docs" / "contact-sheet.html"

# Only the fields the page actually reads. The assets file also carries per-cell
# provenance (source paths, timings, IoU, grade) that belongs in the record but
# would be dead weight in the page.
FIELDS = (
    "image", "scale", "lam", "width", "height", "before", "after",
    "error", "wobble", "edgesEmitted", "edgesBeforePruning", "bytes", "sourceBytes",
)


def main() -> int:
    if not ASSETS.exists():
        sys.exit(f"missing {ASSETS.relative_to(REPO)} — run `node src/render_pairs.mjs` first")
    assets = json.loads(ASSETS.read_text())
    slim = [{k: rec[k] for k in FIELDS} for rec in assets]

    # The payload rides in a <script type="application/json"> island, and an HTML
    # parser ends that island at the first literal "</" regardless of context.
    # Nothing here should contain one, but escaping is cheaper than trusting it.
    blob = json.dumps(slim, separators=(",", ":")).replace("</", "<\\/")

    template = (HERE / "contact-sheet.template.html").read_text()
    if "/*__DATA__*/" not in template:
        sys.exit("template has no /*__DATA__*/ placeholder")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(template.replace("/*__DATA__*/", blob))
    print(f"  {OUT.relative_to(REPO)}  {OUT.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
