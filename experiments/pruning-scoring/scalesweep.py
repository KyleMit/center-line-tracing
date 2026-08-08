#!/usr/bin/env python3
"""Does skimage-skan's raster scale matter once Track 8's pruning cleans up after it?

    python3 experiments/pruning-scoring/scalesweep.py --jobs 3
    python3 experiments/pruning-scoring/scalesweep.py --images house-wide --scales 4,8
    python3 experiments/pruning-scoring/scalesweep.py --report        # re-print, no work

skimage-skan is the leading backend on the cross-backend leaderboard but it only
ever published raster scale 4. Its own notes measure the tension directly: raising
the scale improves geometry (case 03 centerline median 0.197 -> 0.053 from scale 1
to 8) while spurious branch count grows roughly linearly with resolution (case 20:
22 branches at scale 1, 289 at scale 16 on a shape whose true answer is one line).
That track concluded "scale 4 is the default here; scale 8 is the right choice if a
pruning stage will clean up after it".

This layer *is* that pruning stage, so the conditional is now testable. Every cell
re-extracts at its own scale, then runs the same automatic width-aware selection
the leaderboard uses, and is scored on both axes that matter: reconstruction error
AND the product goal (wobble, control points per stroke width). Judging a raster
scale on error alone would be the exact mistake NOTES' addendum warns about — a
denser raster can buy error by wiggling along the outline.

Writes debug/pruning-scoring/scalesweep.json (data), scalesweep.md (report), and
scalesweep/graphs/<image>__s<scale>.json (the extracted graphs).

The graphs deliberately land under debug/pruning-scoring/ rather than in
debug/skimage-skan/graphs/, because bench.py's leaderboard picks each track's
*rawest* published variant as the pruning input; dropping scale-16 graphs into that
track's directory would silently re-point the leaderboard at a config that track
never published.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "experiments" / "skimage-skan"))

from clg import CenterlineGraph, metrics, select, smoothness, svgio  # noqa: E402

DEBUG = REPO / "debug" / "pruning-scoring"
OUT_JSON = DEBUG / "scalesweep.json"
OUT_MD = DEBUG / "scalesweep.md"
GRAPHS = DEBUG / "scalesweep" / "graphs"

# The synthetic corpus is skimage-skan's, and it carries truth centerlines. It is
# the only place a scale can be judged on where the line actually IS rather than
# on how well the drawing rebuilds from it.
CORPUS = REPO / "debug" / "skimage-skan" / "corpus" / "corpus.json"
CORPUS_JSON = DEBUG / "scalesweep-corpus.json"
CORPUS_MD = DEBUG / "scalesweep-corpus.md"

IMAGES = [
    "house-wide", "butterfly-wide", "boat-tall", "island-tall", "balloon-tall",
    "home-wide", "house-tall", "dinosaur-wide", "landscape-square", "sun-square",
]
SCALES = [1.0, 2.0, 4.0, 8.0, 16.0]

# The same shortened sweep the leaderboard uses, so the auto-selected numbers here
# are directly comparable with the ones in leaderboard.md.
LAMBDAS = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0)

# The published skimage-skan config, held fixed so `scale` is the only variable.
# +pw (per-vertex width) because NOTES §6 measured the radius profile as worth a
# 37% error reduction, and it is what that track promotes.
WIDTH_MODE = "piecewise"
METHOD = "medial-axis"
SIMPLIFY_EPS = 0.15


def extract_graph(image: str, scale: float, svg_path: Path | None = None,
                  ) -> tuple[Path, float, int]:
    """Re-extract one drawing at one raster scale. Returns (path, seconds, elements)."""
    import emit  # noqa: PLC0415  — skimage-skan's modules, imported in the worker
    import extract  # noqa: PLC0415
    import svgio as skan_svgio  # noqa: PLC0415

    doc = skan_svgio.load(svg_path or REPO / "inputs" / f"{image}.svg")
    cfg = extract.ExtractConfig(scale=scale, method=METHOD, simplify_eps=SIMPLIFY_EPS)
    t0 = time.time()
    graph, _results = extract.extract_document(doc, cfg)
    emit.fit_beziers(graph, width_mode=WIDTH_MODE)
    seconds = time.time() - t0

    src_rel = (svg_path or REPO / "inputs" / f"{image}.svg").relative_to(REPO)
    path = GRAPHS / f"{image}__s{scale:g}.json"
    graph.save(path)
    # `source` is not part of the schema's required set, but writing it lets
    # clg.resolve find the drawing for these files without filename guessing.
    doc_json = json.loads(path.read_text())
    doc_json["source"] = str(src_rel)
    path.write_text(json.dumps(doc_json, separators=(",", ":")))
    return path, seconds, len(doc.elements)


def _cell(args: tuple[str, float]) -> dict:
    image, scale = args
    t0 = time.time()
    try:
        path, extract_seconds, elements = extract_graph(image, scale)
    except Exception as exc:  # noqa: BLE001
        return {"image": image, "scale": scale, "status": "extract-failed",
                "error": f"{type(exc).__name__}: {exc}"[:300]}

    src = svgio.load_source(REPO / "inputs" / f"{image}.svg")
    g = CenterlineGraph.load(path)
    try:
        chosen, cands = select.select(g, src, lambdas=LAMBDAS)
    except Exception as exc:  # noqa: BLE001
        return {"image": image, "scale": scale, "status": "select-failed",
                "error": f"{type(exc).__name__}: {exc}"[:300]}
    if chosen is None:
        return {"image": image, "scale": scale, "status": "no-candidate"}

    raw = next((c for c in cands if c.lam == 0.0), None)
    s_auto = smoothness.graph_smoothness(chosen.graph)
    grade, _ = smoothness.naturalness_grade(s_auto)

    return {
        "image": image,
        "scale": scale,
        "status": "ok",
        "graph": str(path.relative_to(REPO)),
        "elements": elements,
        "extractSeconds": round(extract_seconds, 2),
        "seconds": round(time.time() - t0, 2),
        "raw": raw.to_dict() if raw else None,
        "auto": chosen.to_dict(),
        "smoothness": s_auto.to_dict(),
        "grade": grade,
        "sweep": [c.to_dict() for c in cands],
    }


def _corpus_cell(args: tuple[dict, float]) -> dict:
    """Same sweep, but on shapes whose true centerline is known."""
    case, scale = args
    t0 = time.time()
    svg = REPO / case["svg"]
    try:
        path, extract_seconds, _ = extract_graph(case["id"], scale, svg_path=svg)
        src = svgio.load_source(svg)
        g = CenterlineGraph.load(path)
        chosen, cands = select.select(g, src, lambdas=LAMBDAS)
    except Exception as exc:  # noqa: BLE001
        return {"case": case["id"], "num": case["num"], "scale": scale,
                "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]}
    if chosen is None:
        return {"case": case["id"], "num": case["num"], "scale": scale,
                "status": "no-candidate"}

    raw = next((c for c in cands if c.lam == 0.0), None)
    return {
        "case": case["id"],
        "num": case["num"],
        "notes": case["notes"],
        "radius": case.get("radius"),
        "scale": scale,
        "status": "ok",
        "graph": str(path.relative_to(REPO)),
        "extractSeconds": round(extract_seconds, 2),
        "seconds": round(time.time() - t0, 2),
        "rawEdges": raw.metrics.edges if raw else None,
        "autoEdges": chosen.metrics.edges,
        "lam": chosen.lam,
        "rawTruth": metrics.centerline_error(raw.graph, case["truth"]) if raw else None,
        "autoTruth": metrics.centerline_error(chosen.graph, case["truth"]),
        "autoRecon": chosen.to_dict(),
        "smoothness": smoothness.graph_smoothness(chosen.graph).to_dict(),
    }


def run_corpus(cases: list[dict], scales: list[float], jobs: int) -> dict:
    work = [(c, s) for c in cases for s in scales]
    prior = {}
    if CORPUS_JSON.exists():
        old = json.loads(CORPUS_JSON.read_text())
        prior = {(r["case"], r["scale"]): r for r in old.get("results", [])}
    results: list[dict] = []
    t0 = time.time()

    def flush() -> None:
        merged = dict(prior)
        for r in results:
            merged[(r["case"], r["scale"])] = r
        DEBUG.mkdir(parents=True, exist_ok=True)
        CORPUS_JSON.write_text(json.dumps({
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seconds": round(time.time() - t0, 1),
            "scales": sorted({k[1] for k in merged}),
            "lambdas": list(LAMBDAS),
            "results": sorted(merged.values(), key=lambda r: (r["num"], r["scale"])),
        }, indent=1))

    def consume(runner) -> None:
        for i, rec in enumerate(runner, 1):
            results.append(rec)
            flush()
            med = (rec.get("autoTruth") or {}).get("centerlineMedian")
            print(f"  [{i}/{len(work)}] {rec['case']}@{rec['scale']:g}: {rec['status']} "
                  f"truth-med {med if med is None else format(med, '.4f')} "
                  f"({rec.get('seconds', 0)}s)", flush=True)

    if jobs > 1:
        with Pool(jobs) as pool:
            consume(pool.imap_unordered(_corpus_cell, work))
    else:
        consume(map(_corpus_cell, work))
    return json.loads(CORPUS_JSON.read_text())


def corpus_report(data: dict) -> str:
    ok = [r for r in data["results"] if r.get("status") == "ok"]
    by = {(r["case"], r["scale"]): r for r in ok}
    scales = sorted({k[1] for k in by})
    cases = sorted({r["case"] for r in ok}, key=lambda c: next(
        r["num"] for r in ok if r["case"] == c))

    lines = ["# Raster scale against GROUND-TRUTH centerlines\n"]
    lines.append(f"Generated {data['generated']} · {data['seconds']}s · "
                 "skimage-skan on its own 20-case synthetic corpus, auto-pruned "
                 "by this layer at each scale.\n")
    lines.append("Every other table in this directory measures *reconstruction* "
                 "error, which cannot distinguish a smooth path in the wrong place "
                 "from a smooth path in the right one. These shapes were generated "
                 "from known centerlines, so this one can. Distances are SVG user "
                 "units against a stroke radius of 10 (case 19 tapers 6 -> 16).\n")

    def med(vals):
        v = sorted(x for x in vals if x is not None)
        return v[len(v) // 2] if v else None

    lines.append("\nBoth `01-horizontal-line` and `17-near-parallel` report the same "
                 "numbers at every scale, which looks like a bug and is not: case 17 "
                 "is two translated copies of case 01's capsule, so the two "
                 "point-distance sets are identical.\n")
    lines.append("\n## Medians over the 20 cases\n")
    lines.append("`branches before` is counted after canonicalization but before "
                 "pruning (the λ=0 candidate), because that is the input pruning "
                 "actually sees — the published raw counts are higher.\n")
    lines.append("| scale | cases | truth median | truth P95 | invented geometry "
                 "(recovered->truth P95) | missed geometry (truth->recovered P95) "
                 "| branches before | branches after pruning |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for s in scales:
        rows = [by[(c, s)] for c in cases if (c, s) in by]
        if not rows:
            continue
        lines.append(
            f"| {s:g} | {len(rows)} "
            f"| {_f(med([r['autoTruth']['centerlineMedian'] for r in rows]))} "
            f"| {_f(med([r['autoTruth']['centerlineP95'] for r in rows]))} "
            f"| {_f(med([r['autoTruth']['recoveredToTruthP95'] for r in rows]))} "
            f"| {_f(med([r['autoTruth']['truthToRecoveredP95'] for r in rows]))} "
            f"| {_f(med([r['rawEdges'] for r in rows]), '5.0f')} "
            f"| {_f(med([r['autoEdges'] for r in rows]), '5.0f')} |")

    lines.append("\n## Truth-centerline median error, per case\n")
    lines.append("| case | " + " | ".join(f"scale {s:g}" for s in scales) + " |")
    lines.append("|---" * (len(scales) + 1) + "|")
    for c in cases:
        vals = [by[(c, s)]["autoTruth"]["centerlineMedian"] if (c, s) in by else None
                for s in scales]
        good = [v for v in vals if v is not None]
        pick = min(good) if good else None
        cells = [(f"**{_f(v)}**" if v is not None and v == pick else _f(v)) for v in vals]
        lines.append(f"| {c} | " + " | ".join(cells) + " |")

    lines.append("\n## Does pruning keep up with the extra resolution?\n")
    lines.append("Branch count before → after automatic pruning. Case 20 is the "
                 "stress test and the one that answers the question: a single "
                 "straight capsule under boundary jitter, whose true answer is one "
                 "branch at every scale.\n")
    lines.append("| case | " + " | ".join(f"scale {s:g}" for s in scales) + " |")
    lines.append("|---" * (len(scales) + 1) + "|")
    for c in cases:
        cells = []
        for s in scales:
            r = by.get((c, s))
            cells.append("  --  " if not r else f"{r['rawEdges']} → {r['autoEdges']}")
        lines.append(f"| {c} | " + " | ".join(cells) + " |")

    failed = [r for r in data["results"] if r.get("status") != "ok"]
    if failed:
        lines.append("\n## Cells that did not produce a result\n")
        for r in failed:
            lines.append(f"- `{r['case']}@{r['scale']:g}` — {r['status']}: "
                         f"{r.get('error', '')}")
    return "\n".join(lines) + "\n"


def run(images: list[str], scales: list[float], jobs: int) -> dict:
    work = [(i, s) for i in images for s in scales]
    prior = {}
    if OUT_JSON.exists():
        old = json.loads(OUT_JSON.read_text())
        prior = {(r["image"], r["scale"]): r for r in old.get("results", [])}

    results: list[dict] = []
    t0 = time.time()

    def flush() -> None:
        merged = dict(prior)
        for r in results:
            merged[(r["image"], r["scale"])] = r
        # Axes come from everything stored, not from this invocation: the sweep is
        # run one scale at a time (a scale-16 pass is ~20x a scale-1 pass), and
        # recording only the current run's axes silently drops every earlier
        # column from the report.
        DEBUG.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps({
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seconds": round(time.time() - t0, 1),
            "images": [i for i in IMAGES if any(k[0] == i for k in merged)],
            "scales": sorted({k[1] for k in merged}),
            "lambdas": list(LAMBDAS),
            "widthMode": WIDTH_MODE,
            "method": METHOD,
            "results": sorted(merged.values(),
                              key=lambda r: (IMAGES.index(r["image"])
                                             if r["image"] in IMAGES else 99, r["scale"])),
        }, indent=1))

    def consume(runner) -> None:
        for i, rec in enumerate(runner, 1):
            results.append(rec)
            flush()   # every cell: a scale-16 run is slow enough that losing it hurts
            err = rec["auto"]["error"] if rec.get("auto") else None
            print(f"  [{i}/{len(work)}] {rec['image']}@{rec['scale']:g}: {rec['status']} "
                  f"err {err if err is None else format(err, '.4f')} "
                  f"({rec.get('seconds', 0)}s)", flush=True)

    if jobs > 1:
        with Pool(jobs) as pool:
            consume(pool.imap_unordered(_cell, work))
    else:
        consume(map(_cell, work))
    return json.loads(OUT_JSON.read_text())


# ------------------------------------------------------------------- reporting


def _f(v, spec="6.4f"):
    if v is None:
        return "  --  "
    try:
        return format(float(v), spec)
    except (TypeError, ValueError):
        return str(v)


def report(data: dict) -> str:
    by = {(r["image"], r["scale"]): r for r in data["results"] if r.get("status") == "ok"}
    # Axes from the results, never from the stored header: the sweep is run one
    # scale at a time and a run only knows about its own scales.
    images = [i for i in IMAGES if any(k[0] == i for k in by)]
    scales = sorted({k[1] for k in by})

    lines = ["# skimage-skan raster scale, swept and auto-pruned\n"]
    lines.append(f"Generated {data['generated']} · {data['seconds']}s · "
                 f"`{data['method']}` + {data['widthMode']} width · "
                 f"pruning λ {min(data['lambdas'])}..{max(data['lambdas'])}, "
                 "selected automatically per cell.\n")
    lines.append("Error is symmetric difference as a fraction of source ink, measured "
                 "*after* automatic width-aware pruning — so a scale is judged on what "
                 "survives cleanup, not on its raw skeleton. Lower is better.\n")

    def table(title: str, cell, spec="6.4f", best="min") -> None:
        lines.append(f"\n## {title}\n")
        lines.append("| image | " + " | ".join(f"scale {s:g}" for s in scales) + " |")
        lines.append("|---" * (len(scales) + 1) + "|")
        for img in images:
            vals = [cell(by[(img, s)]) if (img, s) in by else None for s in scales]
            good = [v for v in vals if v is not None]
            pick = (min if best == "min" else max)(good) if good else None
            cells = []
            for v in vals:
                txt = _f(v, spec)
                cells.append(f"**{txt}**" if pick is not None and v == pick else txt)
            lines.append(f"| {img} | " + " | ".join(cells) + " |")

    table("Reconstruction error after auto-pruning",
          lambda r: r["auto"]["error"])
    table("Wobble after auto-pruning (product goal: lower is smoother)",
          lambda r: r["smoothness"]["wiggle"])
    table("Control points per stroke width (editability; lower is leaner)",
          lambda r: r["smoothness"]["verts_per_width"], spec="6.2f")
    table("Branches kept after auto-pruning",
          lambda r: r["auto"]["edges"], spec="6.0f")
    table("Selected pruning strength λ",
          lambda r: r["auto"]["lam"], spec="5.2f", best="max")
    table("Extraction seconds",
          lambda r: r["extractSeconds"], spec="7.1f")

    # medians across the drawings, which is how the leaderboard ranks backends
    lines.append("\n## Medians across all drawings\n")
    lines.append("| scale | images | median err | median raw err (unpruned) | "
                 "median wobble | median pts/width | median branches | median extract s |")
    lines.append("|---|---|---|---|---|---|---|---|")

    def med(vals):
        v = sorted(x for x in vals if x is not None)
        return v[len(v) // 2] if v else None

    for s in scales:
        rows = [by[(i, s)] for i in images if (i, s) in by]
        if not rows:
            continue
        lines.append(
            f"| {s:g} | {len(rows)} | {_f(med([r['auto']['error'] for r in rows]))} "
            f"| {_f(med([(r['raw'] or {}).get('error') for r in rows]))} "
            f"| {_f(med([r['smoothness']['wiggle'] for r in rows]))} "
            f"| {_f(med([r['smoothness']['verts_per_width'] for r in rows]), '6.2f')} "
            f"| {_f(med([r['auto']['edges'] for r in rows]), '6.0f')} "
            f"| {_f(med([r['extractSeconds'] for r in rows]), '6.1f')} |")

    # Absent cells and failed cells are different things and both need saying, or a
    # `--` in the table reads as "not interesting" rather than "not measured".
    absent = [(i, s) for i in images for s in scales if (i, s) not in by
              and not any(r["image"] == i and r["scale"] == s for r in data["results"])]
    failed = [r for r in data["results"] if r.get("status") != "ok"]
    if absent or failed:
        lines.append("\n## Cells with no result\n")
        for i, s in absent:
            lines.append(f"- `{i}@{s:g}` — never completed; see NOTES Addendum 2 §8 "
                         "on scale-16 extraction cost.")
        for r in failed:
            lines.append(f"- `{r['image']}@{r['scale']:g}` — {r['status']}: "
                         f"{r.get('error', '')}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", default=",".join(IMAGES))
    ap.add_argument("--scales", default=",".join(f"{s:g}" for s in SCALES))
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--corpus", action="store_true",
                    help="sweep the synthetic corpus against its truth centerlines")
    ap.add_argument("--cases", default="", help="corpus: restrict to these case ids")
    ap.add_argument("--report", action="store_true", help="re-print stored results only")
    args = ap.parse_args()
    scales = [float(s) for s in args.scales.split(",") if s]

    if args.corpus:
        if args.report:
            data = json.loads(CORPUS_JSON.read_text())
        else:
            cases = json.loads(CORPUS.read_text())["cases"]
            want = [c for c in args.cases.split(",") if c]
            if want:
                cases = [c for c in cases if c["id"] in want or str(c["num"]) in want]
            data = run_corpus(cases, scales, args.jobs)
        md = corpus_report(data)
        CORPUS_MD.write_text(md)
        print(md)
        print(f"wrote {CORPUS_JSON.relative_to(REPO)} and {CORPUS_MD.relative_to(REPO)}")
        return 0

    if args.report:
        data = json.loads(OUT_JSON.read_text())
    else:
        data = run([i for i in args.images.split(",") if i], scales, args.jobs)
    md = report(data)
    OUT_MD.write_text(md)
    print(md)
    print(f"wrote {OUT_JSON.relative_to(REPO)} and {OUT_MD.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
