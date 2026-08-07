"""Track 7 runner: SVG -> flattened polygon -> engine -> graph -> re-stroke -> metrics.

Usage:
  python3 run.py bench --set synthetic [--engine boost|cgal] [--prune 1.0]
  python3 run.py bench --set real
  python3 run.py one <path/to.svg> [--engine boost]

Writes debug/native-geometry/{graphs,restroke,metrics-<engine>-<set>.json}.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import svgpoly
import metrics as M
from graph import restroke_svg, restroke_geometry

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
DEBUG = os.path.join(ROOT, "debug", "native-geometry")
SYNTH = os.path.join(DEBUG, "synthetic")
REAL = os.path.join(ROOT, "inputs")

REAL_ORDER = [
    "house-wide.svg",
    "butterfly-wide.svg",
    "boat-tall.svg",
    "island-tall.svg",
    "balloon-tall.svg",
    "home-wide.svg",
    "house-tall.svg",
    "dinosaur-wide.svg",
    "landscape-square.svg",
    "sun-square.svg",
]


def build_graph(engine, polys, sources, opts):
    if engine == "boost":
        import backend_boost

        return backend_boost.medial_axis_graph(
            polys,
            sources,
            scale=opts.get("scale", 100.0),
            parabola_tol=opts.get("parabola_tol", 0.1),
            r_eps=opts.get("r_eps", 0.25),
        )
    if engine == "cgal":
        import backend_cgal

        return backend_cgal.straight_skeleton_graph(polys, sources)
    raise SystemExit(f"unknown engine {engine}")


def process(svg_path, engine="boost", prune_k=1.0, flatness=0.05, opts=None, tag=""):
    opts = opts or {}
    name = os.path.splitext(os.path.basename(svg_path))[0]
    t_all = time.perf_counter()

    t0 = time.perf_counter()
    els = svgpoly.load_filled_elements(svg_path, flatness=flatness)
    polys, sources = [], []
    for e in els:
        for p in e.polygons:
            polys.append(p)
            sources.append(e.element_id)
    flatten_ms = (time.perf_counter() - t0) * 1000.0

    if not polys:
        return None

    graph, timing = build_graph(engine, polys, sources, opts)
    t0 = time.perf_counter()
    graph = graph.contract_chains()
    graph = graph.prune_tips(prune_k)
    graph = graph.drop_short_components(opts.get("min_component", 0.0))
    graph_ms = (time.perf_counter() - t0) * 1000.0

    orig = svgpoly.total_geometry(els)
    recon = restroke_geometry(graph, simplify_tol=opts.get("simplify", 0.0))
    total_ms = (time.perf_counter() - t_all) * 1000.0

    w, h = svgpoly.svg_viewbox(svg_path)
    row = {
        "name": name,
        "engine": engine,
        "tag": tag,
        "elements": len(els),
        "polygons": len(polys),
        "boundary_segments": timing.get("segments"),
        "raw_voronoi_edges": timing.get("raw_edges"),
        "runtime_ms": {
            "flatten": round(flatten_ms, 1),
            "engine": round(timing.get("voronoi_ms", timing.get("engine_ms", 0.0)), 1),
            "filter": round(timing.get("filter_ms", 0.0), 1),
            "graph": round(graph_ms, 1),
            "total": round(total_ms, 1),
        },
        "params": {
            "flatness": flatness,
            "prune_k": prune_k,
            **{k: v for k, v in opts.items()},
        },
    }
    row.update(M.complexity_metrics(graph))
    row.update(M.area_metrics(orig, recon))
    row.update(M.boundary_metrics(orig, recon))

    gt_path = os.path.join(os.path.dirname(svg_path), name + ".json")
    truth_radius = None
    if os.path.exists(gt_path):
        with open(gt_path) as f:
            gt = json.load(f)
        truth_radius = gt.get("radius")
        row["case"] = {k: gt[k] for k in ("id", "name", "cap", "join") if k in gt}
        row.update(M.centerline_metrics(graph, gt.get("centerlines", [])))
    row.update(M.width_metrics(graph, truth_radius if not (gt_path and os.path.exists(gt_path) and json.load(open(gt_path)).get("variable_width")) else None))

    return {"row": row, "graph": graph, "width": w, "height": h, "orig": orig, "recon": recon}


def write_artifacts(result, engine, subdir):
    graph, row = result["graph"], result["row"]
    gdir = os.path.join(DEBUG, "graphs", engine, subdir)
    rdir = os.path.join(DEBUG, "restroke", engine, subdir)
    os.makedirs(gdir, exist_ok=True)
    os.makedirs(rdir, exist_ok=True)
    graph.write_json(
        os.path.join(gdir, row["name"] + ".json"),
        meta={
            "engine": engine,
            "source": row["name"],
            "params": row["params"],
            "boost_version": "1.83.0" if engine == "boost" else None,
        },
    )
    svg = restroke_svg(graph, result["width"], result["height"])
    with open(os.path.join(rdir, row["name"] + ".svg"), "w") as f:
        f.write(svg)


def bench(args):
    if args.set == "synthetic":
        with open(os.path.join(SYNTH, "index.json")) as f:
            names = json.load(f)
        files = [os.path.join(SYNTH, n + ".svg") for n in names]
        subdir = "synthetic"
    else:
        files = [os.path.join(REAL, n) for n in REAL_ORDER]
        if args.limit:
            files = files[: args.limit]
        subdir = "real"

    opts = {}
    if args.simplify:
        opts["simplify"] = args.simplify
    if args.min_component:
        opts["min_component"] = args.min_component

    rows = []
    for f in files:
        if not os.path.exists(f):
            continue
        try:
            res = process(f, args.engine, args.prune, args.flatness, opts, args.tag)
        except Exception as exc:  # keep the bench going; record the failure
            rows.append({"name": os.path.basename(f), "error": repr(exc)})
            print(f"{os.path.basename(f):28s} ERROR {exc}")
            continue
        if res is None:
            continue
        write_artifacts(res, args.engine, subdir)
        rows.append(res["row"])
        r = res["row"]
        cl = r.get("centerline_recovered_to_truth", {})
        print(
            f"{r['name']:26s} IoU {r.get('iou', 0):.4f}  symdiff {100 * (r.get('symdiff_frac') or 0):6.2f}%  "
            f"strokes {r['strokes']:4d}  br {r['branch_nodes']:3d}  "
            f"cl-med {cl.get('median', '-')!s:>7}  p95 {cl.get('p95', '-')!s:>7}  "
            f"{r['runtime_ms']['total']:.0f}ms"
        )

    out = os.path.join(DEBUG, f"metrics-{args.engine}-{args.set}.json")
    with open(out, "w") as f:
        json.dump({"rows": rows, "generated_by": "experiments/native-geometry/py/run.py"}, f, indent=1)
    print("->", out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bench")
    b.add_argument("--set", default="synthetic", choices=["synthetic", "real"])
    b.add_argument("--engine", default="boost")
    b.add_argument("--prune", type=float, default=1.0)
    b.add_argument("--flatness", type=float, default=0.05)
    b.add_argument("--simplify", type=float, default=0.0)
    b.add_argument("--min-component", dest="min_component", type=float, default=0.0)
    b.add_argument("--limit", type=int, default=0)
    b.add_argument("--tag", default="")
    b.set_defaults(func=bench)

    o = sub.add_parser("one")
    o.add_argument("svg")
    o.add_argument("--engine", default="boost")
    o.add_argument("--prune", type=float, default=1.0)
    o.add_argument("--flatness", type=float, default=0.05)
    o.add_argument("--simplify", type=float, default=0.0)
    o.add_argument("--min-component", dest="min_component", type=float, default=0.0)
    o.add_argument("--tag", default="")

    def one(args):
        opts = {}
        if args.simplify:
            opts["simplify"] = args.simplify
        if args.min_component:
            opts["min_component"] = args.min_component
        res = process(args.svg, args.engine, args.prune, args.flatness, opts, args.tag)
        sub = "synthetic" if "/synthetic/" in args.svg else "real"
        write_artifacts(res, args.engine, sub)
        print(json.dumps(res["row"], indent=1))

    o.set_defaults(func=one)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
