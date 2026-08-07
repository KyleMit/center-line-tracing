#!/usr/bin/env python3
"""Render the accumulated metrics/sweeps into the markdown tables used by NOTES.md."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DEBUG = REPO / "debug" / "autotrace"

IMGS = ["house-wide", "butterfly-wide", "boat-tall", "island-tall", "balloon-tall",
        "home-wide", "house-tall", "dinosaur-wide", "landscape-square", "sun-square"]


def load(p):
    return json.loads(Path(p).read_text()) if Path(p).exists() else {}


def sweep_table(labels=None, images=("house-wide", "dinosaur-wide", "landscape-square")):
    m = load(DEBUG / "metrics.json")
    labels = labels or sorted(m)
    head = "| run | config | " + " | ".join(images) + " |"
    sep = "|---|---|" + "---|" * len(images)
    lines = [head, sep]
    for lab in labels:
        if lab not in m:
            continue
        row = [lab, f"`{m[lab]['config']}`"]
        for im in images:
            e = m[lab]["images"].get(im, {})
            row.append(f"{e['compare_js_pct']:.2f}%" if "compare_js_pct" in e else "–")
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def ladder_table(label):
    m = load(DEBUG / "metrics.json")[label]["images"]
    lines = ["| image | diff % | IoU | boundary P95 (user) | strokes | src elems | runtime | tags |",
             "|---|---|---|---|---|---|---|---|"]
    for im in IMGS:
        e = m.get(im)
        if not e:
            continue
        if "error" in e:
            lines.append(f"| `{im}` | ERROR | | | | | | {e['error']} |")
            continue
        tags = ", ".join(f"{k}×{v}" for k, v in (e.get("failure_tags") or {}).items()) or "–"
        lines.append(
            f"| `{im}` | **{e['compare_js_pct']:.2f}%** | {e['iou']:.4f} | "
            f"{e['boundary_p95_user']:.2f} | {e['n_strokes']} | {e['n_source_elements']} | "
            f"{e['runtime_s']:.0f}s | {tags} |")
    return "\n".join(lines)


def synth_table(label="s4-cap"):
    s = load(DEBUG / "synthetic.json")
    if label not in s:
        return "_(not run)_"
    lines = ["| case | traced subpaths | centerline med (u) | centerline P95 (u) | "
             "endpoint med (u) | true r | recovered r | radius err |",
             "|---|---|---|---|---|---|---|---|"]
    for r in s[label]["rows"]:
        lines.append(
            f"| `{r['case']}` | {r['n_traced_subpaths']} | {r['centerline_median_user']:.2f} | "
            f"{r['centerline_p95_user']:.2f} | {r.get('endpoint_median_user', float('nan')):.2f} | "
            f"{r['true_radius_user']:.2f} | {r['recovered_radius_user']:.2f} | "
            f"{r['radius_err_pct']:+.1f}% |")
    return "\n".join(lines)


def synth_resolution_table():
    s = load(DEBUG / "synthetic.json")
    labels = [k for k in ("s1-cap", "s2-cap", "s3-cap", "s4-cap", "s6-cap", "s8-cap") if k in s]
    if not labels:
        return "_(not run)_"
    import statistics as st
    lines = ["| raster scale (px per user unit) | median centerline err (u) | "
             "median \\|radius err\\| | cases with extra subpaths |",
             "|---|---|---|---|"]
    for lab in labels:
        rows = s[lab]["rows"]
        ce = st.median(r["centerline_median_user"] for r in rows)
        re_ = st.median(abs(r["radius_err_pct"] or 0) for r in rows)
        extra = sum(1 for r in rows if r["n_traced_subpaths"] > r["n_expected_strokes"])
        lines.append(f"| {s[lab]['scale']:g} | {ce:.3f} | {re_:.1f}% | {extra}/{len(rows)} |")
    return "\n".join(lines)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "sweep"
    if what == "sweep":
        print(sweep_table(sys.argv[2:] or None))
    elif what == "ladder":
        print(ladder_table(sys.argv[2]))
    elif what == "synth":
        print(synth_table(sys.argv[2] if len(sys.argv) > 2 else "s4-cap"))
    elif what == "synthres":
        print(synth_resolution_table())
