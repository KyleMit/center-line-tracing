#!/usr/bin/env python3
"""Track 8 harness: score graphs, select pruning automatically, build the leaderboard.

    python3 experiments/pruning-scoring/bench.py incumbent
    python3 experiments/pruning-scoring/bench.py score debug/flo-mat/graphs/house-wide.json
    python3 experiments/pruning-scoring/bench.py select --graph <f> --out <dir>
    python3 experiments/pruning-scoring/bench.py leaderboard --jobs 4
    python3 experiments/pruning-scoring/bench.py sheets
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import defaultdict
from functools import lru_cache
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clg import CenterlineGraph, metrics, resolve, select, svgio  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DEBUG = REPO / "debug" / "pruning-scoring"
OUTPUTS = REPO / "outputs" / "pruning-scoring"
GRAPHS = DEBUG / "graphs"
# The incumbent's graphs are an INPUT to the leaderboard, and every other track's
# inputs live in its own debug/<track>/graphs. Keeping the incumbent's under
# GRAPHS would collide with the promotion target below (GRAPHS/<track>/<image>),
# so each leaderboard run would score the previous run's pruned winner as if it
# were the incumbent's published output — measured drift on sun-square: 0.2104
# published on the first run, 0.2288 on the second. Distinct paths, no feedback.
INCUMBENT_GRAPHS = DEBUG / "incumbent" / "graphs"

REAL_IMAGES = [
    "house-wide", "butterfly-wide", "boat-tall", "island-tall", "balloon-tall",
    "home-wide", "house-tall", "dinosaur-wide", "landscape-square", "sun-square",
]

TRACKS = [
    "flo-mat", "autotrace", "skimage-skan", "polygon-voronoi",
    "tegaki", "opencv-tracing", "native-geometry",
]


@lru_cache(maxsize=32)
def source_for(svg_path: str):
    return svgio.load_source(svg_path)


# --------------------------------------------------------------------- incumbent


def run_incumbent(images: list[str], *, force: bool = False) -> list[dict]:
    """Bootstrap: run the incumbent Python pipeline and convert its SVG to a graph.

    The incumbent only ever emitted an SVG, so it enters the common model through
    the stroked-SVG reader. Its known scores (0.02% dinosaur, 0.73% landscape) are
    the control this whole harness has to reproduce.
    """
    out_dir = OUTPUTS / "incumbent"
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for image in images:
        src_svg = REPO / "inputs" / f"{image}.svg"
        out_svg = out_dir / f"{image}.svg"
        # The repo's promoted outputs/<image>.svg were produced with tuned flags and
        # are what the control numbers (0.02% dinosaur, 0.73% landscape) refer to;
        # default flags score 0.05% / 2.91%. Prefer the promoted result where it
        # exists so the control is the control.
        promoted = REPO / "outputs" / f"{image}.svg"
        if promoted.exists():
            out_svg = promoted
        elif force or not out_svg.exists():
            t = time.time()
            proc = subprocess.run(
                [sys.executable, str(REPO / "src" / "convert_filled_svg_to_stroked_lines.py"),
                 str(src_svg), "-o", str(out_svg)],
                capture_output=True, text=True, cwd=REPO, timeout=1800,
            )
            if proc.returncode != 0:
                print(f"  incumbent FAILED on {image}: {proc.stderr.strip()[:200]}")
                continue
            print(f"  incumbent {image}: {time.time() - t:.1f}s")
        g = svgio.graph_from_stroked_svg(out_svg, image=image, backend="incumbent")
        g.source = str(src_svg.relative_to(REPO))
        path = INCUMBENT_GRAPHS / f"{image}.json"
        g.save(path)
        records.append({"image": image, "graph": str(path.relative_to(REPO)),
                        "svg": str(out_svg.relative_to(REPO)), **g.stats()})
    return records


# ------------------------------------------------------------------- discovery


def graphs_for(track: str, image: str) -> list[Path]:
    root = REPO / "debug" / track / "graphs"
    if track == "incumbent":
        root = INCUMBENT_GRAPHS
    if not root.is_dir():
        return []
    out = []
    for f in sorted(root.rglob("*.json")):
        svg = resolve.resolve_source_svg(f, slug=track if track != "incumbent" else None)
        if svg and resolve.is_real_input(svg) and svg.stem == image:
            out.append(f)
    return out


# ---------------------------------------------------------------------- scoring


def score_one(path: Path, *, width_mode: str = "auto") -> dict | None:
    svg = resolve.resolve_source_svg(path)
    if svg is None:
        return None
    src = source_for(str(svg))
    g = CenterlineGraph.load(path)
    m = metrics.score_graph(g, src, width_mode=width_mode)
    return {"graph": str(Path(path).relative_to(REPO)), "source": str(svg.relative_to(REPO)),
            **m.to_dict()}


def _pair_job(args) -> dict:
    """One (track, image) cell of the leaderboard. Runs in a worker process."""
    track, image, lambdas, tolerance, with_headroom = args
    t0 = time.time()
    files = graphs_for(track, image)
    if not files:
        return {"track": track, "image": image, "status": "no-graph"}
    svg = resolve.resolve_source_svg(files[0])
    src = source_for(str(svg))

    # 1. every variant the track published, scored as-is: its own hand-tuned answer
    published = []
    for f in files:
        try:
            g = CenterlineGraph.load(f)
            m = metrics.score_graph(g, src)
        except Exception as exc:  # noqa: BLE001
            published.append({"graph": str(f.relative_to(REPO)), "error": str(exc)[:160]})
            continue
        published.append({"graph": str(f.relative_to(REPO)), **m.to_dict()})
    scored = [p for p in published if "sym_diff_ratio" in p]
    if not scored:
        return {"track": track, "image": image, "status": "unscorable",
                "published": published}
    best_pub = min(scored, key=lambda p: p["sym_diff_ratio"])

    # 2. automatic selection, starting from the LEAST-processed variant the track
    #    emitted, so the comparison is "our pruning vs their pruning" and not
    #    "our pruning on top of their pruning"
    rawest = max(scored, key=lambda p: (p["edges"], p["total_length"]))
    raw_graph = CenterlineGraph.load(REPO / rawest["graph"])
    chosen, cands = select.select(raw_graph, src, lambdas=lambdas, tolerance=tolerance)

    # 3. optionally, selection applied to their best, which shows remaining headroom.
    #    Off by default: it doubles the sweep cost, and the controlled pruning
    #    comparison lives in abtest.py, which holds the backend properly fixed.
    chosen_on_best, cands_on_best = None, []
    if with_headroom and best_pub["graph"] != rawest["graph"]:
        best_graph = CenterlineGraph.load(REPO / best_pub["graph"])
        chosen_on_best, cands_on_best = select.select(
            best_graph, src, lambdas=lambdas, tolerance=tolerance
        )

    rec = {
        "track": track,
        "image": image,
        "status": "ok",
        "source": str(svg.relative_to(REPO)),
        "variants": len(files),
        "published": published,
        "publishedBest": best_pub,
        "rawest": rawest["graph"],
        "auto": {
            "from": rawest["graph"],
            "lam": chosen.lam if chosen else None,
            "metrics": chosen.metrics.to_dict() if chosen else None,
            "sweep": [c.to_dict() for c in cands],
        },
        "autoOnBest": {
            "from": best_pub["graph"],
            "lam": chosen_on_best.lam if chosen_on_best else None,
            "metrics": chosen_on_best.metrics.to_dict() if chosen_on_best else None,
            "sweep": [c.to_dict() for c in cands_on_best],
        },
        "seconds": round(time.time() - t0, 2),
    }

    # promote the winning graph + SVG so the sheets and outputs/ have something real
    winner, tag = (chosen_on_best, "autoOnBest")
    if chosen and (not chosen_on_best or chosen.error < chosen_on_best.error):
        winner, tag = chosen, "auto"
    if winner is not None:
        gp = GRAPHS / track / f"{image}.json"
        winner.graph.save(gp)
        sp = OUTPUTS / track / f"{image}.svg"
        svgio.write_graph_svg(winner.graph, sp, view_box=src.view_box)
        rec["promoted"] = {"which": tag, "lam": winner.lam,
                           "graph": str(gp.relative_to(REPO)),
                           "svg": str(sp.relative_to(REPO))}
        # Colour-independent raster cross-check at the drawing's own resolution.
        # NOT src/compare.js here: that diffs colour on a fixed canvas, so a
        # re-emitted black centerline SVG scores ~3.7% against a coloured input for
        # no geometric reason at all.
        rec["rasterInk"] = metrics.raster_ink_diff(winner.graph, src)
    return rec


# A shorter sweep than the full DEFAULT_LAMBDAS: the leaderboard runs it 80 times,
# and candidate dedup means the extra points mostly re-score identical graphs.
LEADERBOARD_LAMBDAS = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0)


def leaderboard(images: list[str], tracks: list[str], *, jobs: int = 4,
                lambdas=LEADERBOARD_LAMBDAS, tolerance: float = 0.10,
                with_headroom: bool = False, out: Path | None = None) -> dict:
    work = [(t, i, tuple(lambdas), tolerance, with_headroom)
            for t in tracks for i in images]
    results: list[dict] = []
    t0 = time.time()

    def snapshot() -> dict:
        return {
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seconds": round(time.time() - t0, 1),
            "complete": len(results) == len(work),
            "cells": f"{len(results)}/{len(work)}",
            "images": images,
            "tracks": tracks,
            "lambdas": list(lambdas),
            "tolerance": tolerance,
            "results": results,
        }

    def flush() -> None:
        # Write after every cell. An 80-cell run takes long enough that losing it
        # all to an interruption is a real cost, and a partial table is still useful.
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(snapshot(), indent=1))

    if jobs > 1:
        with Pool(jobs) as pool:
            for i, rec in enumerate(pool.imap_unordered(_pair_job, work), 1):
                results.append(rec)
                flush()
                print(f"  [{i}/{len(work)}] {rec['track']}/{rec['image']}: {rec['status']} "
                      f"({rec.get('seconds', 0)}s)", flush=True)
    else:
        for i, w in enumerate(work, 1):
            rec = _pair_job(w)
            results.append(rec)
            flush()
            print(f"  [{i}/{len(work)}] {rec['track']}/{rec['image']}: {rec['status']}",
                  flush=True)
    return snapshot()


# ------------------------------------------------------------------- reporting


def _fmt(v, spec="6.4f"):
    if v is None:
        return "  --  "
    try:
        return format(float(v), spec)
    except (TypeError, ValueError):
        return str(v)


def leaderboard_markdown(data: dict) -> str:
    by = {(r["track"], r["image"]): r for r in data["results"]}
    lines: list[str] = []
    lines.append("# Cross-backend leaderboard\n")
    lines.append(f"Generated {data['generated']} · {data['seconds']}s · "
                 f"tolerance {data['tolerance']:.0%} · "
                 f"lambdas {min(data['lambdas'])}..{max(data['lambdas'])}\n")
    lines.append("`published` = the track's own best variant, scored as it shipped. "
                 "`auto` = automatic width-aware pruning selected by this harness, "
                 "starting from that track's least-processed variant.\n")
    lines.append("Error is symmetric difference as a fraction of source ink area "
                 "(lower is better).\n")

    for image in data["images"]:
        rows = []
        for track in data["tracks"]:
            r = by.get((track, image))
            if not r or r.get("status") != "ok":
                continue
            pub = r["publishedBest"]
            auto = r.get("auto", {}).get("metrics")
            aob = r.get("autoOnBest", {}).get("metrics")
            rows.append((track, pub, auto, aob, r))
        if not rows:
            continue
        rows.sort(key=lambda t: min(
            [x["sym_diff_ratio"] for x in (t[1], t[2], t[3]) if x] or [9e9]))
        lines.append(f"\n## {image}\n")
        lines.append("| backend | published err | published IoU | auto err | auto λ "
                     "| auto IoU | best err | branches | ctrl pts | raster sym |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for track, pub, auto, aob, r in rows:
            best = min([x for x in (pub, auto, aob) if x],
                       key=lambda x: x["sym_diff_ratio"])
            lines.append(
                f"| {track} | {_fmt(pub['sym_diff_ratio'])} | {_fmt(pub['iou'])} "
                f"| {_fmt(auto['sym_diff_ratio']) if auto else '  --  '} "
                f"| {_fmt(r['auto'].get('lam'), '4.2f')} "
                f"| {_fmt(auto['iou']) if auto else '  --  '} "
                f"| **{_fmt(best['sym_diff_ratio'])}** | {best['edges']} "
                f"| {best['control_points']} | {_fmt((r.get('rasterInk') or {}).get('symDiffRatio'))} |"
            )
    return "\n".join(lines) + "\n"


def summary_markdown(data: dict) -> str:
    """Does automatic selection beat the tracks' hand-tuned thresholds?"""
    per_track: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    for r in data["results"]:
        if r.get("status") != "ok":
            continue
        pub = r["publishedBest"]["sym_diff_ratio"]
        auto = (r.get("auto", {}).get("metrics") or {}).get("sym_diff_ratio")
        aob = (r.get("autoOnBest", {}).get("metrics") or {}).get("sym_diff_ratio")
        per_track[r["track"]].append((pub, auto, aob))

    lines = ["\n# Automatic pruning vs the tracks' own thresholds\n"]
    lines.append("| backend | images | auto better | auto worse | median published err "
                 "| median auto err | median best-of err |")
    lines.append("|---|---|---|---|---|---|---|")

    def med(vals):
        v = sorted(x for x in vals if x is not None)
        return v[len(v) // 2] if v else None

    for track, rows in sorted(per_track.items()):
        better = sum(1 for p, a, _ in rows if a is not None and a < p - 1e-9)
        worse = sum(1 for p, a, _ in rows if a is not None and a > p + 1e-9)
        best = [min([x for x in r if x is not None]) for r in rows]
        lines.append(
            f"| {track} | {len(rows)} | {better} | {worse} | "
            f"{_fmt(med([r[0] for r in rows]))} | {_fmt(med([r[1] for r in rows]))} | "
            f"{_fmt(med(best))} |"
        )
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------- cli


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_inc = sub.add_parser("incumbent", help="run the incumbent pipeline into the graph model")
    p_inc.add_argument("--images", nargs="*", default=REAL_IMAGES)
    p_inc.add_argument("--force", action="store_true")

    p_score = sub.add_parser("score", help="score graph files as published")
    p_score.add_argument("graphs", nargs="+")
    p_score.add_argument("--raster", action="store_true", help="add the raster cross-check")

    p_sel = sub.add_parser("select", help="sweep pruning strengths and choose")
    p_sel.add_argument("--graph", required=True)
    p_sel.add_argument("--tolerance", type=float, default=0.10)
    p_sel.add_argument("--out", default=None)

    p_lb = sub.add_parser("leaderboard", help="score every track on every image")
    p_lb.add_argument("--images", nargs="*", default=REAL_IMAGES)
    p_lb.add_argument("--tracks", nargs="*", default=TRACKS + ["incumbent"])
    p_lb.add_argument("--jobs", type=int, default=4)
    p_lb.add_argument("--tolerance", type=float, default=0.10)
    p_lb.add_argument("--headroom", action="store_true",
                      help="also run selection on each track's best variant (2x cost)")
    p_lb.add_argument("--out", default=str(DEBUG / "metrics.json"))

    args = ap.parse_args()

    if args.cmd == "incumbent":
        recs = run_incumbent(args.images, force=args.force)
        path = DEBUG / "incumbent.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(recs, indent=2))
        for r in recs:
            print(f"{r['image']:18s} edges {r['edges']:4d} strokes {r['strokes']:3d} "
                  f"len {r['totalLength']:9.1f} -> {r['graph']}")
        return 0

    if args.cmd == "score":
        rows = []
        for gpath in args.graphs:
            rec = score_one(Path(gpath))
            if rec is None:
                print(f"unresolved source: {gpath}")
                continue
            rows.append(rec)
            print(f"{Path(gpath).name:44s} IoU {rec['iou']:.4f} sym {rec['sym_diff_ratio']:.4f} "
                  f"bMed {rec['boundary_median']:.2f} bP95 {rec['boundary_p95']:.2f} "
                  f"edges {rec['edges']:4d} cp {rec['control_points']:5d}")
        return 0

    if args.cmd == "select":
        gpath = Path(args.graph)
        svg = resolve.resolve_source_svg(gpath)
        src = source_for(str(svg))
        g = CenterlineGraph.load(gpath)
        chosen, cands = select.select(g, src, tolerance=args.tolerance)
        for c in cands:
            mark = " <== chosen" if chosen and c.lam == chosen.lam else ""
            print(f"lam {c.lam:5.2f} sym {c.error:.4f} IoU {c.metrics.iou:.4f} "
                  f"miss {c.metrics.missing_ratio:.4f} edges {c.metrics.edges:4d} "
                  f"cp {c.metrics.control_points:5d}{mark}")
        if chosen and args.out:
            out = Path(args.out)
            chosen.graph.save(out / f"{gpath.stem}.json")
            svgio.write_graph_svg(chosen.graph, out / f"{gpath.stem}.svg",
                                  view_box=src.view_box)
            print(f"wrote {out}")
        return 0

    if args.cmd == "leaderboard":
        out = Path(args.out)
        data = leaderboard(args.images, args.tracks, jobs=args.jobs,
                           tolerance=args.tolerance, with_headroom=args.headroom,
                           out=out)
        out.write_text(json.dumps(data, indent=1))
        md = leaderboard_markdown(data) + summary_markdown(data)
        (DEBUG / "leaderboard.md").write_text(md)
        print(md)
        print(f"\nwrote {out} and {DEBUG / 'leaderboard.md'}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
