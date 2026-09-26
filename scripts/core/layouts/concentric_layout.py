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


def _compute_concentric_positions(
    G: nx.Graph, hub_id: str
) -> dict[str, tuple[float, float]]:
    """Compute (x, y) coordinates for nodes arranged in concentric rings around hub."""
    lengths = nx.single_source_shortest_path_length(G, hub_id)
    layers: dict[int, list[str]] = {}
    for nid in G.nodes:
        dist = lengths.get(nid, 999)
        layers.setdefault(dist, []).append(nid)

    center_x, center_y = 600, 400
    pos: dict[str, tuple[float, float]] = {hub_id: (center_x, center_y)}
    sorted_dists = sorted([d for d in layers.keys() if d != 999 and d > 0])
    disconnected = layers.get(999, [])

    for ring_idx, dist in enumerate(sorted_dists, 1):
        ring_nodes = list(layers[dist])
        if dist == sorted_dists[-1] and disconnected:
            ring_nodes.extend(disconnected)
            disconnected = []
        n = len(ring_nodes)
        if n > 0:
            radius = 200 + (ring_idx - 1) * 180
            for i, nid in enumerate(ring_nodes):
                angle = i * (2 * math.pi / n) - math.pi / 2
                pos[nid] = (
                    center_x + radius * math.cos(angle),
                    center_y + radius * math.sin(angle),
                )

    if disconnected:
        outer_radius = 200 + len(sorted_dists) * 180
        n = len(disconnected)
        for i, nid in enumerate(disconnected):
            angle = i * (2 * math.pi / n) - math.pi / 2
            pos[nid] = (
                center_x + outer_radius * math.cos(angle),
                center_y + outer_radius * math.sin(angle),
            )

    return pos


def _apply_shape_geometry(
    shapes: dict, pos: dict, hub_id: str, elements: list[dict]
) -> None:
    """Update shape bounds, styles, and synced text elements."""
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

        if sid == hub_id:
            shape["strokeWidth"] = 3
            if shape.get("type") == "rectangle":
                shape["roundness"] = {"type": 3}

        sync_bound_text_translation(shape, elements, new_x - old_x, new_y - old_y)


def _apply_arrow_geometry(edges: list, shapes: dict) -> None:
    """Update arrow paths with straight ray trimming."""
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


def apply_concentric_layout(elements: list[dict]) -> bool:
    """Applies Concentric Ring Layout to Excalidraw elements.
    Mutates elements in place. Returns True if successfully applied.
    """
    shapes, edges, G = _extract_shapes_and_edges(elements)
    if not shapes or not G.nodes:
        return False

    degrees = dict(G.degree())
    if not degrees:
        return False
    hub_id = max(degrees, key=degrees.get)

    pos = _compute_concentric_positions(G, hub_id)
    _apply_shape_geometry(shapes, pos, hub_id, elements)
    _apply_arrow_geometry(edges, shapes)
    return True
