#!/usr/bin/env python3
"""
Convert a filled-shape SVG line drawing into a stroked-line SVG.

This is designed for SVGs like AI-generated coloring/line drawings where each
visible “line” is actually a filled ribbon shape. The script rasterizes the SVG,
segments colored pixels by fill color, skeletonizes each colored region to a
1-pixel centerline, traces those centerlines into SVG paths, and writes a new
SVG whose paths use stroke/stroke-width with fill="none".

Example:
    python convert_filled_svg_to_stroked_lines.py large-image-drawing.svg \
        --output large-image-drawing-lines.svg

Install dependencies:
    pip install cairosvg pillow numpy scikit-image opencv-python
"""

from __future__ import annotations

import argparse
import math
import re
import tempfile
import warnings
from pathlib import Path

import cairosvg
import cv2
import numpy as np
from PIL import Image
from skimage.morphology import closing, disk, medial_axis, remove_small_objects, skeletonize

SVG_NS = "http://www.w3.org/2000/svg"
NEIGHBORS_8 = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]


def read_viewbox(svg_text: str) -> tuple[int, int, int, int]:
    match = re.search(r'viewBox="([^"]+)"', svg_text)
    if not match:
        raise ValueError("Input SVG must have a viewBox.")
    values = [float(v) for v in re.split(r"[\s,]+", match.group(1).strip())]
    if len(values) != 4:
        raise ValueError(f"Expected four viewBox values, got: {match.group(1)!r}")
    x, y, width, height = values
    return int(round(x)), int(round(y)), int(round(width)), int(round(height))


