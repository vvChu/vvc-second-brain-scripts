import math
import networkx as nx
from core.config import cfg
from services.diagram_base import (
    compute_safe_arrow_endpoints,
    sync_bound_text_translation,
)

def _extract_shapes_and_edges(
    elements: list[dict],
) -> tuple[dict[str, dict], list[tuple[dict, str, str]], nx.Graph]:
    """Extract shapes, arrows and build NetworkX graph."""
    shapes = {
        el["id"]: el
        for el in elements
        if el.get("type") in ("rectangle", "ellipse", "diamond")
    }
    arrows = [el for el in elements if el.get("type") == "arrow"]
    G = nx.Graph()
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


def _compute_radial_positions(
    G: nx.Graph, hub_id: str, center_x: float, center_y: float
) -> dict[str, tuple[float, float]]:
    """Compute hub-and-spoke circular positions around hub."""
    pos = {hub_id: (center_x, center_y)}
    other_nodes = [n for n in G.nodes if n != hub_id]
    n = len(other_nodes)
    if n > 0:
        radius = max(300, n * 50)
        angle_step = 2 * math.pi / n
        for i, nid in enumerate(other_nodes):
            angle = i * angle_step - math.pi / 2
            pos[nid] = (
                center_x + radius * math.cos(angle),
                center_y + radius * math.sin(angle),
            )
    return pos


def _apply_shape_geometry(
    shapes: dict[str, dict],
    pos: dict[str, tuple[float, float]],
    hub_id: str,
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
        shape["strokeWidth"] = 3 if sid == hub_id else cfg.excalidraw_stroke_width
        shape["fillStyle"] = "solid"

        sync_bound_text_translation(shape, elements, new_x - old_x, new_y - old_y)


def _apply_arrow_geometry(
    edges: list[tuple[dict, str, str]], shapes: dict[str, dict]
) -> None:
    """Update arrows geometrically with center-to-center ray trimming."""
    for arr, sid, eid in edges:
        s_shape, e_shape = shapes[sid], shapes[eid]
        start_x, start_y, end_x, end_y = compute_safe_arrow_endpoints(s_shape, e_shape)
        arr["x"] = start_x
        arr["y"] = start_y
        arr["points"] = [[0.0, 0.0], [float(end_x - start_x), float(end_y - start_y)]]
        arr["roughness"] = 0
        arr["strokeColor"] = cfg.excalidraw_stroke_color
        arr["strokeWidth"] = cfg.excalidraw_stroke_width
        if arr.get("strokeStyle") != "dashed":
            arr["strokeStyle"] = "solid"


def apply_radial_layout(elements: list[dict]) -> bool:
    """Applies Radial (Star) Layout to Excalidraw elements."""
    shapes, edges, G = _extract_shapes_and_edges(elements)
    if not shapes or not G.nodes:
        return False

    degrees = dict(G.degree())
    if not degrees:
        return False
    hub_id = max(degrees, key=degrees.get)

    pos = _compute_radial_positions(G, hub_id, 600.0, 400.0)
    _apply_shape_geometry(shapes, pos, hub_id, elements)
    _apply_arrow_geometry(edges, shapes)
    return True
