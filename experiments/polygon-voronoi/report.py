"""Build the two required contact sheets for the polygon-Voronoi track.

    python3 experiments/polygon-voronoi/report.py comparison --inputs ...
    python3 experiments/polygon-voronoi/report.py progress --image 03-arc
    python3 experiments/polygon-voronoi/report.py surface       # 2-D sweep tables

Comparison sheet: one row per image, columns input | output | diff | overlay,
labelled with filename, IoU and pixel-diff %, plus zoomed crops of the worst
regions.  Progress sheet: one tile per iteration for the focus image.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bench  # noqa: E402
import graphmodel  # noqa: E402
import sheets  # noqa: E402
from svgpoly import load_svg  # noqa: E402

ROOT = bench.ROOT
DEBUG = bench.DEBUG
TILE = sheets.TILE


def _fill_svg(doc, mono: bool = False) -> str:
    """Re-emit the loaded (flattened) geometry as a plain filled SVG."""
    vb = doc.viewbox
    parts = []
    for el in doc.elements:
        d = []
        for p in el.geometry.geoms:
            for ring in [p.exterior, *p.interiors]:
                cs = list(ring.coords)
                d.append("M " + " L ".join(f"{x:.3f} {y:.3f}" for x, y in cs) + " Z")
        fill = "#000000" if mono else (el.fill or "#000000")
        parts.append(f'<path fill="{fill}" fill-rule="evenodd" d="{" ".join(d)}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="{vb[0]} {vb[1]} {vb[2]} {vb[3]}">{"".join(parts)}</svg>')


def _worst_crops(diff_img: Image.Image, base: Image.Image, k=3, block=64, crop=140):
    a = np.asarray(diff_img)
    mask = (a[..., 0] > 200) & (a[..., 1] < 80)
    h, w = mask.shape
    nb_y, nb_x = h // block, w // block
    if nb_y == 0 or nb_x == 0:
        return []
    scores = mask[: nb_y * block, : nb_x * block].reshape(nb_y, block, nb_x, block)
    scores = scores.sum(axis=(1, 3))
    idx = np.dstack(np.unravel_index(np.argsort(scores.ravel())[::-1], scores.shape))[0]
    out, used = [], []
    for by, bx in idx:
        if scores[by, bx] == 0 or len(out) >= k:
            break
        cy, cx = by * block + block // 2, bx * block + block // 2
        if any(abs(cy - uy) < crop and abs(cx - ux) < crop for uy, ux in used):
            continue
        used.append((cy, cx))
        box = (max(0, cx - crop // 2), max(0, cy - crop // 2),
               min(w, cx + crop // 2), min(h, cy + crop // 2))
        tile = base.crop(box).resize((TILE // 2, TILE // 2), Image.NEAREST)
        out.append((tile, int(scores[by, bx])))
    return out


def build_comparison(inputs, backend, tolerance, cfg, out_stem="contact-comparison",
                     title=None, extra_note=""):
    rows_img, row_labels, table = [], [], [
        ["image", "backend", "tol", "elems", "IoU", "symdiff%", "bdistP95",
         "edges", "terminals", "junctions", "s/elem", "pixdiff%"]
    ]
    for p in inputs:
        full = p if os.path.isabs(p) else os.path.join(ROOT, p)
        name = os.path.basename(full)[:-4]
        prefix = f"{name}-{backend}"
        r = bench.run_one(full, backend, tolerance, cfg, save_prefix=prefix)
        if r.get("error"):
            print(f"  !! {name}: {r['error']}")
            continue
        doc = load_svg(full, tolerance=tolerance)
        with open(os.path.join(ROOT, r["graph"])) as f:
            gj = json.load(f)
        g = _graph_from_json(gj)

        src_img = sheets.render_svg(_fill_svg(doc), TILE, is_string=True)
        out_svg_path = os.path.join(ROOT, r["out_svg"])
        out_img = sheets.render_svg(out_svg_path, TILE)
        dimg, pct = sheets.diff_image(src_img, out_img)
        ov = sheets.overlay_svg(doc.viewbox, _fill_svg(doc, mono=True),
                                graphmodel.to_svg_paths(g), TILE)

        rows_img.append([
            sheets.label(src_img, "input"),
            sheets.label(out_img, "output (re-stroked centerlines)"),
            sheets.label(dimg, f"diff  {pct:.2f}%"),
            sheets.label(ov, "overlay (red = recovered)"),
        ])
        row_labels.append(
            f"{name}\nIoU {r['iou']:.4f}\npixdiff {pct:.2f}%\n"
            f"edges {r['cx_edges']}  term {r['cx_terminals']}\n"
            f"{r['s_per_element']:.3f}s/elem"
        )
        table.append([name, backend, tolerance, r["elements"], f"{r['iou']:.4f}",
                      f"{100*r['symdiff_frac']:.2f}" if r["symdiff_frac"] is not None else "-",
                      f"{r['bdist_p95']:.3f}", r["cx_edges"], r["cx_terminals"],
                      r["cx_junctions"], f"{r['s_per_element']:.3f}", f"{pct:.2f}"])

        crops = _worst_crops(dimg, ov)
        if crops:
            rows_img.append([sheets.label(t, f"worst region {i+1} ({n}px)")
                             for i, (t, n) in enumerate(crops)])
            row_labels.append(f"{name}\nzoomed worst regions")

    png = os.path.join(DEBUG, f"{out_stem}.png")
    img = sheets.grid(rows_img, ["input", "output", "diff", "overlay"], row_labels)
    img.save(png)
    html = sheets.html_sheet(
        title or f"polygon-voronoi comparison ({backend}, tol={tolerance})",
        [{"title": "Scores", "table": table, "note": extra_note},
         {"title": "Contact sheet", "img": os.path.basename(png)}],
        os.path.join(DEBUG, f"{out_stem}.html"), os.path.basename(png))
    print(f"wrote {png}\nwrote {html}")
    return table


def _graph_from_json(gj) -> graphmodel.Graph:
    g = graphmodel.Graph(meta=gj.get("meta", {}))
    for n in gj["nodes"]:
        g.nodes.append(graphmodel.Node(n["id"], n["x"], n["y"], n.get("radius")))
    for e in gj["edges"]:
        g.edges.append(graphmodel.Edge(
            e["id"], e["from"], e["to"],
            [(p["x"], p["y"]) if isinstance(p, dict) else tuple(p)
             for p in e["geometry"]],
            e["length"], e.get("medianRadius"), [], e.get("sourceElementId"),
            e.get("sourceFill")))
    return g


def build_progress(image_svg, iterations, out_stem="contact-progress", title=None):
    """One tile per (tag, backend, tolerance, cfg) iteration, chronological."""
    full = image_svg if os.path.isabs(image_svg) else os.path.join(ROOT, image_svg)
    name = os.path.basename(full)[:-4]
    doc_cache = {}
    tiles, labels, table = [], [], [["#", "tag", "backend", "tol", "IoU",
                                     "clP95", "edges", "s/elem"]]
    row = []
    for i, it in enumerate(iterations):
        tol = it["tolerance"]
        cfg = it["cfg"]
        truth = it.get("truth")
        r = bench.run_one(full, it["backend"], tol, cfg, truth=truth,
                          save_prefix=f"{name}-prog{i}")
        if tol not in doc_cache:
            doc_cache[tol] = load_svg(full, tolerance=tol)
        doc = doc_cache[tol]
        with open(os.path.join(ROOT, r["graph"])) as f:
            g = _graph_from_json(json.load(f))
        ov = sheets.overlay_svg(doc.viewbox, _fill_svg(doc, mono=True),
                                graphmodel.to_svg_paths(g), TILE)
        cl = r.get("cl_hausdorff_p95")
        row.append(sheets.label(
            ov, f"{i}. {it['tag']}",
            f"IoU {r['iou']:.4f}"
            + (f"  clP95 {cl:.3f}" if isinstance(cl, float) else "")
            + f"  edges {r['cx_edges']}"))
        table.append([i, it["tag"], it["backend"], tol, f"{r['iou']:.4f}",
                      f"{cl:.3f}" if isinstance(cl, float) else "-",
                      r["cx_edges"], f"{r['s_per_element']:.3f}"])
        if len(row) == 4:
            tiles.append(row)
            labels.append("")
            row = []
    if row:
        while len(row) < 4:
            row.append(Image.new("RGB", (TILE, row[0].height), "white"))
        tiles.append(row)
        labels.append("")
    png = os.path.join(DEBUG, f"{out_stem}.png")
    sheets.grid(tiles).save(png)
    html = sheets.html_sheet(title or f"polygon-voronoi progress: {name}",
                             [{"title": "Iterations", "table": table},
                              {"title": "Tiles", "img": os.path.basename(png)}],
                             os.path.join(DEBUG, f"{out_stem}.html"),
                             os.path.basename(png))
    print(f"wrote {png}\nwrote {html}")
    return table


def ITERATIONS(truth=None):
    """The actual chronological trajectory of this track, replayable.

    Each entry is one thing changed relative to the previous, in the order the
    session tried them, so the progress sheet shows the real path -- including
    the step that made things worse.
    """
    P = lambda **kw: {"densify_distance": -0.5, "min_branch_length": -1.0,  # noqa: E731
                      "simplifytolerance": -0.25, "extend": False, **kw}
    return [
        {"tag": "pygeoops library defaults", "backend": "pygeoops",
         "tolerance": 0.5, "cfg": P(), "truth": truth},
        {"tag": "no branch filter (mbl=0)", "backend": "pygeoops",
         "tolerance": 0.5, "cfg": P(min_branch_length=0.0), "truth": truth},
        {"tag": "simplify off", "backend": "pygeoops",
         "tolerance": 0.5, "cfg": P(simplifytolerance=0.0), "truth": truth},
        {"tag": "flatten tol 0.5 -> 0.15", "backend": "pygeoops",
         "tolerance": 0.15, "cfg": P(simplifytolerance=0.0), "truth": truth},
        {"tag": "extend=True (cap reach)", "backend": "pygeoops",
         "tolerance": 0.15, "cfg": P(simplifytolerance=0.0, extend=True),
         "truth": truth},
        {"tag": "densify -0.5 -> -0.25", "backend": "pygeoops",
         "tolerance": 0.15,
         "cfg": P(simplifytolerance=0.0, densify_distance=-0.25), "truth": truth},
        {"tag": "fitodic raw (interp 2.0)", "backend": "fitodic",
         "tolerance": 0.15, "cfg": {"interpolation_distance": 2.0}, "truth": truth},
        {"tag": "fitodic + pygeoops filter", "backend": "fitodic+filter",
         "tolerance": 0.15,
         "cfg": {"interpolation_distance": 2.0, "min_branch_length": -1.0,
                 "simplifytolerance": 0.0}, "truth": truth},
    ]


def pixel_diff(a_svg, b_svg, size=1200):
    """Raster pixel-diff via the incumbent src/compare.js, for continuity."""
    try:
        out = subprocess.run(
            ["node", "src/compare.js", a_svg, b_svg, str(size),
             os.path.join(DEBUG, "scratch_diff.png")],
            cwd=ROOT, capture_output=True, text=True, timeout=300)
        for line in out.stdout.splitlines():
            if "differing pixels" in line:
                return float(line.split("=")[-1].strip().rstrip("%"))
    except Exception:
        pass
    return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["comparison", "progress"])
    ap.add_argument("--inputs", nargs="*")
    ap.add_argument("--image")
    ap.add_argument("--backend", default="pygeoops")
    ap.add_argument("--tolerance", type=float, default=0.25)
    ap.add_argument("--densify", type=float, default=-0.5)
    ap.add_argument("--branch", type=float, default=-1.0)
    ap.add_argument("--simplify", type=float, default=0.0)
    ap.add_argument("--interp", type=float, default=2.0)
    ap.add_argument("--stem", default=None)
    a = ap.parse_args()
    cfg = ({"densify_distance": a.densify, "min_branch_length": a.branch,
            "simplifytolerance": a.simplify, "extend": False}
           if a.backend == "pygeoops" else {"interpolation_distance": a.interp})
    if a.cmd == "comparison":
        build_comparison(a.inputs or bench.REAL_LADDER[:1], a.backend, a.tolerance,
                         cfg, a.stem or f"contact-comparison-{a.backend}")
    elif a.cmd == "progress":
        img = a.image or "inputs/house-wide.svg"
        truth = None
        if img.startswith("debug/"):
            for c in bench.load_manifest():
                if c["svg"] == img:
                    truth = c
        build_progress(img, ITERATIONS(truth), a.stem or "contact-progress",
                       title=f"polygon-voronoi progress: {os.path.basename(img)}")
