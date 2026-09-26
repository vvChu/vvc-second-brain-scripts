from __future__ import annotations

import math
import uuid
from typing import Any

from core.config import cfg
from services.diagram_base import (
    compute_safe_arrow_endpoints,
    sync_bound_text_translation,
)


def _get_shape_text(shape: dict[str, Any], elements: list[dict[str, Any]]) -> str:
    """Retrieve all text associated with a shape."""
    texts = []
    if shape.get("text"):
        texts.append(str(shape["text"]))
    sid = shape.get("id")
    for bound in shape.get("boundElements", []):
        if isinstance(bound, dict) and bound.get("type") == "text":
            tid = bound.get("id")
            for el in elements:
                if el.get("id") == tid and el.get("text"):
                    texts.append(str(el["text"]))
    for el in elements:
        if el.get("type") == "text" and el.get("containerId") == sid and el.get("text"):
            texts.append(str(el["text"]))
    return " ".join(texts).lower()


def _assign_quadrants(
    shape_ids: list[str],
    shapes: dict[str, dict[str, Any]],
    elements: list[dict[str, Any]],
) -> dict[str, int]:
    """Map each shape ID to a quadrant index (0: TL, 1: TR, 2: BL, 3: BR)."""
    assigned: dict[str, int] = {}
    remaining = list(shape_ids)

    # 1. Keyword-based matching
    kw_quadrants = {
        0: ["top_left", "high_left", "goc 2", "góc 2", "q2", "quadrant 2", "tl"],
        1: ["top_right", "high_right", "goc 4", "góc 4", "q4", "quadrant 4", "tr"],
        2: ["bot_left", "bottom_left", "low_left", "goc 1", "góc 1", "q1", "quadrant 1", "bl"],
        3: ["bot_right", "bottom_right", "low_right", "goc 3", "góc 3", "q3", "quadrant 3", "br"],
    }
    for sid in list(remaining):
        s_text = f"{sid.lower()} {_get_shape_text(shapes[sid], elements)}"
        for q_idx, kws in kw_quadrants.items():
            if any(kw in s_text for kw in kws):
                if q_idx not in assigned.values():
                    assigned[sid] = q_idx
                    remaining.remove(sid)
                    break

    # 2. Position-based matching if coordinates are distinct
    if remaining:
        xs = [shapes[sid].get("x", 0.0) for sid in shape_ids]
        ys = [shapes[sid].get("y", 0.0) for sid in shape_ids]
        if max(xs) - min(xs) > 30 or max(ys) - min(ys) > 30:
            avg_x = sum(xs) / len(xs)
            avg_y = sum(ys) / len(ys)
            for sid in list(remaining):
                col = 0 if shapes[sid].get("x", 0.0) < avg_x else 1
                row = 0 if shapes[sid].get("y", 0.0) < avg_y else 1
                q_idx = row * 2 + col
                if q_idx not in assigned.values():
                    assigned[sid] = q_idx
                    remaining.remove(sid)

    # 3. Sequential fallback for any remaining nodes
    available_slots = [q for q in range(max(4, len(shape_ids))) if q not in assigned.values()]
    for sid in remaining:
        slot = available_slots.pop(0) if available_slots else len(assigned)
        assigned[sid] = slot

    return assigned


