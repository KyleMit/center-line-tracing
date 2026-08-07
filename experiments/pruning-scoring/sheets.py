#!/usr/bin/env python3
"""Build the contact sheets.

    python3 experiments/pruning-scoring/sheets.py cross         # one column per backend
    python3 experiments/pruning-scoring/sheets.py comparison --track flo-mat
    python3 experiments/pruning-scoring/sheets.py progress --graph <f>

The cross-backend sheet is Track 8's own artifact: same image, one column per
backend, every backend shown at ITS OWN automatically-selected pruning strength.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clg import CenterlineGraph, resolve, select, sheets, svgio  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DEBUG = REPO / "debug" / "pruning-scoring"
OUTPUTS = REPO / "outputs" / "pruning-scoring"
CACHE = DEBUG / "png"

IMAGES = [
    "house-wide", "butterfly-wide", "boat-tall", "island-tall", "balloon-tall",
    "home-wide", "house-tall", "dinosaur-wide", "landscape-square", "sun-square",
]


def _png(svg: Path | str, tag: str, width: int = sheets.TILE * 2) -> Path:
    svg = Path(svg)
    return CACHE / tag / f"{svg.stem}.png"


def _render_all(pairs: list[tuple[Path, Path]], width: int) -> None:
    jobs = [{"svg": str(s), "png": str(p), "width": width}
            for s, p in pairs if Path(s).exists()]
    sheets.render_svgs(jobs)


def load_metrics() -> dict:
    path = DEBUG / "metrics.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {(r["track"], r["image"]): r for r in data.get("results", [])
            if r.get("status") == "ok"}


def cross_sheet(images: list[str], tracks: list[str], out: Path) -> None:
    by = load_metrics()
    width = sheets.TILE * 2
    pairs: list[tuple[Path, Path]] = []
    for image in images:
        pairs.append((REPO / "inputs" / f"{image}.svg", CACHE / "input" / f"{image}.png"))
        for track in tracks:
            svg = OUTPUTS / track / f"{image}.svg"
            if svg.exists():
                pairs.append((svg, CACHE / track / f"{image}.png"))
    _render_all(pairs, width)

    rows, row_labels, cell_labels = [], [], []
    for image in images:
        inp = CACHE / "input" / f"{image}.png"
        row = [sheets._load_tile(inp)]
        labels = ["input"]
        for track in tracks:
            png = CACHE / track / f"{image}.png"
            if png.exists():
                row.append(sheets.overlay_image(inp, png))
                rec = by.get((track, image), {})
                prom = rec.get("promoted") or {}
                m = ((rec.get(prom.get("which", "auto")) or {}).get("metrics")
                     or rec.get("publishedBest") or {})
                labels.append(
                    f"{track}  λ={prom.get('lam', '?')}\n"
                    f"err {m.get('sym_diff_ratio', float('nan')):.4f}  "
                    f"br {m.get('edges', '?')}"
                )
            else:
                row.append(sheets._load_tile("missing"))
                labels.append(f"{track}  (none)")
        rows.append(row)
        row_labels.append(image)
        cell_labels.append(labels)

    sheet = sheets.grid(
        rows,
        col_labels=["input"] + tracks,
        row_labels=row_labels,
        cell_labels=cell_labels,
        title="Cross-backend centerline recovery — each backend at its own "
              "automatically selected pruning strength",
    )
    sheets.save(sheet, out)
    print(f"wrote {out}  ({sheet.width}x{sheet.height})")


def comparison_sheet(track: str, images: list[str], out: Path) -> None:
    by = load_metrics()
    width = sheets.TILE * 2
    pairs = []
    for image in images:
        pairs.append((REPO / "inputs" / f"{image}.svg", CACHE / "input" / f"{image}.png"))
        svg = OUTPUTS / track / f"{image}.svg"
        if svg.exists():
            pairs.append((svg, CACHE / track / f"{image}.png"))
    _render_all(pairs, width)

    rows, row_labels, cell_labels = [], [], []
    for image in images:
        inp = CACHE / "input" / f"{image}.png"
        rec = CACHE / track / f"{image}.png"
        if not rec.exists():
            continue
        rows.append([
            sheets._load_tile(inp),
            sheets._load_tile(rec),
            sheets.diff_image(inp, rec),
            sheets.overlay_image(inp, rec),
        ])
        r = by.get((track, image), {})
        prom = r.get("promoted") or {}
        m = ((r.get(prom.get("which", "auto")) or {}).get("metrics")
             or r.get("publishedBest") or {})
        raster = (r.get("rasterInk") or {}).get("symDiffRatio")
        row_labels.append(
            f"{image}\nIoU {m.get('iou', float('nan')):.4f}\n"
            f"err {m.get('sym_diff_ratio', float('nan')):.4f}\n"
            f"raster {raster:.4f}" if raster is not None else
            f"{image}\nIoU {m.get('iou', float('nan')):.4f}"
        )
        cell_labels.append(["source fill", f"recovered (λ={prom.get('lam', '?')})",
                            "red = source only, blue = recon only", "overlay"])
    sheet = sheets.grid(rows, col_labels=["input", "output", "diff", "overlay"],
                        row_labels=row_labels, cell_labels=cell_labels,
                        title=f"{track} — comparison sheet")
    sheets.save(sheet, out)
    print(f"wrote {out}")


def progress_sheet(graph_path: Path, out: Path, lambdas=None) -> None:
    """One tile per pruning strength, in order: the trajectory at a glance."""
    lambdas = lambdas or [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0]
    svg = resolve.resolve_source_svg(graph_path)
    src = svgio.load_source(str(svg))
    g = CenterlineGraph.load(graph_path)
    cands = select.sweep(g, src, lambdas=lambdas)
    chosen = select.simplest_within_tolerance(cands, tolerance=0.05)

    tmp = CACHE / "progress" / Path(graph_path).stem
    pairs = [(REPO / svg, CACHE / "input" / f"{Path(svg).stem}.png")]
    for c in cands:
        p = tmp / f"lam{c.lam:.2f}.svg"
        svgio.write_graph_svg(c.graph, p, view_box=src.view_box,
                              hairline=max(2.0, src.view_box[2] / 300.0))
        pairs.append((p, tmp / f"lam{c.lam:.2f}.png"))
    _render_all(pairs, sheets.TILE * 2)

    inp = CACHE / "input" / f"{Path(svg).stem}.png"
    row, labels = [], []
    for c in cands:
        row.append(sheets.overlay_image(inp, tmp / f"lam{c.lam:.2f}.png"))
        mark = " <= chosen" if chosen and c.lam == chosen.lam else ""
        labels.append(f"λ={c.lam:.2f}  err {c.error:.4f}  br {c.metrics.edges}{mark}")
    # wrap into rows of 4
    rows = [row[i:i + 4] for i in range(0, len(row), 4)]
    cell_labels = [labels[i:i + 4] for i in range(0, len(labels), 4)]
    sheet = sheets.grid(rows, cell_labels=cell_labels,
                        title=f"pruning trajectory — {Path(graph_path).name}")
    sheets.save(sheet, out)
    print(f"wrote {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_cross = sub.add_parser("cross")
    p_cross.add_argument("--images", nargs="*", default=IMAGES)
    p_cross.add_argument("--tracks", nargs="*", default=None)
    p_cross.add_argument("--out", default=str(DEBUG / "cross-backend-sheet.png"))

    p_cmp = sub.add_parser("comparison")
    p_cmp.add_argument("--track", required=True)
    p_cmp.add_argument("--images", nargs="*", default=IMAGES)
    p_cmp.add_argument("--out", default=None)

    p_prog = sub.add_parser("progress")
    p_prog.add_argument("--graph", required=True)
    p_prog.add_argument("--out", default=None)

    p_crop = sub.add_parser("crops")
    p_crop.add_argument("--track", required=True)
    p_crop.add_argument("--image", required=True)
    p_crop.add_argument("--n", type=int, default=3)
    p_crop.add_argument("--out", default=None)

    args = ap.parse_args()
    if args.cmd == "cross":
        tracks = args.tracks or sorted(
            d.name for d in OUTPUTS.iterdir() if d.is_dir()
        )
        cross_sheet(args.images, tracks, Path(args.out))
    elif args.cmd == "comparison":
        out = Path(args.out or DEBUG / f"comparison-{args.track}.png")
        comparison_sheet(args.track, args.images, out)
    elif args.cmd == "progress":
        gp = Path(args.graph)
        out = Path(args.out or DEBUG / f"progress-{gp.stem}.png")
        progress_sheet(gp, out)
    elif args.cmd == "crops":
        out = Path(args.out or DEBUG / f"crops-{args.track}-{args.image}.png")
        worst_region_crops(args.track, args.image, out, n=args.n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def worst_region_crops(track: str, image: str, out: Path, *, n: int = 3,
                       zoom: int = 3) -> None:
    """Zoomed crops of the worst reconstruction regions.

    "Worst" = the largest connected pieces of the symmetric difference between the
    source fill and the re-stroked centerline. This is the part of the contact
    sheet that actually tells you WHAT went wrong, as opposed to how much.
    """
    from clg import metrics, restroke

    svg_in = REPO / "inputs" / f"{image}.svg"
    graph_path = DEBUG / "graphs" / track / f"{image}.json"
    if not graph_path.exists():
        print(f"no promoted graph for {track}/{image}")
        return
    src = svgio.load_source(str(svg_in))
    g = CenterlineGraph.load(graph_path)
    rec = restroke.graph_to_fill(g)
    sym = src.polygon.symmetric_difference(rec)
    pieces = sorted(getattr(sym, "geoms", [sym]), key=lambda p: -p.area)[:n]
    if not pieces:
        print("no symmetric difference to show")
        return

    vb = src.view_box
    px_w = int(vb[2] * zoom)
    recon_svg = CACHE / "recon-hi" / f"{track}-{image}.svg"
    svgio.write_graph_svg(g, recon_svg, view_box=vb)
    jobs = [
        {"svg": str(svg_in), "png": str(CACHE / "hi" / f"{image}.png"), "width": px_w},
        {"svg": str(recon_svg), "png": str(CACHE / "hi" / f"{track}-{image}.png"),
         "width": px_w},
    ]
    sheets.render_svgs(jobs)

    from PIL import Image
    a = Image.open(CACHE / "hi" / f"{image}.png").convert("RGB")
    b = Image.open(CACHE / "hi" / f"{track}-{image}.png").convert("RGB")
    scale = a.width / vb[2]

    rows, cell_labels = [], []
    for piece in pieces:
        cx, cy = piece.centroid.x, piece.centroid.y
        half = max(piece.bounds[2] - piece.bounds[0],
                   piece.bounds[3] - piece.bounds[1], 40.0) * 1.6 / 2
        box = (
            int(max(0, (cx - half - vb[0]) * scale)),
            int(max(0, (cy - half - vb[1]) * scale)),
            int(min(a.width, (cx + half - vb[0]) * scale)),
            int(min(a.height, (cy + half - vb[1]) * scale)),
        )
        if box[2] - box[0] < 8 or box[3] - box[1] < 8:
            continue
        ca, cb = a.crop(box), b.crop(box)
        ca.thumbnail((sheets.TILE, sheets.TILE), Image.LANCZOS)
        cb.thumbnail((sheets.TILE, sheets.TILE), Image.LANCZOS)
        ta = Image.new("RGB", (sheets.TILE, sheets.TILE), (255, 255, 255))
        tb = Image.new("RGB", (sheets.TILE, sheets.TILE), (255, 255, 255))
        ta.paste(ca, ((sheets.TILE - ca.width) // 2, (sheets.TILE - ca.height) // 2))
        tb.paste(cb, ((sheets.TILE - cb.width) // 2, (sheets.TILE - cb.height) // 2))
        rows.append([ta, tb])
        cell_labels.append([
            f"source  ({cx:.0f}, {cy:.0f})",
            f"recovered  defect area {piece.area:.0f} u²",
        ])
    sheet = sheets.grid(rows, col_labels=["source fill", "re-stroked centerline"],
                        cell_labels=cell_labels,
                        title=f"{track} / {image} — worst reconstruction regions")
    sheets.save(sheet, out)
    print(f"wrote {out}")
