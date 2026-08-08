#!/usr/bin/env python3
"""Build the publishable pages for this track.

    python3 experiments/pruning-scoring/pages/build.py            # -> debug/pruning-scoring/pages/

`findings.html` is already self-contained and is copied through unchanged. The
contact sheet is a template plus ~750 KB of inlined WebP: published pages cannot
fetch anything (a strict CSP blocks every external host), so the images have to be
data URIs, which is too much base64 to keep in a source file you would ever want to
read or diff. The template carries the markup and the build step injects the data.

Regenerate the inputs first if the pipeline changed:

    python3 experiments/pruning-scoring/recommended.py     # emit the SVGs
    node    experiments/pruning-scoring/sheet_assets.mjs   # render the WebP pairs

Published copies of both pages are linked from NOTES.md and the Track 8 handoff.
Rebuilding here does not update those — re-publish the built file to the same
artifact URL.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DEBUG = REPO / "debug" / "pruning-scoring"
OUT = DEBUG / "pages"

# Only the fields the page actually reads. The assets file also carries the
# per-cell provenance (source paths, timings, IoU, grade) that belongs in the
# record but would be dead weight in a published page.
FIELDS = (
    "image", "scale", "lam", "width", "height", "before", "after",
    "error", "wobble", "edgesEmitted", "edgesBeforePruning", "bytes", "sourceBytes",
)


def build_contact_sheet() -> Path:
    assets_path = DEBUG / "recommended" / "assets.json"
    if not assets_path.exists():
        sys.exit(f"missing {assets_path.relative_to(REPO)} — run sheet_assets.mjs first")
    assets = json.loads(assets_path.read_text())
    slim = [{k: rec[k] for k in FIELDS} for rec in assets]

    # The payload rides in a <script type="application/json"> island, and an HTML
    # parser ends that island at the first literal "</" regardless of context.
    # Nothing here should contain one, but escaping is cheaper than trusting it.
    blob = json.dumps(slim, separators=(",", ":")).replace("</", "<\\/")

    template = (HERE / "contact-sheet.template.html").read_text()
    if "/*__DATA__*/" not in template:
        sys.exit("template has no /*__DATA__*/ placeholder")
    out = OUT / "contact-sheet.html"
    out.write_text(template.replace("/*__DATA__*/", blob))
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sheet = build_contact_sheet()
    findings = OUT / "findings.html"
    shutil.copyfile(HERE / "findings.html", findings)
    for p in (findings, sheet):
        print(f"  {p.relative_to(REPO)}  {p.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
