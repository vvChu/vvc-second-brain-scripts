import math
import networkx as nx
from core.config import cfg
from services.diagram_base import (
    compute_safe_arrow_endpoints,
    sync_bound_text_translation,
)

def _extract_shapes_and_edges(
    elements: list[dict],
) -> tuple[dict[str, dict], list[tuple[dict, str, str]], nx.DiGraph]:
    """Extract shapes, arrows and build NetworkX directed graph."""
    shapes = {
        el["id"]: el
        for el in elements
        if el.get("type") in ("rectangle", "ellipse", "diamond")
    }
    arrows = [el for el in elements if el.get("type") == "arrow"]
    G = nx.DiGraph()
    for sid in shapes:
        G.add_node(sid)

    edges = []
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
            G.add_edge(sid, eid)
            edges.append((arr, sid, eid))
    return shapes, edges, G


def _order_cycle_nodes(G: nx.DiGraph) -> list[str]:
    """Order nodes along the largest directed cycle if available."""
    try:
        cycles = list(nx.simple_cycles(G))
        if cycles:
            ordered_nodes = list(max(cycles, key=len))
            for n in G.nodes:
                if n not in ordered_nodes:
                    ordered_nodes.append(n)
            return ordered_nodes
    except Exception:
        pass
    return list(G.nodes)


def _compute_cycle_positions(
    ordered_nodes: list[str], center_x: float, center_y: float
) -> dict[str, tuple[float, float]]:
    """Compute circular positions around center point."""
    pos: dict[str, tuple[float, float]] = {}
    n = len(ordered_nodes)
    if n > 0:
        radius = max(250, n * 60)
        angle_step = 2 * math.pi / n
        for i, nid in enumerate(ordered_nodes):
            angle = i * angle_step - math.pi / 2
            pos[nid] = (
                center_x + radius * math.cos(angle),
                center_y + radius * math.sin(angle),
            )
    return pos


def _apply_shape_geometry(
    shapes: dict[str, dict],
    pos: dict[str, tuple[float, float]],
    elements: list[dict],
) -> None:
    """Update shape bounds and apply academic grayscale theme."""
    for sid, (x, y) in pos.items():
        shape = shapes[sid]
        old_x, old_y = shape.get("x", 0), shape.get("y", 0)
        sw, sh = shape.get("width", 150), shape.get("height", 100)
        new_x, new_y = x - sw / 2, y - sh / 2

        shape["x"] = float(new_x)
        shape["y"] = float(new_y)
        shape["roughness"] = 0
        shape["backgroundColor"] = cfg.excalidraw_background_color
        shape["strokeColor"] = cfg.excalidraw_stroke_color
        shape["strokeWidth"] = cfg.excalidraw_stroke_width
        shape["fillStyle"] = "solid"

        sync_bound_text_translation(shape, elements, new_x - old_x, new_y - old_y)


def _apply_curved_arrows(
    edges: list[tuple[dict, str, str]],
    shapes: dict[str, dict],
    center_x: float,
    center_y: float,
) -> None:
    """Update arrows geometrically with outward-curving midpoint."""
    for arr, sid, eid in edges:
        s_shape, e_shape = shapes[sid], shapes[eid]
        start_x, start_y, end_x, end_y = compute_safe_arrow_endpoints(s_shape, e_shape)
        mx = (start_x + end_x) / 2
        my = (start_y + end_y) / 2

        v_cx = mx - center_x
        v_cy = my - center_y
        v_dist = math.hypot(v_cx, v_cy)
        if v_dist > 0:
            push_amount = 50
            mx = mx + (v_cx / v_dist) * push_amount
            my = my + (v_cy / v_dist) * push_amount

        arr["x"] = start_x
        arr["y"] = start_y
        arr["points"] = [
            [0.0, 0.0],
            [float(mx - start_x), float(my - start_y)],
            [float(end_x - start_x), float(end_y - start_y)],
        ]
        arr["roughness"] = 0
        arr["strokeColor"] = cfg.excalidraw_stroke_color
        arr["strokeWidth"] = cfg.excalidraw_stroke_width
        arr["roundness"] = {"type": 2}
        if arr.get("strokeStyle") != "dashed":
            arr["strokeStyle"] = "solid"


def apply_cycle_layout(elements: list[dict]) -> bool:
    """Applies Cyclic Layout to Excalidraw elements."""
    shapes, edges, G = _extract_shapes_and_edges(elements)
    if not shapes or not G.nodes:
        return False

    center_x, center_y = 600, 400
    ordered_nodes = _order_cycle_nodes(G)
    pos = _compute_cycle_positions(ordered_nodes, center_x, center_y)

    _apply_shape_geometry(shapes, pos, elements)
    _apply_curved_arrows(edges, shapes, center_x, center_y)
    return True
