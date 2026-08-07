"""Contact sheets: the visual deliverable.

Three kinds:
  * comparison  — one row per image: input | output | diff | overlay
  * progress    — one tile per pruning strength, in order, for one image
  * cross-backend — one row per image, one column per backend (Track 8's own
                    artifact: how the whole parallel effort gets read at the end)

Metrics are proxies. These sheets exist so the numbers can be checked against the
render, which is the only way to catch over-pruning that scores well.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[3]
RENDER_JS = REPO / "experiments" / "pruning-scoring" / "render.mjs"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

TILE = 420          # >= 400px per tile so individual strokes stay legible
LABEL_H = 34
PAD = 8
BG = (250, 250, 250)
INK = (20, 20, 20)


def _font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_PATH, size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def render_svgs(jobs: list[dict]) -> None:
    """Batch-render SVG -> PNG through resvg."""
    if not jobs:
        return
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(jobs, fh)
        spec = fh.name
    subprocess.run(["node", str(RENDER_JS), spec], cwd=REPO, capture_output=True, text=True)


def _load_tile(png: Path | str, size: int = TILE) -> Image.Image:
    tile = Image.new("RGB", (size, size), (255, 255, 255))
    try:
        im = Image.open(png).convert("RGBA")
    except Exception:  # noqa: BLE001
        d = ImageDraw.Draw(tile)
        d.text((size // 2 - 30, size // 2), "n/a", fill=(180, 180, 180), font=_font(20))
        return tile
    im.thumbnail((size, size), Image.LANCZOS)
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    tile.paste(bg.convert("RGB"), ((size - im.width) // 2, (size - im.height) // 2))
    return tile


def overlay_image(input_png: Path | str, recon_png: Path | str, size: int = TILE) -> Image.Image:
    """Recovered centerlines in red over the input fill in grey at 40%."""
    base = _load_tile(input_png, size).convert("RGB")
    grey = Image.new("RGB", base.size, (255, 255, 255))
    faded = Image.blend(grey, base.convert("L").convert("RGB"), 0.40)
    rec = _load_tile(recon_png, size).convert("L")
    red = Image.new("RGB", base.size, (220, 30, 30))
    mask = rec.point(lambda v: 255 if v < 200 else 0)
    out = faded.copy()
    out.paste(red, (0, 0), mask)
    return out


def diff_image(a_png: Path | str, b_png: Path | str, size: int = TILE) -> Image.Image:
    """Red where only A has ink, blue where only B has ink, grey where both."""
    a = _load_tile(a_png, size).convert("L").point(lambda v: 255 if v < 200 else 0)
    b = _load_tile(b_png, size).convert("L").point(lambda v: 255 if v < 200 else 0)
    out = Image.new("RGB", (size, size), (255, 255, 255))
    px = out.load()
    ap, bp = a.load(), b.load()
    for y in range(size):
        for x in range(size):
            ai, bi = ap[x, y], bp[x, y]
            if ai and bi:
                px[x, y] = (205, 205, 205)
            elif ai:
                px[x, y] = (220, 40, 40)
            elif bi:
                px[x, y] = (40, 90, 220)
    return out


def grid(
    rows: list[list[Image.Image]],
    *,
    col_labels: list[str] | None = None,
    row_labels: list[str] | None = None,
    cell_labels: list[list[str]] | None = None,
    title: str | None = None,
    tile: int = TILE,
) -> Image.Image:
    ncols = max(len(r) for r in rows) if rows else 0
    row_label_w = 190 if row_labels else 0
    head_h = 30 if col_labels else 0
    title_h = 42 if title else 0
    cell_h = tile + (LABEL_H if cell_labels else 0)
    w = row_label_w + ncols * (tile + PAD) + PAD
    h = title_h + head_h + len(rows) * (cell_h + PAD) + PAD
    sheet = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(sheet)

    if title:
        d.text((PAD, 10), title, fill=INK, font=_font(22, bold=True))
    if col_labels:
        for c, lab in enumerate(col_labels):
            d.text(
                (row_label_w + PAD + c * (tile + PAD), title_h + 6),
                lab,
                fill=INK,
                font=_font(17, bold=True),
            )
    for r, row in enumerate(rows):
        y = title_h + head_h + r * (cell_h + PAD) + PAD
        if row_labels and r < len(row_labels):
            for i, line in enumerate(row_labels[r].split("\n")):
                d.text((PAD, y + 6 + i * 18), line, fill=INK, font=_font(15, bold=(i == 0)))
        for c, im in enumerate(row):
            x = row_label_w + PAD + c * (tile + PAD)
            sheet.paste(im, (x, y))
            d.rectangle([x, y, x + tile, y + tile], outline=(210, 210, 210))
            if cell_labels and r < len(cell_labels) and c < len(cell_labels[r]):
                d.text(
                    (x + 2, y + tile + 6),
                    cell_labels[r][c],
                    fill=(60, 60, 60),
                    font=_font(14),
                )
    return sheet


def save(image: Image.Image, path: str | Path) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    image.save(p)
    return str(p)
