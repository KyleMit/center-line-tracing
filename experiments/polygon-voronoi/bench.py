"""Re-runnable benchmark / parameter sweep for the polygon-Voronoi track.

    python3 experiments/polygon-voronoi/bench.py sweep-synthetic
    python3 experiments/polygon-voronoi/bench.py bench --inputs inputs/house-wide.svg
    python3 experiments/polygon-voronoi/bench.py best

Writes ``debug/polygon-voronoi/metrics.json`` (+ ``sweep-*.json``), graph JSON to
``debug/polygon-voronoi/graphs/``, and stroked SVGs to
``debug/polygon-voronoi/svg/`` (promoted results are copied to
``outputs/polygon-voronoi/``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
from shapely.geometry import MultiLineString
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backends  # noqa: E402
import failures  # noqa: E402
import graphmodel  # noqa: E402
import metrics as M  # noqa: E402
from svgpoly import load_svg  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEBUG = os.path.join(ROOT, "debug", "polygon-voronoi")
SYNTH = os.path.join(DEBUG, "synthetic")
OUTPUTS = os.path.join(ROOT, "outputs", "polygon-voronoi")

REAL_LADDER = [
    "inputs/house-wide.svg",
    "inputs/butterfly-wide.svg",
    "inputs/boat-tall.svg",
    "inputs/island-tall.svg",
    "inputs/balloon-tall.svg",
    "inputs/home-wide.svg",
    "inputs/house-tall.svg",
    "inputs/dinosaur-wide.svg",
    "inputs/landscape-square.svg",
    "inputs/sun-square.svg",
]


# --------------------------------------------------------------------------


def _params_for(backend: str, cfg: dict) -> dict:
    if backend == "pygeoops":
        return {k: cfg[k] for k in
                ("densify_distance", "min_branch_length", "simplifytolerance", "extend")
                if k in cfg}
    if backend == "fitodic+filter":
        return {k: cfg[k] for k in
                ("interpolation_distance", "min_branch_length", "simplifytolerance")
                if k in cfg}
    return {k: cfg[k] for k in ("interpolation_distance",) if k in cfg}


REFERENCE_TOLERANCE = 0.02
_ref_cache: dict[str, object] = {}


def reference_geometry(svg_path: str):
    """High-fidelity geometry every result is scored against.

    Scoring against the *swept* flattening of the same file would hide
    flattening error: a coarse polygon is easy to reconstruct with a coarse
    centerline, and IoU would improve as the shape got worse.  All region
    metrics therefore compare against this fixed 0.02-unit flattening.
    """
    if svg_path not in _ref_cache:
        d = load_svg(svg_path, tolerance=REFERENCE_TOLERANCE)
        _ref_cache[svg_path] = unary_union([e.geometry for e in d.elements])
    return _ref_cache[svg_path]


def run_one(svg_path: str, backend: str, tolerance: float, cfg: dict,
            truth: dict | None = None, save_prefix: str | None = None) -> dict:
    """Full pipeline for one SVG at one parameter setting."""
    t_load = time.perf_counter()
    doc = load_svg(svg_path, tolerance=tolerance)
    load_s = time.perf_counter() - t_load
    if not doc.elements:
        return {"error": "no filled elements"}

    source = reference_geometry(svg_path)
    flattened = unary_union([e.geometry for e in doc.elements])
    params = _params_for(backend, cfg)

    graphs, backend_s, n_parts, errors = [], 0.0, 0, []
    for el in doc.elements:
        for poly in el.geometry.geoms:
            n_parts += 1
            res = backends.run(backend, poly, **params)
            backend_s += res.seconds
            if res.error:
                errors.append(res.error)
                continue
            if res.lines.is_empty:
                continue
            graphs.append(graphmodel.build_graph(
                res.lines, poly, source_element_id=el.element_id))

    g = graphmodel.merge_graphs(graphs, meta={
        "backend": backend,
        "flatten_tolerance": tolerance,
        "params": params,
        "source": os.path.relpath(svg_path, ROOT),
        "radiusSource": "derived-distance-to-boundary",
        "radiusNote": "polygon-Voronoi carries no native radius; sampled from "
                      "distance-to-boundary of the source Shapely polygon",
    })

    recon = graphmodel.restroke(g)
    row = {
        "svg": os.path.relpath(svg_path, ROOT),
        "backend": backend,
        "tolerance": tolerance,
        "params": params,
        "elements": len(doc.elements),
        "polygons": n_parts,
        "boundary_points": sum(e.n_boundary_points for e in doc.elements),
        "repaired_elements": sum(1 for e in doc.elements if e.repaired),
        "load_s": round(load_s, 4),
        "backend_s": round(backend_s, 4),
        "s_per_element": round(backend_s / max(1, len(doc.elements)), 4),
        "errors": errors[:3],
        "avg_width": round(backends.average_width(source), 3),
        # How much shape was lost by flattening alone, before any centerline work.
        "flatten_iou": round(M.iou(source, flattened), 5),
    }
    row.update({f"cx_{k}": v for k, v in M.complexity(g).items()})
    row["iou"] = round(M.iou(source, recon), 5)
    row["symdiff"] = round(M.symmetric_difference_area(source, recon), 2)
    row["symdiff_frac"] = round(row["symdiff"] / source.area, 5) if source.area else None
    bd = M.boundary_distance(source, recon)
    row["bdist_median"] = round(bd["median"], 4)
    row["bdist_p95"] = round(bd["p95"], 4)

    fc = failures.classify(g, source, recon, n_parts, row["avg_width"])
    row["components"] = fc["components"]
    row.update({f"tag_{k.replace(' ', '_')}": v for k, v in fc["tags"].items()})
    row["tag_total"] = sum(fc["tags"].values())
    if source.area:
        row["cap_missed_frac"] = round(fc["cap_missed_area"] / source.area, 5)
        row["join_missed_frac"] = round(fc["join_missed_area"] / source.area, 5)

    if truth:
        ce = M.centerline_error(g.to_multilinestring(), truth["centerlines"])
        row.update({f"cl_{k}": round(v, 4) for k, v in ce.items()})
        we = M.width_error(g, truth.get("width"))
        row.update({f"w_{k}": (round(v, 4) if isinstance(v, float) else v)
                    for k, v in we.items()})

    if save_prefix:
        gp = os.path.join(DEBUG, "graphs", f"{save_prefix}.json")
        g.save(gp)
        row["graph"] = os.path.relpath(gp, ROOT)
        sp = os.path.join(DEBUG, "svg", f"{save_prefix}.svg")
        os.makedirs(os.path.dirname(sp), exist_ok=True)
        with open(sp, "w") as f:
            f.write(_svg_doc(doc, g))
        row["out_svg"] = os.path.relpath(sp, ROOT)
    return row


def _svg_doc(doc, g) -> str:
    vb = doc.viewbox
    body = "\n".join("  " + p for p in graphmodel.to_svg_paths(g))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'viewBox="{vb[0]} {vb[1]} {vb[2]} {vb[3]}" '
        f'width="{doc.width}" height="{doc.height}">\n{body}\n</svg>\n'
    )


# --------------------------------------------------------------------------
# sweeps
# --------------------------------------------------------------------------

TOLERANCES = [0.05, 0.15, 0.5, 1.5, 4.0]
PYGEOOPS_BRANCH = [0.0, -0.25, -0.5, -1.0, -2.0]
FITODIC_INTERP = [0.25, 0.5, 1.0, 2.0, 4.0]

# The 2-D surface the handoff asks for: flattening tolerance x library knob.
GRIDS = {
    # A: pygeoops' width-relative branch filter -- the Track 8 comparison point.
    "branch": ("pygeoops", "min_branch_length", PYGEOOPS_BRANCH,
               {"densify_distance": -0.5, "simplifytolerance": -0.25, "extend": False}),
    # A2: the same branch filter with simplification OFF, which is the setting
    # the synthetic sweep showed is actually usable on curved strokes.
    "branch0": ("pygeoops", "min_branch_length", PYGEOOPS_BRANCH,
                {"densify_distance": -0.5, "simplifytolerance": 0.0, "extend": False}),
    # F: fitodic's Voronoi with pygeoops' branch filter bolted on, to separate
    # "which Voronoi" from "does it prune".
    "interp_filtered": ("fitodic+filter", "interpolation_distance", FITODIC_INTERP,
                        {"min_branch_length": -1.0, "simplifytolerance": 0.0}),
    # E: cap handling -- pygeoops can extend the axis out to the polygon edge.
    "extend": ("pygeoops", "extend", [False, True],
               {"densify_distance": -0.5, "min_branch_length": -1.0,
                "simplifytolerance": 0.0}),
    # B: pygeoops' output simplification -- suspected cause of curve error.
    "simplify": ("pygeoops", "simplifytolerance", [0.0, -0.02, -0.05, -0.1, -0.25],
                 {"densify_distance": -0.5, "min_branch_length": -1.0, "extend": False}),
    # C: pygeoops' own boundary densification.
    "densify": ("pygeoops", "densify_distance", [0.0, -0.1, -0.25, -0.5, -1.0],
                {"simplifytolerance": -0.05, "min_branch_length": -1.0, "extend": False}),
    # D: fitodic's only knob.
    "interp": ("fitodic", "interpolation_distance", FITODIC_INTERP, {}),
}


def load_manifest() -> list[dict]:
    with open(os.path.join(SYNTH, "manifest.json")) as f:
        return json.load(f)


def select_cases(cases: list[str] | None) -> list[dict]:
    man = load_manifest()
    if cases:
        want = set(cases)
        man = [c for c in man if c["slug"] in want or str(c["num"]) in want
               or c["name"] in want]
    return man


def sweep_synthetic(cases: list[str] | None, grids: list[str],
                    out_name: str = "sweep-synthetic.json",
                    tolerances: list[float] | None = None):
    tolerances = tolerances or TOLERANCES
    rows = []
    for case in select_cases(cases):
        svg = os.path.join(ROOT, case["svg"])
        for gname in grids:
            backend, knob_name, values, fixed = GRIDS[gname]
            for tol in tolerances:
                for v in values:
                    cfg = dict(fixed)
                    cfg[knob_name] = v
                    r = run_one(svg, backend, tol, cfg, truth=case)
                    r.update(case=case["slug"], curve_native=case["curve_native"],
                             grid=gname, knob=v, knob_name=knob_name)
                    rows.append(r)
        print(f"  swept {case['slug']}", flush=True)
    path = os.path.join(DEBUG, out_name)
    os.makedirs(DEBUG, exist_ok=True)
    with open(path, "w") as f:
        json.dump(rows, f)
    print(f"wrote {path} ({len(rows)} rows)")
    return rows


def _fmt(v, w=8, p=4):
    if v is None:
        return " " * (w - 1) + "-"
    if isinstance(v, float):
        if v == float("inf"):
            return " " * (w - 3) + "inf"
        return f"{v:{w}.{p}f}"
    return f"{str(v):>{w}s}"


def print_surface(rows, metric="cl_hausdorff_p95", grid="branch", agg=None):
    sel = [r for r in rows if r.get("grid") == grid]
    if not sel:
        return
    backend, knob_name, _, _ = GRIDS[grid]
    tols = sorted({r["tolerance"] for r in sel})
    knobs = sorted({r["knob"] for r in sel})
    cases = sorted({r["case"] for r in sel})
    print(f"\n### grid '{grid}' ({backend}.{knob_name}) -- {metric}")
    print(f"    rows = {knob_name}, cols = flattening tolerance")
    if agg:
        print("case".ljust(18) + "".join(f"{t:>9g}" for t in tols))
    for k in knobs:
        print(f"\n  {knob_name} = {k}")
        print("    " + "case".ljust(16) + "".join(f"{t:>9g}" for t in tols))
        for c in cases:
            line = "    " + f"{c:16s}"
            for t in tols:
                m = [r for r in sel if r["case"] == c and r["tolerance"] == t
                     and r["knob"] == k]
                line += _fmt(m[0].get(metric) if m else None, 9, 3)
            print(line)


def print_knob_summary(rows, grid, metrics_list):
    """Median across cases for each (tolerance, knob) -- the compact surface."""
    sel = [r for r in rows if r.get("grid") == grid]
    if not sel:
        return
    backend, knob_name, _, _ = GRIDS[grid]
    tols = sorted({r["tolerance"] for r in sel})
    knobs = sorted({r["knob"] for r in sel})
    for metric in metrics_list:
        print(f"\n### grid '{grid}' ({backend}.{knob_name}) -- median {metric} "
              f"across {len({r['case'] for r in sel})} cases")
        print("    " + f"{knob_name:>16s}" + "".join(f"{t:>10g}" for t in tols))
        for k in knobs:
            line = "    " + f"{k:>16g}"
            for t in tols:
                vals = [r.get(metric) for r in sel
                        if r["tolerance"] == t and r["knob"] == k
                        and isinstance(r.get(metric), (int, float))]
                line += f"{np.median(vals):10.3f}" if vals else f"{'-':>10}"
            print(line)


def sweep_real(inputs, grids, out_name="sweep-real.json", tolerances=None):
    """Same 2-D surface as the synthetic sweep, on real artwork.

    Real inputs have no ground truth, so the columns that matter here are
    reconstruction (IoU / symdiff) and complexity (edges / terminals) rather
    than centerline error.
    """
    tolerances = tolerances or [0.1, 0.25, 0.75, 2.0]
    rows = []
    for p in inputs:
        full = os.path.join(ROOT, p)
        name = os.path.basename(p)[:-4]
        for gname in grids:
            backend, knob_name, values, fixed = GRIDS[gname]
            for tol in tolerances:
                for v in values:
                    cfg = dict(fixed)
                    cfg[knob_name] = v
                    r = run_one(full, backend, tol, cfg)
                    r.update(case=name, grid=gname, knob=v, knob_name=knob_name)
                    rows.append(r)
            print(f"  {name} / {gname} done", flush=True)
    path = os.path.join(DEBUG, out_name)
    with open(path, "w") as f:
        json.dump(rows, f)
    print(f"wrote {path} ({len(rows)} rows)")
    return rows


def bench_real(inputs, backend, tolerance, cfg, out_name="metrics.json"):
    rows = []
    for p in inputs:
        full = os.path.join(ROOT, p)
        name = os.path.basename(p)[:-4]
        r = run_one(full, backend, tolerance, cfg,
                    save_prefix=f"{name}-{backend}")
        r["image"] = name
        rows.append(r)
        print(f"  {name:22s} IoU {r.get('iou')}  edges {r.get('cx_edges')}  "
              f"{r.get('backend_s')}s  ({r.get('s_per_element')}s/el)", flush=True)
    path = os.path.join(DEBUG, out_name)
    with open(path, "w") as f:
        json.dump(rows, f, indent=1)
    print(f"wrote {path}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sweep-synthetic", "sweep-real", "bench", "one"])
    ap.add_argument("--cases", nargs="*")
    ap.add_argument("--grids", nargs="*", default=["branch", "simplify", "densify", "interp"])
    ap.add_argument("--inputs", nargs="*")
    ap.add_argument("--tolerances", nargs="*", type=float)
    ap.add_argument("--backend", default="pygeoops")
    ap.add_argument("--tolerance", type=float, default=0.5)
    ap.add_argument("--densify", type=float, default=-0.5)
    ap.add_argument("--branch", type=float, default=-1.0)
    ap.add_argument("--simplify", type=float, default=-0.05)
    ap.add_argument("--interp", type=float, default=1.0)
    ap.add_argument("--out", default="sweep-synthetic.json")
    a = ap.parse_args()

    cfg = ({"densify_distance": a.densify, "min_branch_length": a.branch,
            "simplifytolerance": a.simplify, "extend": False}
           if a.backend == "pygeoops" else {"interpolation_distance": a.interp})

    if a.cmd == "sweep-synthetic":
        rows = sweep_synthetic(a.cases, a.grids, a.out, a.tolerances)
        for g in a.grids:
            print_knob_summary(rows, g,
                               ["cl_hausdorff_p95", "iou", "cx_edges", "s_per_element"])
    elif a.cmd == "sweep-real":
        rows = sweep_real(a.inputs or REAL_LADDER[:4], a.grids, a.out, a.tolerances)
        for g in a.grids:
            print_knob_summary(rows, g, ["iou", "symdiff_frac", "cx_edges",
                                         "cx_terminals", "s_per_element"])
    elif a.cmd == "bench":
        bench_real(a.inputs or REAL_LADDER, a.backend, a.tolerance, cfg, a.out)
    elif a.cmd == "one":
        for p in (a.inputs or ["inputs/house-wide.svg"]):
            r = run_one(os.path.join(ROOT, p), a.backend, a.tolerance, cfg,
                        save_prefix=f"{os.path.basename(p)[:-4]}-{a.backend}")
            print(json.dumps(r, indent=1))


if __name__ == "__main__":
    main()
