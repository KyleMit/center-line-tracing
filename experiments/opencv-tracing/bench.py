"""The one re-runnable `bench` command for the `opencv-tracing` track.

    python3 experiments/opencv-tracing/bench.py            # corpus + real ladder
    python3 experiments/opencv-tracing/bench.py --targets case-15 house-wide
    python3 experiments/opencv-tracing/bench.py --matrix thinning tracer

Writes:
    debug/opencv-tracing/metrics.json      every run, every config
    debug/opencv-tracing/graphs/*.json     common graph model, best config per image
    outputs/opencv-tracing/*.svg           promoted re-stroked SVGs
and prints a table.

Runtime is measured deliberately and prominently, because speed is this track's
entire reason to exist (report §16). `--speed` additionally times Track 3's
primitives (`skimage.morphology.medial_axis` / `skeletonize`) on byte-identical
masks, which is the honest way to state the quality-vs-speed tradeoff.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import numpy as np

import corpus
import metrics as M
import pipeline
import svgraster
import tracers

ROOT = Path(__file__).resolve().parents[2]
DEBUG = ROOT / "debug" / "opencv-tracing"
CORPUS = DEBUG / "corpus"
OUTPUTS = ROOT / "outputs" / "opencv-tracing"
MASKS = DEBUG / "masks"

REAL_LADDER = ["house-wide", "dinosaur-wide", "butterfly-wide", "landscape-square",
               "sun-square"]

DEFAULT_CONFIG = {
    "scale": 4.0,
    "thinning": "zhangsuen",
    "tracer": "st-c",
    "csize": 10,
    "simplify_px": 0.5,
    "cap_extend": "round",
}


# ---------------------------------------------------------------------------
# targets
# ---------------------------------------------------------------------------

def resolve_targets(names: list[str] | None) -> list[dict]:
    if not CORPUS.joinpath("manifest.json").exists():
        corpus.build(CORPUS)
    manifest = json.loads((CORPUS / "manifest.json").read_text())

    targets = []
    for case in manifest:
        targets.append({"name": Path(case["file"]).stem, "kind": "synthetic",
                        "path": CORPUS / case["file"], "groundTruth": case["groundTruth"]})
    for name in REAL_LADDER:
        path = ROOT / "inputs" / f"{name}.svg"
        if path.exists():
            targets.append({"name": name, "kind": "real", "path": path,
                            "groundTruth": None})

    if not names:
        return targets
    picked = []
    for want in names:
        hits = [t for t in targets if t["name"] == want or t["name"].startswith(want)]
        if not hits:
            raise SystemExit(f"no target matching {want!r}")
        picked.extend(hits)
    return picked


# ---------------------------------------------------------------------------
# one run
# ---------------------------------------------------------------------------

def run_one(target: dict, config: dict, save_artifacts: bool = False) -> dict:
    svg_text = target["path"].read_text()
    mask_dir = MASKS / target["name"] / f"s{config['scale']:g}"

    t0 = time.perf_counter()
    rasters, raster_meta = svgraster.rasterize_elements(svg_text, mask_dir, config["scale"])
    rasterize_s = time.perf_counter() - t0

    graphs = []
    t0 = time.perf_counter()
    for i, raster in enumerate(rasters):
        graphs.append(pipeline.process_element(
            raster, i, thinning=config["thinning"], tracer=config["tracer"],
            cap_extend=config["cap_extend"], csize=config["csize"],
            simplify_px=config["simplify_px"]))
    extract_s = time.perf_counter() - t0

    stage = {key: float(sum(g.timings.get(key, 0.0) for g in graphs))
             for key in ("thin_s", "trace_s", "distance_s", "graph_s", "cap_extend_s")}
    total_px = int(sum(g.raster.mask.size for g in graphs))

    result = {
        "target": target["name"], "kind": target["kind"], "config": dict(config),
        "elements": len(rasters), "rasterPixels": total_px,
        "runtime": {
            "rasterize_s": rasterize_s,
            "extract_s": extract_s,
            **stage,
            "total_s": rasterize_s + extract_s,
            "extract_s_per_element": extract_s / max(1, len(rasters)),
            "extract_us_per_megapixel": (extract_s * 1e6) / max(1, total_px / 1e6) / 1e6,
        },
        "complexity": M.complexity(graphs),
        "tags": M.classify(graphs),
    }

    def aggregate(constant_width: bool) -> dict:
        recon = [M.reconstruction(g, constant_width) for g in graphs]
        if not recon:
            return {}
        orig = sum(r["originalArea"] for r in recon)
        return {
            "iou": float(np.average([r["iou"] for r in recon],
                                    weights=[r["originalArea"] for r in recon])),
            "symDiffArea": float(sum(r["symDiffArea"] for r in recon)),
            "symDiffFraction": float(sum(r["symDiffArea"] for r in recon) / orig) if orig else 0.0,
            "boundaryMedian": float(np.nanmedian([r["boundaryMedian"] for r in recon])),
            "boundaryP95": float(np.nanpercentile([r["boundaryP95"] for r in recon], 95)),
        }

    # Constant width per edge is the shape Common Setup asks for. The variable
    # profile scores the DERIVED per-vertex radii on their own terms — the only
    # way to tell whether sampling a distance transform actually recovers width,
    # which matters because this backend has no native radius at all.
    result["reconstruction"] = aggregate(True)
    result["reconstructionVariableWidth"] = aggregate(False)

    if target["groundTruth"]:
        result["centerline"] = M.centerline_error(graphs, target["groundTruth"])
        result["tags"]["wrong endpoint"] = M.wrong_endpoints(graphs, target["groundTruth"])

    if save_artifacts:
        viewbox = svgraster.read_viewbox(svg_text)
        (DEBUG / "graphs").mkdir(parents=True, exist_ok=True)
        (DEBUG / "graphs" / f"{target['name']}.json").write_text(json.dumps(
            pipeline.graph_to_json(graphs, target["name"], raster_meta, config), indent=1))
        OUTPUTS.mkdir(parents=True, exist_ok=True)
        (OUTPUTS / f"{target['name']}.svg").write_text(
            pipeline.graph_to_svg(graphs, viewbox))
        hair = DEBUG / "hairline"
        hair.mkdir(parents=True, exist_ok=True)
        (hair / f"{target['name']}.svg").write_text(
            pipeline.graph_to_svg(graphs, viewbox, hairline=True))

    return result


# ---------------------------------------------------------------------------
# skeletonizer speed comparison (report §16) — this track's core claim
# ---------------------------------------------------------------------------

def speed_comparison(targets: list[dict], scale: float, repeats: int = 3) -> dict:
    """Time every skeletonizer on byte-identical masks.

    Track 3's primitive is `medial_axis(return_distance=True)`; this track's is
    `cv2.ximgproc.thinning`. Same masks, same machine, same process — anything
    less and the speed claim is not worth making.
    """
    from skimage.morphology import medial_axis, skeletonize
    import skimage

    masks = []
    for target in targets:
        rasters, _ = svgraster.rasterize_elements(
            target["path"].read_text(), MASKS / target["name"] / f"s{scale:g}", scale)
        masks.extend(r.mask for r in rasters)

    total_px = sum(m.size for m in masks)

    def timed(fn):
        best = None
        for _ in range(repeats):
            t0 = time.perf_counter()
            for m in masks:
                fn(m)
            elapsed = time.perf_counter() - t0
            best = elapsed if best is None else min(best, elapsed)
        return best

    entries = {
        "cv2.ximgproc.thinning(ZHANGSUEN)": lambda m: pipeline.thin(m, "zhangsuen"),
        "cv2.ximgproc.thinning(GUOHALL)": lambda m: pipeline.thin(m, "guohall"),
        "skimage.medial_axis(return_distance=True)":
            lambda m: medial_axis(m, return_distance=True),
        "skimage.skeletonize(method='zhang')": lambda m: skeletonize(m, method="zhang"),
        "skimage.skeletonize(method='lee')": lambda m: skeletonize(m, method="lee"),
        "cv2.distanceTransform (radius recovery)": pipeline.distance_field,
    }

    results = {}
    for label, fn in entries.items():
        seconds = timed(fn)
        results[label] = {"seconds": seconds,
                          "megapixels_per_s": (total_px / 1e6) / seconds}

    # Tracers, on skeletons produced by the default thinner.
    skeletons = [pipeline.thin(m, "zhangsuen") for m in masks]
    tracer_results = {}
    for label, fn in (("st-c", tracers.st_c), ("st-js", tracers.st_js),
                      ("bespoke", tracers.bespoke), ("st-py", tracers.st_py)):
        if label == "st-py" and total_px > 4_000_000:
            tracer_results[label] = {"seconds": None,
                                     "note": "skipped: pure-Python reference is O(minutes) here"}
            continue
        t0 = time.perf_counter()
        for s in skeletons:
            fn(s)
        elapsed = time.perf_counter() - t0
        tracer_results[label] = {"seconds": elapsed,
                                 "megapixels_per_s": (total_px / 1e6) / elapsed}

    return {"maskMegapixels": total_px / 1e6, "maskCount": len(masks),
            "repeats": repeats, "skimage": skimage.__version__,
            "skeletonizers": results, "tracers": tracer_results}


# ---------------------------------------------------------------------------
# tracer agreement (the portability claim)
# ---------------------------------------------------------------------------

def tracer_agreement(targets: list[dict], config: dict,
                     py_pixel_budget: int = 2_000_000) -> dict:
    """Do the C, Python and JS ports of skeleton-tracing return the same polylines?

    If they do, "this pipeline ports to the browser unchanged" is a fact rather
    than a hope. Compared as sorted vertex multisets so polyline ordering does
    not count as a difference.

    `st-py` is upstream's own "super slow ... just for reference" implementation
    and is skipped above `py_pixel_budget` — it is minutes per megapixel, and
    checking it on the small targets already establishes the invariant.
    """
    def signature(polys):
        return sorted(tuple(map(tuple, p)) for p in polys)

    report = {}
    for target in targets:
        rasters, _ = svgraster.rasterize_elements(
            target["path"].read_text(), MASKS / target["name"] / f"s{config['scale']:g}",
            config["scale"])
        skeletons = [pipeline.thin(r.mask, config["thinning"]) for r in rasters]
        pixels = sum(s.size for s in skeletons)
        ref = [signature(tracers.st_c(s, csize=config["csize"])) for s in skeletons]
        for label, fn in (("st-py", tracers.st_py), ("st-js", tracers.st_js)):
            if label == "st-py" and pixels > py_pixel_budget:
                report.setdefault(label, {})[target["name"]] = None
                continue
            same = all(signature(fn(s, csize=config["csize"])) == r
                       for s, r in zip(skeletons, ref))
            report.setdefault(label, {})[target["name"]] = same
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

MATRICES = {
    "thinning": [{"thinning": v} for v in ("zhangsuen", "guohall")],
    "tracer": [{"tracer": v} for v in ("st-c", "st-js", "bespoke")],
    "caps": [{"cap_extend": v} for v in ("none", "round", "boundary")],
    "csize": [{"csize": v} for v in (5, 10, 20, 40)],
    "simplify": [{"simplify_px": v} for v in (0.0, 0.25, 0.5, 1.0)],
    "scale": [{"scale": v} for v in (2.0, 4.0, 8.0)],
}


def expand(matrix: list[str]) -> list[dict]:
    configs = [dict(DEFAULT_CONFIG)]
    for key in matrix:
        expanded = []
        for base in configs:
            for override in MATRICES[key]:
                merged = dict(base)
                merged.update(override)
                expanded.append(merged)
        configs = expanded
    return configs


def config_label(config: dict) -> str:
    diff = {k: v for k, v in config.items() if DEFAULT_CONFIG[k] != v}
    return ",".join(f"{k}={v}" for k, v in diff.items()) or "default"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets", nargs="*", default=None)
    parser.add_argument("--matrix", nargs="*", default=[], choices=list(MATRICES))
    parser.add_argument("--speed", action="store_true")
    parser.add_argument("--agreement", action="store_true")
    parser.add_argument("--save", action="store_true",
                        help="write graph JSON and promoted SVGs for the default config")
    parser.add_argument("--out", default=str(DEBUG / "metrics.json"))
    args = parser.parse_args()

    targets = resolve_targets(args.targets)
    configs = expand(args.matrix)

    runs = []
    for target in targets:
        for config in configs:
            t0 = time.perf_counter()
            result = run_one(target, config,
                             save_artifacts=args.save and config == DEFAULT_CONFIG)
            result["configLabel"] = config_label(config)
            result["wallClock_s"] = time.perf_counter() - t0
            runs.append(result)
            print(_row(result))

    payload = {
        "slug": "opencv-tracing",
        "defaultConfig": DEFAULT_CONFIG,
        "classifierRules": M.CLASSIFIER_RULES,
        "runs": runs,
    }
    if args.speed:
        payload["speed"] = speed_comparison(targets, DEFAULT_CONFIG["scale"])
    if args.agreement:
        payload["tracerAgreement"] = tracer_agreement(targets, DEFAULT_CONFIG)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(out.read_text()) if out.exists() and args.out.endswith(".json") \
        and out.stat().st_size else {}
    if existing.get("runs") and not args.targets and not args.matrix:
        pass
    out.write_text(json.dumps(payload, indent=1))
    print(f"\nwrote {out}")

    if args.speed:
        _print_speed(payload["speed"])


def _row(result: dict) -> str:
    rec = result.get("reconstruction", {})
    cen = result.get("centerline", {})
    cx = result["complexity"]
    tags = sum(v for k, v in result["tags"].items())
    return (f"{result['target']:<28} {result['configLabel']:<22} "
            f"IoU {rec.get('iou', float('nan')):.4f}  "
            f"sym% {rec.get('symDiffFraction', float('nan')) * 100:6.2f}  "
            f"bP95 {rec.get('boundaryP95', float('nan')):6.3f}  "
            f"cov {cen.get('gtCoverageFraction', float('nan')):.3f}  "
            f"E {cx['edgeCount']:4d} V {cx['vertexCount']:5d}  "
            f"tags {tags:3d}  {result['runtime']['extract_s']:.3f}s")


def _print_speed(speed: dict):
    print(f"\nSkeletonizer speed on {speed['maskMegapixels']:.1f} Mpx "
          f"across {speed['maskCount']} masks (best of {speed['repeats']}):")
    for label, entry in speed["skeletonizers"].items():
        print(f"  {label:<45} {entry['seconds']:7.3f}s  "
              f"{entry['megapixels_per_s']:8.2f} Mpx/s")
    print("Tracers:")
    for label, entry in speed["tracers"].items():
        if entry.get("seconds") is None:
            print(f"  {label:<45} {entry['note']}")
        else:
            print(f"  {label:<45} {entry['seconds']:7.3f}s  "
                  f"{entry['megapixels_per_s']:8.2f} Mpx/s")


if __name__ == "__main__":
    main()
