"""Contact sheets (Common Setup §"Contact sheets — the visual deliverable").

Comparison sheet: one row per image, four columns
    input | output (re-stroked) | diff | overlay (centerlines in red over input)
Progress sheet: one tile per recorded iteration for the current focus image.

Emits both PNG and HTML.
"""

from __future__ import annotations

import io
import json
import os

import cairosvg
from PIL import Image, ImageDraw, ImageFont

TILE = 420
PAD = 8
LABEL_H = 34


def render_svg(path_or_str, width, height, is_string=False):
    kw = dict(output_width=width, output_height=height, background_color="white")
    png = (
        cairosvg.svg2png(bytestring=path_or_str.encode(), **kw)
        if is_string
        else cairosvg.svg2png(url=path_or_str, **kw)
    )
    return Image.open(io.BytesIO(png)).convert("RGB")


def to_mask(img, thresh=200):
    g = img.convert("L")
    return g.point(lambda v: 255 if v < thresh else 0)


def diff_image(a, b):
    """Red = in original only (missed), blue = in reconstruction only (extra)."""
    ma, mb = to_mask(a), to_mask(b)
    out = Image.new("RGB", a.size, "white")
    px = out.load()
    pa, pb = ma.load(), mb.load()
    w, h = a.size
    for y in range(h):
        for x in range(w):
            va, vb = pa[x, y], pb[x, y]
            if va and vb:
                px[x, y] = (215, 215, 215)
            elif va:
                px[x, y] = (220, 40, 40)
            elif vb:
                px[x, y] = (40, 90, 220)
    return out


def overlay_image(input_img, graph_json, vw, vh, size):
    base = input_img.copy().convert("RGB")
    faded = Image.blend(base, Image.new("RGB", base.size, "white"), 0.6)
    d = ImageDraw.Draw(faded)
    sx, sy = size[0] / vw, size[1] / vh
    with open(graph_json) as f:
        g = json.load(f)
    for e in g["edges"]:
        pts = [(x * sx, y * sy) for x, y in e["geometry"]]
        if len(pts) >= 2:
            d.line(pts, fill=(220, 20, 20), width=2)
    nodes = {n["id"]: n for n in g["nodes"]}
    deg = {}
    for e in g["edges"]:
        for k in (e["from"], e["to"]):
            deg[k] = deg.get(k, 0) + 1
    for nid, k in deg.items():
        n = nodes.get(nid)
        if not n:
            continue
        x, y = n["x"] * sx, n["y"] * sy
        c = (20, 120, 220) if k >= 3 else (20, 170, 60)
        d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=c)
    return faded


