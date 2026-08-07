"""Contact sheets for the `opencv-tracing` track.

Two kinds, both required by Common Setup:

* **Comparison sheet** — one row per image: `input | output | diff | overlay`,
  labelled with filename, IoU and pixel-diff %, plus zoomed crops of the worst
  regions.
* **Progress sheet** — one tile per iteration for the current focus image, in
  chronological order, so the trajectory is visible at a glance.

Both are written as HTML *and* PNG so they can be read without a browser.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TILE = 440
LABEL_H = 34


def _font(size=15):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_svg(svg_path: Path, width: int, out_png: Path) -> Image.Image:
    """Rasterize an SVG to RGBA at a fixed width, through the same resvg build."""
    payload = json.dumps({
        "outDir": str(out_png.parent), "scale": 1, "pad": 0,
        "originX": 0, "originY": 0,
        "jobs": [{"id": out_png.stem, "svg": svg_path.read_text()}],
        "forceWidth": width,
    })
    out_png.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["node", str(HERE / "render_one.mjs"), str(width)],
                   input=payload.encode("utf-8"), capture_output=True, check=True)
    return Image.open(out_png).convert("RGBA")


def _flatten(img: Image.Image, background=(255, 255, 255)) -> Image.Image:
    flat = Image.new("RGB", img.size, background)
    flat.paste(img, mask=img.split()[-1])
    return flat


def _fit(img: Image.Image, size=TILE, background=(255, 255, 255)) -> Image.Image:
    tile = Image.new("RGB", (size, size), background)
    scale = min(size / img.width, size / img.height)
    resized = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                         Image.LANCZOS)
    tile.paste(resized, ((size - resized.width) // 2, (size - resized.height) // 2))
    return tile


def diff_image(a: Image.Image, b: Image.Image):
    """Red = only in input, blue = only in output, grey = both. Returns (img, pct)."""
    size = (max(a.width, b.width), max(a.height, b.height))
    aa = np.array(a.resize(size, Image.LANCZOS))
    bb = np.array(b.resize(size, Image.LANCZOS))
    ink_a = aa[..., 3] > 128
    ink_b = bb[..., 3] > 128

    out = np.full((*size[::-1], 3), 255, np.uint8)
    out[ink_a & ink_b] = (190, 190, 190)
    out[ink_a & ~ink_b] = (220, 30, 30)
    out[~ink_a & ink_b] = (30, 60, 220)
    pct = 100.0 * np.count_nonzero(ink_a ^ ink_b) / ink_a.size
    return Image.fromarray(out), pct, (ink_a ^ ink_b)


def overlay_image(source: Image.Image, hairline: Image.Image) -> Image.Image:
    """Recovered centerlines in red over the source fill in grey at 40%.

    `hairline` must be the thin-stroke render, not the re-stroked output — at
    full stroke width the centerline covers exactly the thing you are trying to
    inspect.
    """
    size = (max(source.width, hairline.width), max(source.height, hairline.height))
    src = np.array(source.resize(size, Image.LANCZOS))
    rec = np.array(hairline.resize(size, Image.LANCZOS))
    out = np.full((*size[::-1], 3), 255, np.uint8)
    fill = src[..., 3] > 40
    out[fill] = (169, 169, 169)                      # 40% black on white
    line = rec[..., 3] > 100
    out[line] = (220, 20, 20)
    return Image.fromarray(out)


def worst_crops(diff_mask: np.ndarray, source: Image.Image, recovered: Image.Image,
                count=3, window=None) -> list:
    """The `count` densest windows of disagreement, as side-by-side crops."""
    h, w = diff_mask.shape
    window = window or max(60, min(h, w) // 6)
    step = max(1, window // 2)
    scored = []
    for y in range(0, max(1, h - window), step):
        for x in range(0, max(1, w - window), step):
            scored.append((int(diff_mask[y:y + window, x:x + window].sum()), x, y))
    scored.sort(reverse=True)

    picked = []
    for score, x, y in scored:
        if score <= 0:
            break
        if any(abs(x - px) < window and abs(y - py) < window for _, px, py in picked):
            continue
        picked.append((score, x, y))
        if len(picked) >= count:
            break

    src = source.resize((w, h), Image.LANCZOS)
    rec = recovered.resize((w, h), Image.LANCZOS)
    crops = []
    for score, x, y in picked:
        box = (x, y, x + window, y + window)
        pair = Image.new("RGB", (window * 2 + 6, window), (230, 230, 230))
        pair.paste(_flatten(src.crop(box)), (0, 0))
        pair.paste(_flatten(rec.crop(box)), (window + 6, 0))
        crops.append((score, pair))
    return crops


def label_tile(img: Image.Image, text: str, sub: str = "") -> Image.Image:
    out = Image.new("RGB", (img.width, img.height + LABEL_H), (245, 245, 245))
    out.paste(img, (0, 0))
    draw = ImageDraw.Draw(out)
    draw.text((6, img.height + 3), text, fill=(20, 20, 20), font=_font(15))
    if sub:
        draw.text((6, img.height + 18), sub, fill=(90, 90, 90), font=_font(12))
    return out


def comparison_sheet(rows: list, out_stem: Path, title: str):
    """rows: [{name, input_svg, output_svg, iou, sym, tags}]"""
    tiles = []
    html_rows = []
    for row in rows:
        work = out_stem.parent / "_render"
        src = render_svg(row["input_svg"], 900, work / f"{row['name']}-in.png")
        rec = render_svg(row["output_svg"], 900, work / f"{row['name']}-out.png")
        diff, pct, diff_mask = diff_image(src, rec)
        hair = render_svg(row["hairline_svg"], 900, work / f"{row['name']}-hair.png") \
            if row.get("hairline_svg") else rec
        over = overlay_image(src, hair)

        strip = [
            label_tile(_fit(_flatten(src)), row["name"], "input fill"),
            label_tile(_fit(_flatten(rec)), f"IoU {row['iou']:.4f}", "re-stroked output"),
            # NOTE: this is a coarse 900px preview diff computed here, NOT the
            # incumbent's src/compare.js number at 1200px. They are not
            # comparable — compare.js numbers live in debug/opencv-tracing/
            # pixel-diff.json and in NOTES.md.
            label_tile(_fit(diff), f"preview diff {pct:.2f}% (900px)",
                       "red=input only, blue=output only"),
            label_tile(_fit(over), row.get("tagline", ""), "centerlines over fill"),
        ]
        crops = worst_crops(diff_mask, src, rec)
        for i, (score, crop) in enumerate(crops):
            strip.append(label_tile(_fit(crop), f"worst region {i + 1}", "source | recovered"))

        band = Image.new("RGB", (TILE * len(strip), TILE + LABEL_H), (245, 245, 245))
        for i, tile in enumerate(strip):
            band.paste(tile, (i * TILE, 0))
        tiles.append(band)
        row["pixelDiffPct"] = pct

        html_rows.append(
            f"<tr><th>{row['name']}</th><td>IoU {row['iou']:.4f}</td>"
            f"<td>sym {row['sym'] * 100:.2f}%</td><td>preview diff {pct:.2f}%</td>"
            f"<td>{row.get('tagline', '')}</td></tr>")

    if tiles:
        width = max(t.width for t in tiles)
        sheet = Image.new("RGB", (width, sum(t.height for t in tiles)), (245, 245, 245))
        y = 0
        for tile in tiles:
            sheet.paste(tile, (0, y))
            y += tile.height
        sheet.save(out_stem.with_suffix(".png"))

    out_stem.with_suffix(".html").write_text(_html(title, out_stem.name + ".png", html_rows))
    return rows


def progress_sheet(entries: list, out_stem: Path, title: str):
    """entries: [{tag, score, output_svg, input_svg}] in chronological order."""
    tiles = []
    html_rows = []
    work = out_stem.parent / "_render"
    for i, entry in enumerate(entries):
        rec = render_svg(entry["output_svg"], 900, work / f"prog-{i:02d}.png")
        tiles.append(label_tile(_fit(_flatten(rec)), f"{i + 1}. {entry['tag']}",
                                entry["score"]))
        html_rows.append(f"<tr><th>{i + 1}. {entry['tag']}</th><td>{entry['score']}</td></tr>")

    if tiles:
        per_row = 4
        rows = (len(tiles) + per_row - 1) // per_row
        sheet = Image.new("RGB", (TILE * min(per_row, len(tiles)),
                                  rows * (TILE + LABEL_H)), (245, 245, 245))
        for i, tile in enumerate(tiles):
            sheet.paste(tile, ((i % per_row) * TILE, (i // per_row) * (TILE + LABEL_H)))
        sheet.save(out_stem.with_suffix(".png"))
    out_stem.with_suffix(".html").write_text(_html(title, out_stem.name + ".png", html_rows))


def _html(title: str, png_name: str, rows: list) -> str:
    return f"""<!doctype html><meta charset="utf-8"><title>{title}</title>
<style>
body{{font:14px/1.5 system-ui,sans-serif;margin:24px;background:#fafafa;color:#222}}
table{{border-collapse:collapse;margin:16px 0}}
th,td{{border:1px solid #ddd;padding:4px 10px;text-align:left}}
th{{background:#f0f0f0;font-weight:600}}
img{{max-width:100%;border:1px solid #ccc;background:#fff}}
</style>
<h1>{title}</h1>
<table>{''.join(rows)}</table>
<img src="{png_name}" alt="{title}">
"""
