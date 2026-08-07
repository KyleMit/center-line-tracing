#!/usr/bin/env python3
"""Contact sheets (Common Setup): comparison sheet + progress sheet.

Comparison sheet -- one row per image, four columns (input | output | diff |
overlay), labelled with filename, IoU and pixel-diff %, plus zoomed crops of
the worst regions.  Progress sheet -- one tile per iteration for the focus
image, in chronological order, so the trajectory is visible at a glance.

Both are emitted as PNG (viewable without a browser) and HTML.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))

from overlay import hairline, render  # noqa: E402
from svgio import Document, Renderer  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
DEBUG = REPO / "debug" / "autotrace"
SHEETS = DEBUG / "sheets"
TILE = 430  # >= 400px per tile so individual strokes stay legible


def _font(size=17):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _fit(mask_img: np.ndarray, w, h):
    im = Image.fromarray(mask_img)
    im.thumbnail((w, h), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    canvas.paste(im, ((w - im.width) // 2, (h - im.height) // 2))
    return canvas


def panels(input_svg: Path, out_svg_text: str, px=1100, box=None):
    doc = Document(input_svg)
    box = box or (doc.vx, doc.vy, doc.vw, doc.vh)
    scale = px / max(box[2], box[3])
    r = Renderer(DEBUG / "scratch")
    try:
        src, _ = render(r, input_svg.read_text(), box, scale)
        rec, _ = render(r, out_svg_text, box, scale)
        line, _ = render(r, hairline(out_svg_text, max(box[2], box[3]) / px * 1.8),
                         box, scale)
    finally:
        r.close()
    h = min(src.shape[0], rec.shape[0], line.shape[0])
    w = min(src.shape[1], rec.shape[1], line.shape[1])
    src, rec, line = src[:h, :w], rec[:h, :w], line[:h, :w]

    a = np.full((h, w, 3), 255, np.uint8); a[src] = (35, 35, 35)
    b = np.full((h, w, 3), 255, np.uint8); b[rec] = (35, 35, 35)
    d = np.full((h, w, 3), 255, np.uint8)
    d[src & rec] = (225, 225, 225)
    d[src & ~rec] = (30, 90, 220)
    d[rec & ~src] = (220, 30, 30)
    o = np.full((h, w, 3), 255, np.uint8)
    o[src] = (188, 188, 188)
    o[line] = (215, 20, 20)
    return a, b, d, o, (src ^ rec)


def worst_crops(diff_mask, n=3, win=None):
    """Bounding boxes of the densest error regions, for the zoomed crops."""
    h, w = diff_mask.shape
    win = win or max(40, min(h, w) // 7)
    from scipy import ndimage
    dens = ndimage.uniform_filter(diff_mask.astype(np.float32), win)
    out = []
    d = dens.copy()
    for _ in range(n):
        idx = int(np.argmax(d))
        cy, cx = divmod(idx, w)
        if d[cy, cx] <= 0:
            break
        out.append((cx, cy, win))
        y0, y1 = max(0, cy - win), min(h, cy + win)
        x0, x1 = max(0, cx - win), min(w, cx + win)
        d[y0:y1, x0:x1] = 0
    return out


def comparison_sheet(label: str, images: list, dest_png: Path, dest_html: Path):
    store = json.loads((DEBUG / "metrics.json").read_text())
    entry = store[label]
    rows, html = [], []
    f, fs = _font(19), _font(15)

    for im in images:
        out = DEBUG / "runs" / label / f"{im}.svg"
        inp = REPO / "inputs" / f"{im}.svg"
        if not out.exists():
            continue
        m = entry["images"].get(im, {})
        a, b, d, o, xor = panels(inp, out.read_text())
        cells = [_fit(x, TILE, TILE) for x in (a, b, d, o)]

        crops = worst_crops(xor, 3)
        ccells = []
        for (cx, cy, win) in crops:
            y0, y1 = max(0, cy - win), min(d.shape[0], cy + win)
            x0, x1 = max(0, cx - win), min(d.shape[1], cx + win)
            cc = np.concatenate([o[y0:y1, x0:x1], d[y0:y1, x0:x1]], axis=1)
            ccells.append(_fit(cc, TILE, TILE // 2))

        head = 30
        rw = TILE * 4
        rh = TILE + head + (TILE // 2 + 22 if ccells else 0)
        row = Image.new("RGB", (rw, rh), (255, 255, 255))
        dr = ImageDraw.Draw(row)
        dr.text((6, 6), f"{im}.svg   diff {m.get('compare_js_pct', float('nan')):.2f}%   "
                        f"IoU {m.get('iou', float('nan')):.4f}   "
                        f"strokes {m.get('n_strokes', '?')}   "
                        f"bP95 {m.get('boundary_p95_user', float('nan')):.2f}u",
                (10, 10, 10), font=f)
        for i, c in enumerate(cells):
            row.paste(c, (i * TILE, head))
        for i, t in enumerate(("input", "output", "diff (blue=missing red=extra)", "overlay")):
            dr.text((i * TILE + 6, head + TILE - 20), t, (90, 90, 90), font=fs)
        if ccells:
            yy = head + TILE + 20
            dr.text((6, head + TILE + 2), "worst regions (overlay | diff)", (90, 90, 90), font=fs)
            for i, c in enumerate(ccells):
                row.paste(c, (i * TILE, yy))
        rows.append(row)
        html.append(
            f"<h3>{im}.svg — diff {m.get('compare_js_pct', 0):.2f}% · "
            f"IoU {m.get('iou', 0):.4f} · strokes {m.get('n_strokes', '?')}</h3>")

    if not rows:
        raise SystemExit(f"no outputs for label {label}")
    W = max(r.width for r in rows)
    H = sum(r.height + 12 for r in rows) + 46
    sheet = Image.new("RGB", (W, H), (250, 250, 250))
    dr = ImageDraw.Draw(sheet)
    dr.text((10, 12), f"autotrace -centerline + EDT width recovery — {label} "
                      f"({entry['config']})", (10, 10, 10), font=_font(23))
    y = 46
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height + 12
    dest_png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest_png)

    dest_html.write_text(
        "<meta charset=utf-8><style>body{font:14px system-ui;background:#fafafa;"
        "margin:24px}img{max-width:100%;border:1px solid #ddd}</style>"
        f"<h1>autotrace centerline — {label}</h1><p><code>{entry['config']}</code></p>"
        + "".join(html) + f'<img src="{dest_png.name}">')
    return dest_png


def progress_sheet(image: str, labels: list, dest_png: Path, dest_html: Path):
    store = json.loads((DEBUG / "metrics.json").read_text())
    f, fs = _font(16), _font(13)
    tiles = []
    for lab in labels:
        out = DEBUG / "runs" / lab / f"{image}.svg"
        if not out.exists():
            continue
        m = store.get(lab, {}).get("images", {}).get(image, {})
        _, _, d, o, _ = panels(REPO / "inputs" / f"{image}.svg", out.read_text(), px=800)
        cell = Image.new("RGB", (TILE, TILE + 46), (255, 255, 255))
        cell.paste(_fit(o, TILE, TILE // 2), (0, 24))
        cell.paste(_fit(d, TILE, TILE // 2), (0, 24 + TILE // 2))
        dr = ImageDraw.Draw(cell)
        dr.text((5, 3), lab, (10, 10, 10), font=f)
        dr.text((5, TILE + 26),
                f"diff {m.get('compare_js_pct', float('nan')):.2f}%  "
                f"IoU {m.get('iou', float('nan')):.4f}", (30, 30, 120), font=fs)
        tiles.append(cell)
    if not tiles:
        raise SystemExit("no tiles")
    cols = min(4, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * TILE, rows * (TILE + 46) + 40), (250, 250, 250))
    ImageDraw.Draw(sheet).text((10, 10), f"progress — {image}.svg (chronological)",
                               (10, 10, 10), font=_font(21))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * TILE, 40 + (i // cols) * (TILE + 46)))
    dest_png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest_png)
    dest_html.write_text(
        "<meta charset=utf-8><style>body{font:14px system-ui;margin:24px}"
        "img{max-width:100%}</style>"
        f"<h1>progress — {image}.svg</h1><img src='{dest_png.name}'>")
    return dest_png


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comparison", metavar="LABEL")
    ap.add_argument("--images", nargs="*", default=None)
    ap.add_argument("--progress", metavar="IMAGE")
    ap.add_argument("--labels", nargs="*", default=None)
    a = ap.parse_args()
    SHEETS.mkdir(parents=True, exist_ok=True)
    if a.comparison:
        store = json.loads((DEBUG / "metrics.json").read_text())
        imgs = a.images or sorted(store[a.comparison]["images"])
        p = comparison_sheet(a.comparison, imgs,
                             SHEETS / f"comparison-{a.comparison}.png",
                             SHEETS / f"comparison-{a.comparison}.html")
        print("->", p)
    if a.progress:
        p = progress_sheet(a.progress, a.labels or [],
                           SHEETS / f"progress-{a.progress}.png",
                           SHEETS / f"progress-{a.progress}.html")
        print("->", p)


if __name__ == "__main__":
    main()
