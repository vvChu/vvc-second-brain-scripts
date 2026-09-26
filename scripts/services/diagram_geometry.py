"""VvC Second Brain — Diagram Geometry & Canvas Engine.

Mathematical computations for Excalidraw shape boundaries, arrow routing,
bound text displacement synchronization, and canvas bounding-box normalization.
"""

from __future__ import annotations

import math
from typing import Any

from core.config import cfg


def get_shape_boundary_point(shape: dict[str, Any], dx: float, dy: float) -> tuple[float, float]:
    """Compute exact boundary point of a shape along direction (dx, dy) from center.

    Supports rectangle/diamond (axis-aligned box clipping) and ellipse (parametric).

    Args:
        shape: Excalidraw element dict with x, y, width, height, type.
        dx: X component of direction vector.
        dy: Y component of direction vector.

    Returns:
        (bx, by) — boundary point on the shape perimeter.
    """
    cx = float(shape.get("x", 0)) + float(shape.get("width", 150)) / 2
    cy = float(shape.get("y", 0)) + float(shape.get("height", 100)) / 2
    hw = float(shape.get("width", 150)) / 2
    hh = float(shape.get("height", 100)) / 2

    dist = math.hypot(dx, dy)
    if dist == 0 or hw == 0 or hh == 0:
        return cx, cy

    ndx = dx / dist
    ndy = dy / dist

    if shape.get("type") == "ellipse":
        denom = math.sqrt((ndx / hw) ** 2 + (ndy / hh) ** 2)
        t = 1.0 / denom if denom > 0 else min(hw, hh)
    else:
        tx = hw / abs(ndx) if abs(ndx) > 1e-9 else float("inf")
        ty = hh / abs(ndy) if abs(ndy) > 1e-9 else float("inf")
        t = min(tx, ty)

    return cx + ndx * t, cy + ndy * t


def sync_bound_text_translation(
    shape: dict[str, Any],
    elements: list[dict[str, Any]],
    dx: float,
    dy: float,
) -> None:
    """Synchronously translate bound text elements for a shape."""
    sid = shape.get("id")
    if not sid:
        return

    bound_text_ids = set()
    for bound in shape.get("boundElements", []):
        if isinstance(bound, dict) and bound.get("type") == "text" and bound.get("id"):
            bound_text_ids.add(bound["id"])

    for el in elements:
        if el.get("type") != "text":
            continue
        el_id = el.get("id")
        is_bound = (
            (el_id and el_id in bound_text_ids)
            or (el.get("containerId") == sid)
            or (el.get("containerHeaderOf") == sid)
        )
        if is_bound:
            el["x"] = float(el.get("x", 0.0) + dx)
            el["y"] = float(el.get("y", 0.0) + dy)
            if not el.get("strokeColor"):
                el["strokeColor"] = cfg.excalidraw_stroke_color
            if not el.get("fontFamily"):
                el["fontFamily"] = cfg.excalidraw_font_family


def _calculate_canvas_min_bounds(elements: list[dict[str, Any]]) -> tuple[float, float]:
    """Find minimum x and y coordinates across all elements including arrow points."""
    min_x = float("inf")
    min_y = float("inf")

    for el in elements:
        if "x" not in el or "y" not in el:
            continue
        el_x = float(el.get("x", 0.0))
        el_y = float(el.get("y", 0.0))

        if el.get("type") == "arrow" and "points" in el:
            pts = el["points"]
            if isinstance(pts, list) and pts:
                p_xs = [el_x + float(p[0]) for p in pts if isinstance(p, (list, tuple)) and len(p) >= 2]
                p_ys = [el_y + float(p[1]) for p in pts if isinstance(p, (list, tuple)) and len(p) >= 2]
                if p_xs:
                    min_x = min(min_x, min(p_xs))
                if p_ys:
                    min_y = min(min_y, min(p_ys))
        else:
            min_x = min(min_x, el_x)
            min_y = min(min_y, el_y)

    return min_x, min_y


def normalize_canvas_bounding_box(
    elements: list[dict[str, Any]],
    min_padding_x: float = 80.0,
    min_padding_y: float = 60.0,
) -> None:
    """Shift all canvas elements to safe positive coordinates if clipping occurs."""
    if not elements:
        return

    min_x, min_y = _calculate_canvas_min_bounds(elements)
    if min_x == float("inf") or min_y == float("inf"):
        return

    shift_x = min_padding_x - min_x if min_x < min_padding_x else 0.0
    shift_y = min_padding_y - min_y if min_y < min_padding_y else 0.0

    if shift_x > 0.0 or shift_y > 0.0:
        for el in elements:
            if "x" in el:
                el["x"] = float(el.get("x", 0.0) + shift_x)
            if "y" in el:
                el["y"] = float(el.get("y", 0.0) + shift_y)


def compute_safe_arrow_endpoints(
    s_shape: dict[str, Any],
    e_shape: dict[str, Any],
) -> tuple[float, float, float, float]:
    """Compute safe arrow start and end points between two shapes."""
    sx = float(s_shape.get("x", 0.0)) + float(s_shape.get("width", 150.0)) / 2.0
    sy = float(s_shape.get("y", 0.0)) + float(s_shape.get("height", 100.0)) / 2.0
    ex = float(e_shape.get("x", 0.0)) + float(e_shape.get("width", 150.0)) / 2.0
    ey = float(e_shape.get("y", 0.0)) + float(e_shape.get("height", 100.0)) / 2.0

    dx = ex - sx
    dy = ey - sy
    dist = math.hypot(dx, dy)
    if dist <= 0:
        return sx, sy, ex, ey

    bsx, bsy = get_shape_boundary_point(s_shape, dx, dy)
    bex, bey = get_shape_boundary_point(e_shape, -dx, -dy)
    dot = (bex - bsx) * (dx / dist) + (bey - bsy) * (dy / dist)

    if dot > 12.0:
        padding = min(5.0, (dot - 2.0) / 2.0)
        start_x = bsx + (dx / dist) * padding
        start_y = bsy + (dy / dist) * padding
        end_x = bex - (dx / dist) * padding
        end_y = bey - (dy / dist) * padding
    elif dot > 0:
        start_x, start_y = bsx, bsy
        end_x, end_y = bex, bey
    else:
        start_x, start_y, end_x, end_y = sx, sy, ex, ey

    return float(start_x), float(start_y), float(end_x), float(end_y)
