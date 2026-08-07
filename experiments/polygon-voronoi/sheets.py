"""Contact sheets for the polygon-Voronoi track (Common Setup: visual deliverable).

Two kinds, both required:
  comparison sheet -- one row per image: input | output | diff | overlay
  progress sheet   -- one tile per iteration for the current focus image

Emits HTML and a PNG so the result is viewable without a browser.  Rendering is
via cairosvg (deterministic enough for these composites; ``src/compare.js``
remains the authority for the raster pixel-diff number).
"""

from __future__ import annotations

import io
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

TILE = 420


def _font(size=15):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def render_svg(path_or_str: str, size: int = TILE, is_string=False) -> Image.Image:
    import cairosvg

    kw = {"output_width": size, "output_height": size, "background_color": "white"}
    if is_string:
        png = cairosvg.svg2png(bytestring=path_or_str.encode(), **kw)
    else:
        png = cairosvg.svg2png(url=path_or_str, **kw)
    return Image.open(io.BytesIO(png)).convert("RGB")


def overlay_svg(doc_viewbox, fill_svg: str, graph_paths: list[str],
                size: int = TILE, hairline: bool = True) -> Image.Image:
    """Grey source fill at 40% with recovered centerlines drawn over it in red.

    The axis is drawn as a HAIRLINE, not at its recovered stroke width: a
    full-width red stroke covers the grey fill exactly and makes every result
    look identical.  A thin line shows where the axis actually sits inside the
    stroke, which is the thing worth looking at.
    """
    import re

    body = re.sub(r'fill="[^"]*"', 'fill="#000000"', fill_svg)
    body = re.sub(r"<svg[^>]*>", "", body).replace("</svg>", "")
    vb = doc_viewbox
    hw = max(vb[2], vb[3]) / size * 1.6  # ~1.6 device px
    strokes = []
    for p in graph_paths:
        p = p.replace('stroke="#000000"', 'stroke="#ff0000"')
        if hairline:
            p = re.sub(r'stroke-width="[^"]*"', f'stroke-width="{hw:.3f}"', p)
        strokes.append(p)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{vb[0]} {vb[1]} {vb[2]} {vb[3]}">'
        f'<g opacity="0.35">{body}</g>'
        f'<g>{chr(10).join(strokes)}</g></svg>'
    )
    return render_svg(svg, size, is_string=True)


def diff_image(a: Image.Image, b: Image.Image) -> tuple[Image.Image, float]:
    """Red where they differ; returns the image and the differing-pixel percentage."""
    na = np.asarray(a.convert("L"), dtype=np.int16)
    nb = np.asarray(b.convert("L"), dtype=np.int16)
    mask = np.abs(na - nb) > 32
    out = np.full((*na.shape, 3), 255, np.uint8)
    out[..., 0] = np.where(mask, 255, 245)
    out[..., 1] = np.where(mask, 0, 245)
    out[..., 2] = np.where(mask, 0, 245)
    grey = np.minimum(na, nb)
    dark = grey < 128
    for c in range(3):
        out[..., c] = np.where(dark & ~mask, 170, out[..., c])
    return Image.fromarray(out), float(mask.mean() * 100.0)


def label(img: Image.Image, text: str, sub: str = "") -> Image.Image:
    pad = 46 if sub else 26
    out = Image.new("RGB", (img.width, img.height + pad), "white")
    out.paste(img, (0, 0))
    d = ImageDraw.Draw(out)
    d.text((6, img.height + 4), text, fill=(0, 0, 0), font=_font(15))
    if sub:
        d.text((6, img.height + 24), sub, fill=(90, 90, 90), font=_font(13))
    return out


def grid(rows: list[list[Image.Image]], headers: list[str] | None = None,
         row_labels: list[str] | None = None) -> Image.Image:
    if not rows:
        return Image.new("RGB", (10, 10), "white")
    w = max(sum(i.width for i in r) for r in rows)
    left = 190 if row_labels else 0
    top = 30 if headers else 0
    h = sum(max(i.height for i in r) for r in rows)
    out = Image.new("RGB", (w + left, h + top), "white")
    d = ImageDraw.Draw(out)
    if headers:
        x = left
        for i, htxt in enumerate(headers):
            d.text((x + 6, 8), htxt, fill=(0, 0, 0), font=_font(16))
            x += rows[0][i].width if i < len(rows[0]) else TILE
    y = top
    for ri, r in enumerate(rows):
        x = left
        if row_labels:
            for li, ln in enumerate(row_labels[ri].split("\n")):
                d.text((6, y + 8 + li * 17), ln, fill=(0, 0, 0), font=_font(14))
        for img in r:
            out.paste(img, (x, y))
            x += img.width
        y += max(i.height for i in r)
    return out


def html_sheet(title: str, sections: list[dict], out_path: str, png_rel: str | None = None):
    css = """
    body{font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;margin:24px;
         background:#fafafa;color:#111}
    h1{font-size:20px} h2{font-size:15px;margin-top:28px}
    table{border-collapse:collapse;margin:10px 0}
    td,th{border:1px solid #ddd;padding:4px 8px;text-align:right}
    th{background:#eee} td:first-child,th:first-child{text-align:left}
    img{image-rendering:auto;max-width:100%;border:1px solid #ddd;background:#fff}
    .note{color:#555;max-width:70em}
    """
    parts = [f"<!doctype html><meta charset=utf-8><title>{title}</title>",
             f"<style>{css}</style><h1>{title}</h1>"]
    if png_rel:
        parts.append(f'<p class=note>PNG: <a href="{png_rel}">{png_rel}</a></p>')
    for s in sections:
        parts.append(f"<h2>{s.get('title','')}</h2>")
        if s.get("note"):
            parts.append(f"<p class=note>{s['note']}</p>")
        if s.get("table"):
            head, body = s["table"][0], s["table"][1:]
            parts.append("<table><tr>" + "".join(f"<th>{c}</th>" for c in head) + "</tr>")
            for row in body:
                parts.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
            parts.append("</table>")
        if s.get("img"):
            parts.append(f'<img src="{s["img"]}">')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write("\n".join(parts))
    return out_path