def _position_matrix_shapes(
    shapes: dict[str, dict[str, Any]],
    elements: list[dict[str, Any]],
    quad_assignments: dict[str, int],
    cx: float,
    cy: float,
    col_offset: float,
    row_offset: float,
) -> None:
    """Position matrix nodes into assigned quadrant slots."""
    slot_coords = {
        0: (cx - col_offset, cy - row_offset),
        1: (cx + col_offset, cy - row_offset),
        2: (cx - col_offset, cy + row_offset),
        3: (cx + col_offset, cy + row_offset),
    }
    for sid, q_idx in quad_assignments.items():
        shape = shapes[sid]
        target_cx, target_cy = slot_coords.get(
            q_idx,
            (
                cx + (1.0 if q_idx % 2 else -1.0) * col_offset,
                cy + (1.0 if (q_idx // 2) % 2 else -1.0) * row_offset + (q_idx // 4) * 180.0,
            ),
        )
        old_x, old_y = shape.get("x", 0.0), shape.get("y", 0.0)
        sw, sh = shape.get("width", 150.0), shape.get("height", 100.0)
        new_x, new_y = target_cx - sw / 2.0, target_cy - sh / 2.0

        shape["x"] = float(new_x)
        shape["y"] = float(new_y)
        shape["roughness"] = 0
        shape["backgroundColor"] = cfg.excalidraw_background_color
        shape["strokeColor"] = cfg.excalidraw_stroke_color
        shape["strokeWidth"] = cfg.excalidraw_stroke_width
        shape["fillStyle"] = "solid"

        sync_bound_text_translation(shape, elements, new_x - old_x, new_y - old_y)


def _create_cross_dividers(
    cx: float, cy: float, min_x: float, max_x: float, min_y: float, max_y: float
) -> list[dict[str, Any]]:
    """Create vertical and horizontal crosshair dividers."""
    return [
        {
            "id": f"matrix_v_{uuid.uuid4().hex[:8]}",
            "type": "arrow",
            "x": cx,
            "y": min_y,
            "width": 0,
            "height": max_y - min_y,
            "strokeColor": "#a8a29e",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 0,
            "points": [[0, 0], [0, float(max_y - min_y)]],
            "startArrowhead": None,
            "endArrowhead": None,
        },
        {
            "id": f"matrix_h_{uuid.uuid4().hex[:8]}",
            "type": "arrow",
            "x": min_x,
            "y": cy,
            "width": max_x - min_x,
            "height": 0,
            "strokeColor": "#a8a29e",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 0,
            "points": [[0, 0], [float(max_x - min_x), 0]],
            "startArrowhead": None,
            "endArrowhead": None,
        },
    ]


def _create_axis_dividers(
    min_x: float, max_x: float, min_y: float, max_y: float
) -> list[dict[str, Any]]:
    """Create X and Y coordinate axis dividers."""
    origin_x = min_x + 50.0
    origin_y = max_y - 30.0
    return [
        {
            "id": f"axis_y_{uuid.uuid4().hex[:8]}",
            "type": "arrow",
            "x": origin_x,
            "y": origin_y,
            "width": 0,
            "height": origin_y - min_y,
            "strokeColor": cfg.excalidraw_stroke_color,
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 0,
            "points": [[0, 0], [0, float(-(origin_y - min_y))]],
            "startArrowhead": None,
            "endArrowhead": "arrow",
        },
        {
            "id": f"axis_x_{uuid.uuid4().hex[:8]}",
            "type": "arrow",
            "x": origin_x,
            "y": origin_y,
            "width": max_x - origin_x,
            "height": 0,
            "strokeColor": cfg.excalidraw_stroke_color,
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 0,
            "points": [[0, 0], [float(max_x - origin_x), 0]],
            "startArrowhead": None,
            "endArrowhead": "arrow",
        },
    ]


def _update_matrix_arrows(
    arrows: list[dict[str, Any]], shapes: dict[str, dict[str, Any]]
) -> None:
    """Trim and style interconnecting arrows."""
    for arr in arrows:
        sb = arr.get("startBinding", {})
        eb = arr.get("endBinding", {})
        sid = (
            sb.get("elementId")
            if isinstance(sb, dict)
            else (sb if isinstance(sb, str) else None)
        )
        eid = (
            eb.get("elementId")
            if isinstance(eb, dict)
            else (eb if isinstance(eb, str) else None)
        )
        if sid in shapes and eid in shapes:
            sx, sy, ex, ey = compute_safe_arrow_endpoints(shapes[sid], shapes[eid])
            arr["x"] = sx
            arr["y"] = sy
            arr["points"] = [[0.0, 0.0], [float(ex - sx), float(ey - sy)]]
        arr["roughness"] = 0
        arr["strokeColor"] = cfg.excalidraw_stroke_color
        if arr.get("strokeStyle") != "dashed":
            arr["strokeStyle"] = "solid"


def apply_matrix_layout(elements: list[dict], style: str = "cross") -> bool:
    """Applies 2x2 Matrix / Quadrant Grid Layout to Excalidraw elements."""
    shapes = {
        el["id"]: el
        for el in elements
        if el.get("type") in ("rectangle", "ellipse", "diamond")
    }
    arrows = [el for el in elements if el.get("type") == "arrow"]
    if not shapes:
        return False

    cx, cy = 600.0, 400.0
    col_offset, row_offset = 180.0, 130.0
    quad_assignments = _assign_quadrants(list(shapes.keys()), shapes, elements)

    _position_matrix_shapes(
        shapes, elements, quad_assignments, cx, cy, col_offset, row_offset
    )

    elements[:] = [
        el
        for el in elements
        if not (
            isinstance(el.get("id"), str)
            and (el["id"].startswith("matrix_") or el["id"].startswith("axis_"))
        )
    ]

    min_x, max_x = cx - col_offset - 120.0, cx + col_offset + 120.0
    min_y, max_y = cy - row_offset - 100.0, cy + row_offset + 100.0

    dividers = (
        _create_cross_dividers(cx, cy, min_x, max_x, min_y, max_y)
        if style == "cross"
        else _create_axis_dividers(min_x, max_x, min_y, max_y)
    )
    elements[0:0] = dividers

    _update_matrix_arrows(arrows, shapes)
    return True