def _font(sz=15):
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def build_comparison(rows, inputs_dir, restroke_dir, graphs_dir, out_png, out_html, title):
    font = _font(14)
    bold = _font(16)
    tiles = []
    for r in rows:
        if "error" in r:
            continue
        name = r["name"]
        src = os.path.join(inputs_dir, name + ".svg")
        rec = os.path.join(restroke_dir, name + ".svg")
        gj = os.path.join(graphs_dir, name + ".json")
        if not (os.path.exists(src) and os.path.exists(rec)):
            continue
        import svgpoly

        vw, vh = svgpoly.svg_viewbox(src)
        scale = TILE / max(vw, vh)
        size = (max(1, int(vw * scale)), max(1, int(vh * scale)))
        a = render_svg(src, *size)
        b = render_svg(rec, *size)
        tiles.append((r, a, b, diff_image(a, b), overlay_image(a, gj, vw, vh, size)))

    if not tiles:
        return
    row_h = max(t[1].size[1] for t in tiles) + LABEL_H + PAD
    row_w = 4 * (max(t[1].size[0] for t in tiles) + PAD) + PAD
    sheet = Image.new("RGB", (row_w, row_h * len(tiles) + 40), "white")
    d = ImageDraw.Draw(sheet)
    d.text((PAD, 10), title, fill="black", font=bold)
    y = 40
    for r, a, b, df, ov in tiles:
        x = PAD
        for img, cap in ((a, "input"), (b, "re-stroked"), (df, "diff"), (ov, "overlay")):
            sheet.paste(img, (x, y + LABEL_H))
            d.text((x, y + 2), cap, fill=(90, 90, 90), font=font)
            x += img.size[0] + PAD
        label = (
            f"{r['name']}   IoU {r.get('iou', 0):.4f}   symdiff "
            f"{100 * (r.get('symdiff_frac') or 0):.2f}%   strokes {r['strokes']}   "
            f"branches {r['branch_nodes']}   {r['runtime_ms']['total']:.0f}ms"
        )
        cl = r.get("centerline_recovered_to_truth")
        if cl:
            label += f"   centerline med {cl['median']} / p95 {cl['p95']}"
        d.text((PAD + 300, y + 2), label, fill="black", font=font)
        y += row_h
    sheet.save(out_png)

    html = [
        "<!doctype html><meta charset=utf-8><title>%s</title>" % title,
        "<style>body{font:13px system-ui;margin:16px;background:#fafafa}"
        "table{border-collapse:collapse}td{padding:4px;vertical-align:top;text-align:center}"
        "img{max-width:420px;border:1px solid #ddd;background:#fff}"
        "th{font-weight:600;text-align:left;padding:6px 4px}</style>",
        f"<h2>{title}</h2><table>",
        "<tr><th>case</th><th>input</th><th>re-stroked</th><th>diff</th><th>overlay</th></tr>",
    ]
    rel = os.path.relpath
    base = os.path.dirname(out_html)
    for r, *_ in tiles:
        name = r["name"]
        cl = r.get("centerline_recovered_to_truth")
        meta = (
            f"<b>{name}</b><br>IoU {r.get('iou', 0):.4f}<br>"
            f"symdiff {100 * (r.get('symdiff_frac') or 0):.2f}%<br>"
            f"strokes {r['strokes']} / branches {r['branch_nodes']}<br>"
            f"{r['runtime_ms']['total']:.0f} ms"
        )
        if cl:
            meta += f"<br>centerline med {cl['median']}<br>p95 {cl['p95']}"
        html.append(
            "<tr><td style='text-align:left'>%s</td><td><img src='%s'></td>"
            "<td><img src='%s'></td><td colspan=2><i>see PNG sheet</i></td></tr>"
            % (
                meta,
                rel(os.path.join(inputs_dir, name + ".svg"), base),
                rel(os.path.join(restroke_dir, name + ".svg"), base),
            )
        )
    html.append("</table>")
    with open(out_html, "w") as f:
        f.write("\n".join(html))


def build_progress(entries, out_png, title):
    """entries: [(tag, svg_path, caption)] in chronological order."""
    font = _font(14)
    bold = _font(16)
    imgs = []
    for tag, svg, cap in entries:
        if not os.path.exists(svg):
            continue
        import svgpoly

        vw, vh = svgpoly.svg_viewbox(svg)
        scale = TILE / max(vw, vh)
        imgs.append((cap, render_svg(svg, max(1, int(vw * scale)), max(1, int(vh * scale)))))
    if not imgs:
        return
    cols = min(4, len(imgs))
    rows = (len(imgs) + cols - 1) // cols
    tw = max(i.size[0] for _, i in imgs) + PAD
    th = max(i.size[1] for _, i in imgs) + LABEL_H + PAD
    sheet = Image.new("RGB", (cols * tw + PAD, rows * th + 40), "white")
    d = ImageDraw.Draw(sheet)
    d.text((PAD, 10), title, fill="black", font=bold)
    for i, (cap, img) in enumerate(imgs):
        cx, cy = PAD + (i % cols) * tw, 40 + (i // cols) * th
        d.text((cx, cy), cap, fill="black", font=font)
        sheet.paste(img, (cx, cy + LABEL_H))
    sheet.save(out_png)
