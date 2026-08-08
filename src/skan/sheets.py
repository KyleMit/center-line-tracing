#!/usr/bin/env python3
"""Contact sheets for this pipeline — the visual deliverable.

    python3 src/skan/sheets.py comparison --tag medial-axis@4
    python3 src/skan/sheets.py progress --image house-wide

Comparison sheet: one row per image, columns input | output | diff | overlay,
plus zoomed crops of the worst regions.  Progress sheet: one tile per iteration
for a single focus image, in the order the runs were recorded.

Both write a PNG *and* an HTML file so they can be read with or without a
browser.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import scipy.ndimage as ndi
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))

import metrics as M  # noqa: E402
import raster  # noqa: E402
import svgio  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent
DEBUG = REPO / "runs"
SHEETS = DEBUG / "sheets"
TILE = 440
FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
FONT_SM = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 13)
LABEL_H = 46


def _fit_box(viewbox, tile):
    _, _, w, h = viewbox
    s = tile / max(w, h)
    return s


def render_svg_file(path: Path, viewbox, tile: int, box=None) -> Image.Image:
    """Render an SVG file on white at `tile` px on its longest side."""
    box = box or (viewbox[0], viewbox[1], viewbox[2], viewbox[3])
    text = Path(path).read_text()
    body = re.sub(r"(?s)^.*?<svg[^>]*>", "", text, count=1)
    body = re.sub(r"(?s)</svg>\s*$", "", body)
    scale = tile / max(box[2], box[3])
    x, y, w, h = box
    width, height = svgio._px(box, scale)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {w} {h}" '
           f'width="{width}" height="{height}">'
           f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#ffffff"/>{body}</svg>')
    return _rgb(svg, box, scale)


def _rgb(svg: str, box, scale) -> Image.Image:
    """Render an SVG string to an RGB PIL image (via the same resvg helper)."""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "a.png"
        job = {"jobs": [{"svg": svg, "width": svgio._px(box, scale)[0],
                         "height": svgio._px(box, scale)[1], "out": str(out)}]}
        proc = subprocess.run(["node", str(Path(__file__).parent / "resvg_render_rgb.js")],
                              input=json.dumps(job), capture_output=True, text=True,
                              cwd=str(REPO))
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[:1000])
        return Image.open(out).convert("RGB").copy()


def overlay_svg(doc: svgio.SvgDoc, graph_path: Path, box, scale) -> Image.Image:
    """Recovered centerlines in red over the input fill in grey at 40%."""
    graph = json.loads(Path(graph_path).read_text())
    x, y, w, h = box
    width, height = svgio._px(box, scale)
    stroke_w = max(w, h) / 400.0
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {w} {h}" '
             f'width="{width}" height="{height}">',
             f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#ffffff"/>']
    for e in doc.elements:
        parts.append(f'<path d="{e.d}" fill="#808080" fill-opacity="0.4" '
                     f'fill-rule="{e.fill_rule}"/>')
    for edge in graph["edges"]:
        pts = edge["geometry"]
        if len(pts) < 2:
            continue
        d = "M" + " L".join(f"{p[0]:.2f},{p[1]:.2f}" for p in pts)
        if edge.get("closed"):
            d += "Z"
        parts.append(f'<path d="{d}" fill="none" stroke="#e02020" '
                     f'stroke-width="{stroke_w:.3f}" stroke-linecap="round"/>')
    # junctions and endpoints, so topology defects are visible at a glance
    for n in graph["nodes"]:
        deg = n.get("degree") or 0
        if deg == 1:
            parts.append(f'<circle cx="{n["x"]:.2f}" cy="{n["y"]:.2f}" '
                         f'r="{stroke_w*1.6:.2f}" fill="#1060d0"/>')
        elif deg >= 3:
            parts.append(f'<circle cx="{n["x"]:.2f}" cy="{n["y"]:.2f}" '
                         f'r="{stroke_w*2.0:.2f}" fill="#12a012"/>')
    parts.append("</svg>")
    return _rgb("".join(parts), box, scale)


def diff_image(doc: svgio.SvgDoc, recon: Path, box, scale) -> tuple[Image.Image, np.ndarray]:
    jobs = [(svgio.doc_svg(doc, box, scale), box, scale),
            (M.mask_svg_from_svg_file(recon, box, scale), box, scale)]
    o, r = raster.render_many(jobs)
    om, rm = o.mask, r.mask
    h, w = om.shape
    img = np.full((h, w, 3), 255, np.uint8)
    img[om & rm] = (200, 200, 200)
    img[om & ~rm] = (220, 30, 30)      # missed
    img[rm & ~om] = (30, 90, 220)      # added
    return Image.fromarray(img), (om ^ rm)


def worst_crops(doc: svgio.SvgDoc, recon: Path, graph_path: Path, sym: np.ndarray,
                scale: float, n: int = 3, size: int = 260) -> list[tuple[Image.Image, str]]:
    lbl, count = ndi.label(sym, np.ones((3, 3)))
    if count == 0:
        return []
    sizes = ndi.sum(sym, lbl, range(1, count + 1))
    order = np.argsort(-sizes)[:n]
    crops = []
    for k in order:
        cy, cx = ndi.center_of_mass(lbl == (k + 1))
        vx, vy, vw, vh = doc.viewbox
        x = vx + cx / scale
        y = vy + cy / scale
        half = size / 2 / scale * (max(vw, vh) / max(vw, vh))
        span = max(vw, vh) / 9.0
        box = (x - span / 2, y - span / 2, span, span)
        tile_scale = 300 / span
        left = overlay_svg(doc, graph_path, box, tile_scale)
        right, _ = diff_image(doc, recon, box, tile_scale)
        pair = Image.new("RGB", (left.width + right.width + 6, left.height), "white")
        pair.paste(left, (0, 0))
        pair.paste(right, (left.width + 6, 0))
        crops.append((pair, f"worst region @ ({x:.0f},{y:.0f}) — {int(sizes[k]/scale**2)} u²"))
    return crops


def label_tile(img: Image.Image, title: str, subtitle: str = "") -> Image.Image:
    out = Image.new("RGB", (img.width, img.height + LABEL_H), "white")
    out.paste(img, (0, LABEL_H))
    d = ImageDraw.Draw(out)
    d.text((6, 4), title, font=FONT, fill="black")
    if subtitle:
        d.text((6, 24), subtitle, font=FONT_SM, fill="#444444")
    d.line([(0, LABEL_H - 1), (out.width, LABEL_H - 1)], fill="#dddddd")
    return out


def grid(rows: list[list[Image.Image]], pad: int = 8, bg="white") -> Image.Image:
    widths = [sum(im.width for im in row) + pad * (len(row) + 1) for row in rows]
    heights = [max(im.height for im in row) + pad for row in rows]
    out = Image.new("RGB", (max(widths), sum(heights) + pad), bg)
    y = pad
    for row, hh in zip(rows, heights):
        x = pad
        for im in row:
            out.paste(im, (x, y))
            x += im.width + pad
        y += hh
    return out


def _runs_for(store, tag=None, images=None):
    out = []
    for r in store["runs"]:
        if tag and r["tag"] != tag:
            continue
        if images and r["image"] not in images:
            continue
        out.append(r)
    return out


def comparison(args) -> None:
    store = json.loads((DEBUG / "metrics.json").read_text())
    runs = _runs_for(store, args.tag, args.images or None)
    runs = [r for r in runs if not r.get("corpusCase")] if not args.corpus else \
           [r for r in runs if r.get("corpusCase")]
    runs.sort(key=lambda r: (r.get("corpusCase") or 0, r["image"]))
    # See progress() — runs/out/ and runs/graphs/ are a regenerable cache, so a
    # record whose files are gone means "re-run the bench for that tag", not
    # "the sheet is broken".
    stale = [r["image"] for r in runs
             if not (REPO / r["output"]).exists() or not (REPO / r["graph"]).exists()]
    runs = [r for r in runs
            if (REPO / r["output"]).exists() and (REPO / r["graph"]).exists()]
    if stale:
        print(f"skipping {len(stale)} run(s) with no emitted SVG: {', '.join(stale)}")
    rows, html = [], []
    for rec in runs:
        doc = svgio.load(REPO / rec["source"])
        box = (doc.viewbox[0], doc.viewbox[1], doc.viewbox[2], doc.viewbox[3])
        scale = _fit_box(doc.viewbox, TILE)
        recon = REPO / rec["output"]
        inp = render_svg_file(REPO / rec["source"], doc.viewbox, TILE)
        out = render_svg_file(recon, doc.viewbox, TILE)
        dif, sym = diff_image(doc, recon, box, scale)
        ovl = overlay_svg(doc, REPO / rec["graph"], box, scale)
        px = rec.get("pixelDiffPct")
        sub = (f"IoU {rec['iou']:.4f}  pixel {px:.2f}%" if px is not None
               else f"IoU {rec['iou']:.4f}")
        sub2 = (f"edges {rec['edges']}  bez {rec['bezierSegments']}  "
                f"symDiff {rec['symDiffFrac']:.4f}  bP95 {rec.get('boundaryP95', 0):.2f}")
        rows.append([
            label_tile(inp, f"{rec['image']}  [{rec['tag']}]", "input (filled)"),
            label_tile(out, "output (stroked)", sub),
            label_tile(dif, "diff  red=missed blue=added", sub2),
            label_tile(ovl, "overlay  red=centerline", "blue=endpoint green=junction"),
        ])
        for crop, cap in worst_crops(doc, recon, REPO / rec["graph"], sym, scale,
                                     n=args.crops):
            rows.append([label_tile(crop, f"{rec['image']} — {cap}",
                                    "overlay | diff")])
        html.append(rec)
    if not rows:
        print("no runs matched")
        return
    SHEETS.mkdir(parents=True, exist_ok=True)
    name = args.name or ("corpus" if args.corpus else "comparison")
    png = SHEETS / f"{name}.png"
    grid(rows).save(png)
    _write_html(SHEETS / f"{name}.html", name, html, png.name)
    print(f"wrote {png.relative_to(REPO)} and {name}.html ({len(rows)} rows)")


def progress(args) -> None:
    store = json.loads((DEBUG / "metrics.json").read_text())
    runs = [r for r in store["runs"] if r["image"] == args.image]
    # metrics.json is the durable record; runs/out/ is a regenerable cache that is
    # not in version control. Skip records whose emitted SVG is no longer on disk
    # rather than failing the whole sheet — re-run the bench for that tag to get
    # the tile back.
    missing = [r["tag"] for r in runs if not (REPO / r["output"]).exists()]
    runs = [r for r in runs if (REPO / r["output"]).exists()]
    if missing:
        print(f"skipping {len(missing)} tag(s) with no emitted SVG: {', '.join(missing)}")
    if not runs:
        print(f"no runs for {args.image}")
        return
    tiles = []
    for rec in runs:
        doc = svgio.load(REPO / rec["source"])
        img = render_svg_file(REPO / rec["output"], doc.viewbox, TILE)
        px = rec.get("pixelDiffPct")
        score = (f"IoU {rec['iou']:.4f}" + (f"  pixel {px:.2f}%" if px is not None else "")
                 + (f"  cL95 {rec['centerlineP95']:.2f}"
                    if rec.get("centerlineP95") is not None else ""))
        tiles.append(label_tile(img, rec["tag"], score))
    rows = [tiles[i:i + 4] for i in range(0, len(tiles), 4)]
    SHEETS.mkdir(parents=True, exist_ok=True)
    png = SHEETS / f"progress-{args.image}.png"
    grid(rows).save(png)
    _write_html(SHEETS / f"progress-{args.image}.html", f"progress: {args.image}",
                runs, png.name)
    print(f"wrote {png.relative_to(REPO)} ({len(tiles)} tiles)")


def _write_html(path: Path, title: str, records: list[dict], png_name: str) -> None:
    keys = ["image", "tag", "iou", "pixelDiffPct", "symDiffFrac", "boundaryMedian",
            "boundaryP95", "centerlineMedian", "centerlineP95", "edges", "nodes",
            "bezierSegments", "controlPoints", "fileBytes", "extractSeconds"]
    head = "".join(f"<th>{k}</th>" for k in keys)
    body = []
    for r in records:
        cells = []
        for k in keys:
            v = r.get(k)
            cells.append("<td>" + ("-" if v is None else
                                   (f"{v:.4f}" if isinstance(v, float) else str(v))) + "</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    path.write_text(f"""<!doctype html><meta charset=utf-8><title>{title}</title>
<style>body{{font:14px/1.4 system-ui,sans-serif;margin:24px;background:#fafafa}}
table{{border-collapse:collapse;margin:16px 0}} td,th{{border:1px solid #ccc;padding:3px 7px;
text-align:right;font-variant-numeric:tabular-nums}} th{{background:#eee}}
td:first-child,td:nth-child(2),th:first-child,th:nth-child(2){{text-align:left}}
img{{max-width:100%;border:1px solid #ccc;background:#fff}}</style>
<h1>skimage-skan — {title}</h1>
<table><tr>{head}</tr>{''.join(body)}</table>
<img src="{png_name}">
""")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["comparison", "progress"])
    ap.add_argument("--tag", default=None)
    ap.add_argument("--image", default="house-wide")
    ap.add_argument("--images", default="")
    ap.add_argument("--corpus", action="store_true")
    ap.add_argument("--crops", type=int, default=2)
    ap.add_argument("--name", default=None)
    args = ap.parse_args()
    args.images = [s for s in args.images.split(",") if s]
    if args.command == "comparison":
        comparison(args)
    else:
        progress(args)


if __name__ == "__main__":
    main()