def extract_fill_colors(svg_text: str) -> list[str]:
    """Return explicit hex fill colors used by filled paths/shapes."""
    colors = sorted(set(re.findall(r'fill="(#[0-9a-fA-F]{6})"', svg_text)))
    if not colors:
        raise ValueError("No explicit hex fill colors found. This script expects filled line-shape SVGs.")
    return colors


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def render_svg_to_rgba(svg_path: Path, width: int, height: int) -> np.ndarray:
    """Rasterize at native viewBox size so pixel coordinates match SVG coordinates."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        cairosvg.svg2png(
            url=str(svg_path),
            write_to=str(tmp_path),
            output_width=width,
            output_height=height,
            background_color=None,
        )
        return np.array(Image.open(tmp_path).convert("RGBA"))
    finally:
        tmp_path.unlink(missing_ok=True)


def render_svg_text_to_rgba(svg_text: str, width: int, height: int) -> np.ndarray:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        cairosvg.svg2png(
            bytestring=svg_text.encode("utf-8"),
            write_to=str(tmp_path),
            output_width=width,
            output_height=height,
            background_color=None,
        )
        return np.array(Image.open(tmp_path).convert("RGBA"))
    finally:
        tmp_path.unlink(missing_ok=True)


def attr_value(attrs: str, name: str) -> str | None:
    match = re.search(rf'\b{name}\s*=\s*["\']([^"\']+)["\']', attrs, flags=re.I)
    return match.group(1) if match else None


def explicit_fill(attrs: str) -> str | None:
    direct = attr_value(attrs, "fill")
    if direct and re.match(r"^#[0-9a-fA-F]{6}$", direct):
        return direct.upper()

    style = attr_value(attrs, "style")
    if style:
        match = re.search(r"(?:^|;)\s*fill\s*:\s*(#[0-9a-fA-F]{6})", style, flags=re.I)
        if match:
            return match.group(1).upper()

    return None


def sanitize_shape_attrs(attrs: str) -> str:
    attrs = re.sub(
        r'\s(?:fill|stroke|stroke-width|stroke-linecap|stroke-linejoin|vector-effect)\s*=\s*["\'][^"\']*["\']',
        "",
        attrs,
        flags=re.I,
    )
    attrs = re.sub(r'\sstyle\s*=\s*["\'][^"\']*["\']', "", attrs, flags=re.I)
    attrs = re.sub(r"/\s*$", "", attrs)
    return attrs.strip()


def parse_filled_elements(svg_text: str) -> list[dict[str, str]]:
    elements: list[dict[str, str]] = []
    fill_stack: list[str | None] = [None]
    token_re = re.compile(r"<g\b([^>]*)>|</g>|<(path|rect|circle|ellipse)\b([^>]*)/?>", flags=re.I)

    for match in token_re.finditer(svg_text):
        token = match.group(0)
        if token.lower().startswith("</g"):
            if len(fill_stack) > 1:
                fill_stack.pop()
            continue

        if token.lower().startswith("<g"):
            attrs = match.group(1) or ""
            fill_attr = attr_value(attrs, "fill")
            fill = None if fill_attr and fill_attr.lower() == "none" else explicit_fill(attrs) or fill_stack[-1]
            fill_stack.append(fill)
            continue

        tag = (match.group(2) or "").lower()
        attrs = match.group(3) or ""
        fill_attr = attr_value(attrs, "fill")
        fill = None if fill_attr and fill_attr.lower() == "none" else explicit_fill(attrs) or fill_stack[-1]
        if not fill:
            continue

        clean_attrs = sanitize_shape_attrs(attrs)
        elements.append({
            "tag": tag,
            "fill": fill,
            "markup": f'<{tag} {clean_attrs} fill="#fff"/>',
            "attrs": attrs,
        })

    return elements


def render_element_mask(element: dict[str, str], viewbox: tuple[int, int, int, int], scale: float) -> np.ndarray:
    x, y, width, height = viewbox
    out_width = int(round(width * scale))
    out_height = int(round(height * scale))
    svg_text = "\n".join([
        f'<svg xmlns="{SVG_NS}" version="1.1" viewBox="{x} {y} {width} {height}">',
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="#000"/>',
        element["markup"],
        "</svg>",
    ])
    rgba = render_svg_text_to_rgba(svg_text, out_width, out_height)
    return rgba[..., 0] > 128


def degree(skeleton: np.ndarray, y: int, x: int) -> int:
    h, w = skeleton.shape
    count = 0
    for dy, dx in NEIGHBORS_8:
        yy, xx = y + dy, x + dx
        if 0 <= yy < h and 0 <= xx < w and skeleton[yy, xx]:
            count += 1
    return count


def trace_skeleton_paths(skeleton: np.ndarray) -> list[list[tuple[int, int]]]:
    """
    Convert a 1-pixel skeleton image into ordered pixel chains.

    Coordinates are stored internally as (y, x). They are converted to SVG
    (x, y) when the path data is emitted.
    """
    h, w = skeleton.shape
    skeleton_points = np.argwhere(skeleton)
    if len(skeleton_points) == 0:
        return []

    deg = np.zeros(skeleton.shape, dtype=np.uint8)
    for y, x in skeleton_points:
        deg[y, x] = degree(skeleton, int(y), int(x))

    nodes = set(map(tuple, np.argwhere(skeleton & (deg != 2))))
    visited_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    paths: list[list[tuple[int, int]]] = []

    def edge_key(a: tuple[int, int], b: tuple[int, int]):
        return tuple(sorted((a, b)))

    def skel_neighbors(p: tuple[int, int]) -> list[tuple[int, int]]:
        y, x = p
        output = []
        for dy, dx in NEIGHBORS_8:
            q = (y + dy, x + dx)
            if 0 <= q[0] < h and 0 <= q[1] < w and skeleton[q]:
                output.append(q)
        return output

    # Open chains and chains between branch points.
    for node in list(nodes):
        for neighbor in skel_neighbors(node):
            key = edge_key(node, neighbor)
            if key in visited_edges:
                continue
            path = [node, neighbor]
            visited_edges.add(key)
            previous, current = node, neighbor
            while current not in nodes:
                next_pixels = [q for q in skel_neighbors(current) if q != previous]
                if not next_pixels:
                    break
                nxt = next_pixels[0]
                visited_edges.add(edge_key(current, nxt))
                path.append(nxt)
                previous, current = current, nxt
            paths.append(path)

    # Closed loops where every pixel has degree 2, such as the sun circle.
    remaining_edges = []
    for y, x in skeleton_points:
        p = (int(y), int(x))
        for q in skel_neighbors(p):
            if edge_key(p, q) not in visited_edges:
                remaining_edges.append((p, q))

    while remaining_edges:
        start, neighbor = remaining_edges.pop()
        if edge_key(start, neighbor) in visited_edges:
            continue
        path = [start, neighbor]
        visited_edges.add(edge_key(start, neighbor))
        previous, current = start, neighbor
        guard = 0
        while current != start and guard < 100000:
            guard += 1
            next_pixels = [q for q in skel_neighbors(current) if q != previous]
            if not next_pixels:
                break
            nxt = next_pixels[0]
            if edge_key(current, nxt) in visited_edges and nxt != start:
                break
            visited_edges.add(edge_key(current, nxt))
            path.append(nxt)
            previous, current = current, nxt
        if len(path) > 2:
            paths.append(path)

    return paths


def trace_skeleton_paired(skeleton: np.ndarray, pair_dot_cutoff: float) -> list[list[tuple[int, int]]]:
    h, w = skeleton.shape
    skeleton_points = np.argwhere(skeleton)
    if len(skeleton_points) == 0:
        return []

    deg = np.zeros(skeleton.shape, dtype=np.uint8)
    for y, x in skeleton_points:
        deg[y, x] = degree(skeleton, int(y), int(x))

    nodes = set(map(tuple, np.argwhere(skeleton & (deg != 2))))
    if not nodes:
        return trace_skeleton_paths(skeleton)

    def edge_key(a: tuple[int, int], b: tuple[int, int]):
        return tuple(sorted((a, b)))

    def skel_neighbors(p: tuple[int, int]) -> list[tuple[int, int]]:
        py, px = p
        output = []
        for dy, dx in NEIGHBORS_8:
            q = (py + dy, px + dx)
            if 0 <= q[0] < h and 0 <= q[1] < w and skeleton[q]:
                output.append(q)
        return output

    edges: list[list[tuple[int, int]]] = []
    visited_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    incidents: dict[tuple[int, int], list[tuple[int, int, tuple[float, float]]]] = {}

    def outward_vector(chain: list[tuple[int, int]], end_index: int) -> tuple[float, float]:
        if end_index == 0:
            a = chain[0]
            b = chain[min(len(chain) - 1, 4)]
        else:
            a = chain[-1]
            b = chain[max(0, len(chain) - 5)]
        vx = float(b[1] - a[1])
        vy = float(b[0] - a[0])
        length = math.hypot(vx, vy) or 1.0
        return vx / length, vy / length

    for node in list(nodes):
        for neighbor in skel_neighbors(node):
            key = edge_key(node, neighbor)
            if key in visited_edges:
                continue
            chain = [node, neighbor]
            visited_edges.add(key)
            previous, current = node, neighbor
            guard = 0
            while current not in nodes and guard < 100000:
                guard += 1
                next_pixels = [q for q in skel_neighbors(current) if q != previous]
                if not next_pixels:
                    break
                nxt = next_pixels[0]
                visited_edges.add(edge_key(current, nxt))
                chain.append(nxt)
                previous, current = current, nxt
            edge_id = len(edges)
            edges.append(chain)
            for end_index, p in ((0, chain[0]), (1, chain[-1])):
                if p in nodes:
                    incidents.setdefault(p, []).append((edge_id, end_index, outward_vector(chain, end_index)))

    pair_for: dict[tuple[int, int], tuple[int, int]] = {}
    for incident in incidents.values():
        candidates = []
        for i in range(len(incident)):
            e1, end1, v1 = incident[i]
            for j in range(i + 1, len(incident)):
                e2, end2, v2 = incident[j]
                dot = v1[0] * v2[0] + v1[1] * v2[1]
                candidates.append((dot, e1, end1, e2, end2))
        used: set[tuple[int, int]] = set()
        for dot, e1, end1, e2, end2 in sorted(candidates):
            a = (e1, end1)
            b = (e2, end2)
            if a in used or b in used:
                continue
            # Opposite outgoing directions represent one stroke passing through
            # the junction. A looser cutoff handles 8-connected stair steps.
            if dot > pair_dot_cutoff:
                continue
            pair_for[a] = b
            pair_for[b] = a
            used.add(a)
            used.add(b)

    def oriented(edge_id: int, start_end: int) -> list[tuple[int, int]]:
        chain = edges[edge_id]
        return chain if start_end == 0 else list(reversed(chain))

    paths: list[list[tuple[int, int]]] = []
    used_edges: set[int] = set()

    starts = []
    for edge_id in range(len(edges)):
        for end_index in (0, 1):
            if (edge_id, end_index) not in pair_for:
                starts.append((edge_id, end_index))

    def trace_from(start: tuple[int, int]) -> list[tuple[int, int]]:
        edge_id, start_end = start
        path: list[tuple[int, int]] = []
        while edge_id not in used_edges:
            segment = oriented(edge_id, start_end)
            used_edges.add(edge_id)
            path.extend(segment if not path else segment[1:])
            exit_end = 1 - start_end
            nxt = pair_for.get((edge_id, exit_end))
            if nxt is None:
                break
            edge_id, paired_end = nxt
            start_end = paired_end
        return path

    for start in starts:
        if start[0] in used_edges:
            continue
        path = trace_from(start)
        if len(path) > 1:
            paths.append(path)

    for edge_id in range(len(edges)):
        if edge_id in used_edges:
            continue
        path = trace_from((edge_id, 0))
        if len(path) > 1:
            paths.append(path)

    return paths


def centerline(mask: np.ndarray, method: str) -> np.ndarray:
    if method == "medial-axis":
        return medial_axis(mask)
    if method == "lee":
        return skeletonize(mask, method="lee")
    if method == "zhang":
        return skeletonize(mask, method="zhang")
    raise ValueError(f"Unsupported skeleton method {method!r}.")


def trace_centerline(skeleton: np.ndarray, mode: str, pair_dot_cutoff: float) -> list[list[tuple[int, int]]]:
    if mode == "split":
        return trace_skeleton_paths(skeleton)
    if mode == "paired":
        return trace_skeleton_paired(skeleton, pair_dot_cutoff)
    raise ValueError(f"Unsupported trace mode {mode!r}.")


def simplify_path(
    path: list[tuple[int, int]],
    epsilon: float,
    scale: float = 1.0,
    viewbox_origin: tuple[int, int] = (0, 0),
) -> tuple[list[tuple[float, float]], bool]:
    """Simplify the pixel chain with Douglas-Peucker and return SVG x/y points."""
    contour = np.array([[p[1], p[0]] for p in path], dtype=np.float32).reshape((-1, 1, 2))
    closed = False
    if len(path) > 3:
        dx = path[0][1] - path[-1][1]
        dy = path[0][0] - path[-1][0]
        closed = (dx * dx + dy * dy) <= 4

    approx = cv2.approxPolyDP(contour, epsilon, closed)
    ox, oy = viewbox_origin
    points = [
        (ox + float(point[0][0]) / scale, oy + float(point[0][1]) / scale)
        for point in approx
    ]
    if closed and points and points[0] != points[-1]:
        points.append(points[0])
    return points, closed


def path_length(points: list[tuple[float, float]]) -> float:
    return sum(
        math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
        for i in range(1, len(points))
    )


def format_number(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def svg_path_d(points: list[tuple[float, float]], closed: bool) -> str:
    if not points:
        return ""
    parts = [f"M {format_number(points[0][0])} {format_number(points[0][1])}"]
    for x, y in points[1:]:
        parts.append(f"L {format_number(x)} {format_number(y)}")
    if closed:
        parts.append("Z")
    return " ".join(parts)


def path_data_length(attrs: str) -> int:
    match = re.search(r'\bd\s*=\s*["\']([\s\S]*?)["\']', attrs, flags=re.I)
    return len(match.group(1)) if match else 0


def hough_strokes(
    skeleton: np.ndarray,
    stroke_width: float,
    color: str,
    scale: float,
    viewbox_origin: tuple[int, int],
) -> list[dict[str, object]]:
    image = (skeleton.astype(np.uint8) * 255)
    lines = cv2.HoughLinesP(
        image,
        rho=1,
        theta=np.pi / 180,
        threshold=18,
        minLineLength=max(16, int(round(28 * scale))),
        maxLineGap=max(8, int(round(18 * scale))),
    )
    if lines is None:
        return []

    ox, oy = viewbox_origin
    output: list[dict[str, object]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for line in lines[:, 0, :]:
        x1, y1, x2, y2 = [int(v) for v in line]
        if math.hypot(x2 - x1, y2 - y1) < 20 * scale:
            continue
        key = tuple(round(v / (3 * scale)) for v in (x1, y1, x2, y2))
        reverse_key = (key[2], key[3], key[0], key[1])
        if key in seen or reverse_key in seen:
            continue
        seen.add(key)
        p1 = (ox + x1 / scale, oy + y1 / scale)
        p2 = (ox + x2 / scale, oy + y2 / scale)
        output.append({
            "color": color,
            "stroke_width": stroke_width,
            "d": svg_path_d([p1, p2], closed=False),
            "linecap": "round",
            "caps": [],
        })
    return output


def convert_svg(
    input_svg: Path,
    output_svg: Path,
    mode: str = "elements",
    scale: float = 1.0,
    skeleton_method: str = "zhang",
    cap_mode: str = "round",
    scribble_mode: str = "none",
    scribble_path_length: int = 5000,
    trace_mode: str = "split",
    pair_dot_cutoff: float = -0.2,
    alpha_threshold: int = 48,
    min_object_size: int = 20,
    min_path_length: float = 15,
    simplify_epsilon: float = 2.2,
    min_stroke_width: float = 6.0,
    max_stroke_width: float = 18.0,
    stroke_scale: float = 1.0,
) -> None:
    svg_text = input_svg.read_text(encoding="utf-8")
    viewbox = read_viewbox(svg_text)
    x, y, width, height = viewbox
    scale = max(1.0, scale)
    output_paths: list[dict[str, object] | tuple[str, float, str]] = []

    if mode == "elements":
        elements = parse_filled_elements(svg_text)

        for element in elements:
            color_mask = render_element_mask(element, viewbox, scale)

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                color_mask = closing(color_mask, disk(1))
                color_mask = remove_small_objects(
                    color_mask,
                    min_size=max(1, int(round(min_object_size * scale * scale))),
                )

            if not color_mask.any():
                continue

            skeleton = centerline(color_mask, skeleton_method)
            distance_to_edge = cv2.distanceTransform(color_mask.astype(np.uint8), cv2.DIST_L2, 5)
            skeleton_distances = distance_to_edge[skeleton]
            true_endpoints = {
                (int(py), int(px))
                for py, px in np.argwhere(skeleton)
                if degree(skeleton, int(py), int(px)) <= 1
            }
            stroke_width = float(np.median(skeleton_distances) * 2 / scale) if skeleton_distances.size else 8.0
            stroke_width = max(min_stroke_width, min(max_stroke_width, stroke_width))
            stroke_width *= stroke_scale

            if scribble_mode == "hough" and path_data_length(element["attrs"]) >= scribble_path_length:
                hough_paths = hough_strokes(
                    skeleton,
                    stroke_width,
                    element["fill"],
                    scale,
                    viewbox_origin=(x, y),
                )
                if hough_paths:
                    output_paths.extend(hough_paths)
                    continue

            for path in trace_centerline(skeleton, trace_mode, pair_dot_cutoff):
                if len(path) < 8:
                    continue

                points, closed = simplify_path(
                    path,
                    simplify_epsilon,
                    scale=scale,
                    viewbox_origin=(x, y),
                )

                if len(points) < 2 or path_length(points) < min_path_length:
                    continue

                d = svg_path_d(points, closed=closed)
                caps = []
                if cap_mode == "endpoint":
                    for py, px in (path[0], path[-1]):
                        if (int(py), int(px)) in true_endpoints:
                            caps.append((x + px / scale, y + py / scale))
                output_paths.append({
                    "color": element["fill"],
                    "stroke_width": stroke_width,
                    "d": d,
                    "linecap": "butt" if cap_mode == "endpoint" else "round",
                    "caps": caps,
                })

        write_output_svg(output_svg, viewbox, output_paths)
        return

    if mode != "colors":
        raise ValueError(f"Unsupported mode {mode!r}. Use 'elements' or 'colors'.")

    colors = extract_fill_colors(svg_text)
    color_rgb = {color: hex_to_rgb(color) for color in colors}

    rgba = render_svg_to_rgba(input_svg, width, height)
    alpha = rgba[..., 3]
    rgb = rgba[..., :3].astype(np.int16)

    visible_mask = alpha > alpha_threshold

    # Anti-aliasing introduces intermediate colors at edges. Assign every visible
    # pixel to the closest original fill color so each source color is processed
    # as a separate drawing layer.
    palette = np.array([color_rgb[color] for color in colors], dtype=np.int16)
    color_distance = ((rgb[..., None, :] - palette[None, None, :, :]) ** 2).sum(axis=-1)
    nearest_color_index = color_distance.argmin(axis=-1)

    for color_index, color in enumerate(colors):
        color_mask = visible_mask & (nearest_color_index == color_index)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            color_mask = closing(color_mask, disk(1))
            color_mask = remove_small_objects(color_mask, min_size=min_object_size)

        skeleton = centerline(color_mask, skeleton_method)

        # Estimate original ribbon thickness by measuring distance from each
        # skeleton pixel to the edge of its color region. Radius * 2 ≈ stroke width.
        distance_to_edge = cv2.distanceTransform(color_mask.astype(np.uint8), cv2.DIST_L2, 5)
        skeleton_distances = distance_to_edge[skeleton]
        stroke_width = float(np.median(skeleton_distances) * 2) if skeleton_distances.size else 8.0
        stroke_width = max(min_stroke_width, min(max_stroke_width, stroke_width))
        stroke_width *= stroke_scale

        for path in trace_centerline(skeleton, trace_mode, pair_dot_cutoff):
            if len(path) < 8:
                continue

            points, closed = simplify_path(path, simplify_epsilon)

            if len(points) < 2 or path_length(points) < min_path_length:
                continue

            d = svg_path_d(points, closed=closed)
            output_paths.append((color, stroke_width, d))

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="{SVG_NS}" version="1.1" viewBox="{x} {y} {width} {height}">',
        '  <g fill="none" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke">',
    ]

    for color, stroke_width, d in output_paths:
        lines.append(f'    <path d="{d}" stroke="{color}" stroke-width="{stroke_width:.1f}"/>')

    lines.extend([
        '  </g>',
        '</svg>',
    ])

    output_svg.write_text("\n".join(lines), encoding="utf-8")


def write_output_svg(
    output_svg: Path,
    viewbox: tuple[int, int, int, int],
    output_paths: list[dict[str, object] | tuple[str, float, str]],
) -> None:
    x, y, width, height = viewbox
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="{SVG_NS}" version="1.1" viewBox="{x} {y} {width} {height}">',
        '  <g fill="none" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke">',
    ]

    for item in output_paths:
        if isinstance(item, tuple):
            color, stroke_width, d = item
            lines.append(f'    <path d="{d}" stroke="{color}" stroke-width="{stroke_width:.1f}"/>')
            continue

        color = str(item["color"])
        stroke_width = float(item["stroke_width"])
        d = str(item["d"])
        linecap = str(item.get("linecap", "round"))
        linecap_attr = "" if linecap == "round" else f' stroke-linecap="{linecap}"'
        lines.append(f'    <path d="{d}" stroke="{color}" stroke-width="{stroke_width:.1f}"{linecap_attr}/>')
        for cx, cy in item.get("caps", []):
            x2 = float(cx) + 0.01
            lines.append(
                f'    <path d="M {format_number(float(cx))} {format_number(float(cy))} '
                f'L {format_number(x2)} {format_number(float(cy))}" '
                f'stroke="{color}" stroke-width="{stroke_width:.1f}" stroke-linecap="round"/>'
            )

    lines.extend([
        '  </g>',
        '</svg>',
    ])

    output_svg.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert filled-ribbon SVG line art into fill=none stroked SVG paths."
    )
    parser.add_argument("input", type=Path, help="Input SVG whose apparent lines are filled shapes.")
    parser.add_argument("--output", "-o", type=Path, help="Output SVG path. Defaults to <input>-lines.svg.")
    parser.add_argument("--mode", choices=["elements", "colors"], default="elements", help="Segment by filled SVG element or by color. Default: elements.")
    parser.add_argument("--scale", type=float, default=1.0, help="Rasterization scale for element mode. Default: 1.")
    parser.add_argument("--skeleton-method", choices=["zhang", "lee", "medial-axis"], default="zhang", help="Centerline extraction method. Default: zhang.")
    parser.add_argument("--cap-mode", choices=["round", "endpoint"], default="round", help="Use round caps everywhere or only at true skeleton endpoints. Default: round.")
    parser.add_argument("--scribble-mode", choices=["none", "hough"], default="none", help="Experimental reconstruction mode for large scribble fill paths. Default: none.")
    parser.add_argument("--scribble-path-length", type=int, default=5000, help="Minimum source path-data length for scribble mode. Default: 5000.")
    parser.add_argument("--trace-mode", choices=["split", "paired"], default="split", help="Trace centerlines as split graph edges or pair straight-through junctions. Default: split.")
    parser.add_argument("--pair-dot-cutoff", type=float, default=-0.2, help="Maximum outgoing-vector dot product to pair branches at a junction. Higher pairs sharper turns. Default: -0.2.")
    parser.add_argument("--alpha-threshold", type=int, default=48, help="Visible-pixel alpha cutoff. Default: 48.")
    parser.add_argument("--min-object-size", type=int, default=20, help="Remove color blobs smaller than this many pixels. Default: 20.")
    parser.add_argument("--min-path-length", type=float, default=15, help="Discard traced paths shorter than this. Default: 15.")
    parser.add_argument("--simplify-epsilon", type=float, default=2.2, help="Douglas-Peucker simplification amount. Lower preserves more detail. Default: 2.2.")
    parser.add_argument("--min-stroke-width", type=float, default=6.0, help="Minimum emitted stroke width. Default: 6.")
    parser.add_argument("--max-stroke-width", type=float, default=18.0, help="Maximum emitted stroke width. Default: 18.")
    parser.add_argument("--stroke-scale", type=float, default=1.0, help="Multiply estimated stroke widths by this factor after clamping. Default: 1.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_svg = args.input
    output_svg = args.output or input_svg.with_name(f"{input_svg.stem}-lines.svg")

    convert_svg(
        input_svg=input_svg,
        output_svg=output_svg,
        mode=args.mode,
        scale=args.scale,
        skeleton_method=args.skeleton_method,
        cap_mode=args.cap_mode,
        scribble_mode=args.scribble_mode,
        scribble_path_length=args.scribble_path_length,
        trace_mode=args.trace_mode,
        pair_dot_cutoff=args.pair_dot_cutoff,
        alpha_threshold=args.alpha_threshold,
        min_object_size=args.min_object_size,
        min_path_length=args.min_path_length,
        simplify_epsilon=args.simplify_epsilon,
        min_stroke_width=args.min_stroke_width,
        max_stroke_width=args.max_stroke_width,
        stroke_scale=args.stroke_scale,
    )

    print(f"Wrote {output_svg}")


if __name__ == "__main__":
    main()
