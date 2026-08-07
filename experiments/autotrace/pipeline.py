"""SVG -> resvg raster -> autotrace -centerline -> stroked SVG, with width recovery.

Granularity modes:
  raw      one full-colour antialiased raster of the whole drawing, traced in one
           shot.  This is the literal "one shell command" baseline the report
           asks us to keep honest, and reproduces the prior evaluation.
  color    one binary mask per distinct fill colour.
  element  one binary mask per filled element (the incumbent's `--mode elements`).

Only `color` and `element` get width recovery, because only they have a mask
whose distance transform means anything.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

import atrace
import width as W
from svgio import Document, Element, Renderer, SVG_NS

BBOX_PROBE_PX = 700  # coarse pass used only to find element bounds


@dataclass
class Config:
    mode: str = "element"
    scale: float = 4.0
    stat: str = "median"
    endpoint_trim: float = 0.0
    stroke_scale: float = 1.0
    # >0 forces ONE stroke width (user units) on every path, reproducing exactly
    # what the earlier evaluation swept.  0 == per-path width recovered from the
    # source distance transform.  This is the controlled A/B for the whole track.
    global_width: float = 0.0
    cap_extend: bool = False
    drop_outlines: bool = False
    min_length_px: float = 0.0
    outline_frac: float = 0.40
    params: atrace.TraceParams = field(default_factory=atrace.TraceParams)

    def tag(self):
        bits = [self.mode, f"s{self.scale:g}", self.stat, self.params.tag()]
        if self.endpoint_trim:
            bits.append(f"tr{self.endpoint_trim:g}")
        if self.stroke_scale != 1.0:
            bits.append(f"ss{self.stroke_scale:g}")
        if self.global_width:
            bits.append(f"gw{self.global_width:g}")
        if self.cap_extend:
            bits.append("cap")
        if self.drop_outlines:
            bits.append("noout")
        if self.min_length_px:
            bits.append(f"ml{self.min_length_px:g}")
        return "_".join(bits)


# ---- helpers ------------------------------------------------------------------


def _bbox_of(doc: Document, renderer: Renderer, els, pad_user: float):
    """Bounds of `els` in user space, found by a coarse render of the full canvas."""
    scale = BBOX_PROBE_PX / max(doc.vw, doc.vh)
    svg = doc.sub_svg(els, (doc.vx, doc.vy, doc.vw, doc.vh))
    mask, frame = renderer.mask(svg, (doc.vx, doc.vy, doc.vw, doc.vh), scale)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    x0 = doc.vx + xs.min() / frame.scale
    x1 = doc.vx + (xs.max() + 1) / frame.scale
    y0 = doc.vy + ys.min() / frame.scale
    y1 = doc.vy + (ys.max() + 1) / frame.scale
    p = pad_user + 2.0 / frame.scale
    return (x0 - p, y0 - p, (x1 - x0) + 2 * p, (y1 - y0) + 2 * p)


def _cap_extend(sp, mask, dist, r_px):
    """Push each free end out to the mask edge, then back one radius (§2.3).

    AutoTrace's centerline, like any medial axis, stops short of a round cap by
    about one radius; a round-capped re-stroke therefore falls short of the
    original tip.  Only applied to open subpaths.
    """
    if sp.is_closed() or r_px <= 0:
        return
    pts = sp.points()
    if len(pts) < 3:
        return
    h, w = mask.shape

    def march(anchor, direction):
        d = direction / (np.linalg.norm(direction) + 1e-12)
        t = 0.0
        last_inside = 0.0
        while t < 4 * r_px + 4:
            t += 0.5
            q = anchor + d * t
            xi, yi = int(q[0]), int(q[1])
            if xi < 0 or yi < 0 or xi >= w or yi >= h or not mask[yi, xi]:
                break
            last_inside = t
        reach = last_inside - r_px
        return anchor + d * reach if abs(reach) > 0.25 else None

    k = min(len(pts) - 1, max(2, int(r_px)))
    s_new = march(pts[0], pts[0] - pts[k])
    e_new = march(pts[-1], pts[-1] - pts[-1 - k])
    if s_new is not None:
        sp.start = (float(s_new[0]), float(s_new[1]))
    if e_new is not None and sp.segments:
        last = sp.segments[-1]
        p = (float(e_new[0]), float(e_new[1]))
        sp.segments[-1] = (last[0], *last[1:-1], p) if last[0] == "C" else ("L", p)


# ---- the run ------------------------------------------------------------------


def run(input_svg: Path, cfg: Config, scratch: Path, debug=None):
    doc = Document(input_svg)
    renderer = Renderer(scratch)
    t0 = time.perf_counter()
    result = {
        "input": str(input_svg),
        "config": {**{k: v for k, v in asdict(cfg).items() if k != "params"},
                   "params": asdict(cfg.params)},
        "viewBox": [doc.vx, doc.vy, doc.vw, doc.vh],
        "n_source_elements": len(doc.elements),
        "groups": [],
    }
    try:
        if cfg.mode == "raw":
            groups = [("all", doc.elements)]
        elif cfg.mode == "color":
            byc = {}
            for el in doc.elements:
                byc.setdefault(el.fill, []).append(el)
            groups = list(byc.items())
        elif cfg.mode == "element":
            groups = [(el.eid, [el]) for el in doc.elements]
        else:
            raise ValueError(cfg.mode)

        out_paths = []
        graph = {"nodes": [], "edges": []}
        tags = {}

        if cfg.mode == "raw":
            out_paths, ginfo = _run_raw(doc, renderer, cfg, scratch)
            result["groups"].append(ginfo)
        else:
            for gid, els in groups:
                ginfo, paths, gnodes, gedges, gtags = _run_group(
                    doc, renderer, cfg, scratch, gid, els, debug
                )
                result["groups"].append(ginfo)
                out_paths.extend(paths)
                graph["nodes"].extend(gnodes)
                graph["edges"].extend(gedges)
                for k, v in gtags.items():
                    tags[k] = tags.get(k, 0) + v
            result["failure_tags"] = tags
            result["graph"] = graph
    finally:
        renderer.close()

    result["runtime_s"] = time.perf_counter() - t0
    svg = _emit(doc, out_paths)
    result["n_output_paths"] = len(out_paths)
    return svg, result


def _run_raw(doc, renderer, cfg, scratch):
    """The zero-custom-code baseline: whole antialiased drawing, one trace."""
    box = (doc.vx, doc.vy, doc.vw, doc.vh)
    svg = doc.path.read_text()
    mask, frame = renderer.mask(svg, box, cfg.scale, threshold=1)
    # Feed autotrace the same full-colour PNG a user would: re-render on white.
    from PIL import Image

    w = int(round(doc.vw * cfg.scale))
    h = int(round(doc.vh * cfg.scale))
    import subprocess, json as _json

    raw = Path(scratch) / "raw_rgba.bin"
    p = subprocess.run(
        ["node", str(Path(__file__).resolve().parent / "render.mjs")],
        input=_json.dumps({"svg": svg, "width": w, "height": h, "out": str(raw)}) + "\n",
        capture_output=True, text=True,
    )
    res = _json.loads(p.stdout.strip().splitlines()[-1])
    buf = np.frombuffer(raw.read_bytes(), dtype=np.uint8).reshape(res["h"], res["w"], 4)
    rgb = buf[:, :, :3].astype(np.float32)
    a = buf[:, :, 3:4].astype(np.float32) / 255.0
    comp = (rgb * a + 255.0 * (1 - a)).astype(np.uint8)
    png = Path(scratch) / "raw.png"
    Image.fromarray(comp).save(png)
    import shutil as _sh

    out = Path(scratch) / "raw_trace.svg"
    t0 = time.perf_counter()
    pr = subprocess.run(
        [atrace.AUTOTRACE, *cfg.params.argv(), "-output-format", "svg",
         "-output-file", str(out), str(png)],
        capture_output=True, text=True, timeout=1800,
    )
    dt = time.perf_counter() - t0
    if pr.returncode != 0:
        raise RuntimeError(pr.stderr[:400])
    sps = atrace.parse_svg(out.read_text())
    frame = type(frame)(ox=doc.vx, oy=doc.vy, scale=res["w"] / doc.vw,
                        width=res["w"], height=res["h"])
    paths = []
    for sp in sps:
        d = sp.d(lambda p: (doc.vx + p[0] / frame.scale, doc.vy + p[1] / frame.scale))
        paths.append({"d": d, "stroke": sp.stroke, "width": 1.0 / frame.scale})
    return paths, {
        "id": "all", "mode": "raw", "n_subpaths": len(sps), "trace_s": dt,
        "distinct_colors": len({sp.stroke for sp in sps}),
    }


def _run_group(doc, renderer, cfg, scratch, gid, els, debug):
    box = _bbox_of(doc, renderer, els, pad_user=2.0)
    tags = {}
    if box is None:
        return ({"id": gid, "empty": True}, [], [], [], tags)
    svg = doc.sub_svg(els, box)
    mask, frame = renderer.mask(svg, box, cfg.scale)
    if not mask.any():
        return ({"id": gid, "empty": True}, [], [], [], tags)

    dist = W.edt(mask)
    sps, trace_s, _ = atrace.run(mask, Path(scratch) / "at", cfg.params, stem=gid)
    r_shape = W.measure(sps, mask, dist, cfg.stat, cfg.endpoint_trim, cfg.outline_frac)

    kept, dropped_short, n_outline = [], 0, 0
    for sp in sps:
        if sp.outline_like:
            n_outline += 1
            if cfg.drop_outlines:
                continue
        if cfg.min_length_px and sp.stats.get("length_px", 0) < cfg.min_length_px * cfg.scale:
            dropped_short += 1
            continue
        kept.append(sp)

    if cfg.cap_extend:
        for sp in kept:
            _cap_extend(sp, mask, dist, sp.stats.get("radius_px", 0.0))
        W.measure(kept, mask, dist, cfg.stat, cfg.endpoint_trim, cfg.outline_frac)

    fill = els[0].fill if len(els) == 1 else els[0].fill
    paths, nodes, edges = [], [], []
    for i, sp in enumerate(kept):
        r_user = frame.len_px_to_user(sp.stats.get("radius_px", 0.0))
        sw = (cfg.global_width if cfg.global_width
              else max(0.15, 2.0 * r_user * cfg.stroke_scale))
        d = sp.d(lambda p: (box[0] + p[0] / frame.scale, box[1] + p[1] / frame.scale))
        paths.append({
            "d": d, "stroke": fill, "width": sw,
            "closed": sp.is_closed(), "outline_like": sp.outline_like,
        })
        # ---- common graph model (Common Setup §13) ----
        pts_u = frame.px_to_user(sp.points())
        eid = f"{gid}/{i}"
        n0, n1 = f"{eid}:a", f"{eid}:b"
        nodes.append({"id": n0, "x": round(float(pts_u[0][0]), 4),
                      "y": round(float(pts_u[0][1]), 4), "radius": round(r_user, 4)})
        nodes.append({"id": n1, "x": round(float(pts_u[-1][0]), 4),
                      "y": round(float(pts_u[-1][1]), 4), "radius": round(r_user, 4)})
        seglen = float(np.hypot(*np.diff(pts_u, axis=0).T).sum()) if len(pts_u) > 1 else 0.0
        edges.append({
            "id": eid, "from": n0, "to": n1,
            "geometry": [[round(float(x), 3), round(float(y), 3)] for x, y in pts_u],
            "length": round(seglen, 4),
            "medianRadius": round(frame.len_px_to_user(sp.stats.get("radius_median_px", 0.0)), 4),
            "radiusProfile": [round(frame.len_px_to_user(v), 4)
                              for v in W.per_vertex_profile(dist, sp)],
            "sourceElementId": gid,
            "closed": sp.is_closed(),
            "outlineLike": sp.outline_like,
        })

    if n_outline:
        tags["mixed outline/centerline"] = n_outline
    if dropped_short:
        tags["outline noise branch"] = dropped_short
    # A mask thinner than ~1.5px at this scale cannot be traced reliably.
    if r_shape < 1.5:
        tags["raster quantization"] = 1
    if not kept:
        tags["missing narrow segment"] = 1

    radii = [sp.stats.get("radius_px", 0.0) for sp in kept]
    ginfo = {
        "id": gid, "n_elements": len(els), "fill": fill,
        "mask_px": int(mask.sum()), "mask_shape": list(mask.shape),
        "shape_radius_px": round(r_shape, 3),
        "n_subpaths": len(sps), "n_kept": len(kept),
        "n_outline_like": n_outline, "n_closed": sum(1 for s in kept if s.is_closed()),
        "trace_s": round(trace_s, 4),
        "radius_px": {
            "min": round(min(radii), 3) if radii else 0,
            "median": round(float(np.median(radii)), 3) if radii else 0,
            "max": round(max(radii), 3) if radii else 0,
        },
        "width_user": [round(frame.len_px_to_user(2 * r), 3) for r in radii],
    }
    return ginfo, paths, nodes, edges, tags


def _emit(doc, paths):
    out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        f'<svg xmlns="{SVG_NS}" version="1.1" '
        f'viewBox="{doc.vx:g} {doc.vy:g} {doc.vw:g} {doc.vh:g}">',
    ]
    for p in paths:
        out.append(
            f'<path d="{p["d"]}" fill="none" stroke="{p["stroke"]}" '
            f'stroke-width="{p["width"]:.3f}" stroke-linecap="round" '
            f'stroke-linejoin="round"/>'
        )
    for raw in doc.passthrough:
        out.append(raw)
    out.append("</svg>")
    return "\n".join(out)
