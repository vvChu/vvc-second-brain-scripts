import math
import uuid
import networkx as nx
from core.config import cfg
from services.diagram_base import (
    compute_safe_arrow_endpoints,
    sync_bound_text_translation,
)

def _node_has_margin_keyword(shape: dict, elements: list[dict]) -> bool:
    """Check if a shape or its bound text contains margin-related keywords."""
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
    combined = " ".join(texts).lower()
    keywords = ["margin", "profit", "biên lợi nhuận"]
    return any(kw in combined for kw in keywords)

def _extract_shapes_and_edges(
    elements: list[dict],
) -> tuple[dict[str, dict], list[dict], nx.DiGraph, list[tuple[dict, str, str]]]:
    """Extract shapes, arrows, and build networkx DiGraph for value chain layout."""
    shapes = {}
    arrows = []
    for el in elements:
        t = el.get("type")
        if t in ("rectangle", "ellipse", "diamond"):
            shapes[el["id"]] = el
        elif t == "arrow":
            arrows.append(el)

    G = nx.DiGraph()
    for sid in shapes:
        G.add_node(sid)

    edges = []
    for arr in arrows:
        sb = arr.get("startBinding", {})
        eb = arr.get("endBinding", {})
        start_id = sb.get("elementId") if isinstance(sb, dict) else (sb if isinstance(sb, str) else None)
        end_id = eb.get("elementId") if isinstance(eb, dict) else (eb if isinstance(eb, str) else None)
        if start_id in shapes and end_id in shapes:
            G.add_edge(start_id, end_id)
            edges.append((arr, start_id, end_id))
    return shapes, arrows, G, edges

def _resolve_chains_and_margin(
    G: nx.DiGraph, shapes: dict[str, dict], elements: list[dict]
) -> tuple[list[str], list[str], str | None]:
    """Identify primary chain, support activities, and optional margin node."""
    try:
        if nx.is_directed_acyclic_graph(G):
            primary_chain = nx.dag_longest_path(G)
        else:
            primary_chain = list(nx.topological_sort(G))
    except Exception:
        degrees = dict(G.out_degree())
        primary_chain = sorted(degrees, key=degrees.get, reverse=True)

    support_activities = [n for n in G.nodes if n not in primary_chain]
    margin_id = None
    if primary_chain and G.out_degree(primary_chain[-1]) == 0 and len(primary_chain) > 1:
        candidate = primary_chain[-1]
        if len(primary_chain) >= 3 and _node_has_margin_keyword(shapes[candidate], elements):
            margin_id = candidate
            primary_chain = primary_chain[:-1]
    return primary_chain, support_activities, margin_id

def _compute_positions(
    primary_chain: list[str], support_activities: list[str], margin_id: str | None
) -> dict[str, tuple[float, float]]:
    """Compute (cx, cy) target coordinates for each node in the value chain."""
    pos: dict[str, tuple[float, float]] = {}
    start_x, primary_y, support_y, step_x = 150.0, 520.0, 300.0, 220.0
    for idx, nid in enumerate(primary_chain):
        pos[nid] = (start_x + idx * step_x, primary_y)

    n_support = len(support_activities)
    if n_support > 0:
        max_primary_x = start_x + max(0, len(primary_chain) - 1) * step_x
        span_width = max_primary_x - start_x
        if n_support == 1:
            pos[support_activities[0]] = (start_x + span_width / 2.0, support_y)
        else:
            support_step = span_width / (n_support - 1) if n_support > 1 else step_x
            for idx, nid in enumerate(support_activities):
                pos[nid] = (start_x + idx * support_step, support_y)

    if margin_id:
        last_primary_x = start_x + len(primary_chain) * step_x
        pos[margin_id] = (last_primary_x + 50.0, primary_y)
    return pos

def _apply_shape_styling(
    shape: dict, sid: str, primary_chain: list[str], support_activities: list[str]
) -> None:
    """Apply styling attributes to a shape node based on its chain role."""
    shape["roughness"] = 0
    shape["backgroundColor"] = cfg.excalidraw_background_color
    shape["strokeColor"] = cfg.excalidraw_stroke_color
    shape["strokeWidth"] = cfg.excalidraw_stroke_width
    shape["fillStyle"] = "solid"
    if sid in primary_chain:
        shape["strokeWidth"] = 2
        if shape.get("type") == "rectangle" and "roundness" not in shape:
            shape["roundness"] = {"type": 3}
    elif sid in support_activities:
        shape["strokeWidth"] = 1.5
        shape["strokeStyle"] = "dashed"

def _apply_shape_geometry(
    shapes: dict[str, dict],
    elements: list[dict],
    pos: dict[str, tuple[float, float]],
    primary_chain: list[str],
    support_activities: list[str],
    margin_id: str | None,
) -> None:
    """Position shapes, apply diamond styling for margin, and sync text offsets."""
    for sid, (cx, cy) in pos.items():
        shape = shapes[sid]
        old_x, old_y = shape.get("x", 0), shape.get("y", 0)
        shape_w, shape_h = shape.get("width", 150), shape.get("height", 100)
        if sid == margin_id:
            shape["type"] = "diamond"
            shape_w = max(shape_w, 120)
            shape_h = max(shape_h, 120)
            shape["width"], shape["height"] = shape_w, shape_h

        new_x, new_y = cx - shape_w / 2.0, cy - shape_h / 2.0
        shape["x"], shape["y"] = float(new_x), float(new_y)
        _apply_shape_styling(shape, sid, primary_chain, support_activities)
        sync_bound_text_translation(shape, elements, new_x - old_x, new_y - old_y)

def _apply_arrow_geometry(
    edges: list[tuple[dict, str, str]],
    shapes: dict[str, dict],
    primary_chain: list[str],
    support_activities: list[str],
) -> None:
    """Route connecting arrows between primary and support activities."""
    for arr, sid, eid in edges:
        s_shape, e_shape = shapes[sid], shapes[eid]
        s_h = s_shape.get("height", 100)
        sx = float(s_shape["x"] + s_shape.get("width", 150) / 2)
        if sid in support_activities and eid in primary_chain:
            gap = float(e_shape["y"] - (s_shape["y"] + s_h))
            pad = min(5.0, (gap - 2.0) / 2.0) if gap > 12.0 else 0.0
            start_y, end_y = float(s_shape["y"] + s_h + pad), float(e_shape["y"] - pad)
            arr["x"], arr["y"] = sx, start_y
            arr["points"] = [[0.0, 0.0], [0.0, float(end_y - start_y)]]
            arr["strokeStyle"] = "dashed"
        else:
            start_x, start_y, end_x, end_y = compute_safe_arrow_endpoints(s_shape, e_shape)
            arr["x"], arr["y"] = start_x, start_y
            arr["points"] = [[0.0, 0.0], [float(end_x - start_x), float(end_y - start_y)]]
            arr["strokeStyle"] = "solid"
        arr["roughness"] = 0
        arr["strokeColor"] = cfg.excalidraw_stroke_color
        arr["strokeWidth"] = cfg.excalidraw_stroke_width

def apply_value_chain_layout(elements: list[dict]) -> bool:
    """Applies Michael Porter's Value Chain Layout to Excalidraw elements.
    Mutates elements in place. Returns True if successfully applied.
    """
    shapes, arrows, G, edges = _extract_shapes_and_edges(elements)
    if not shapes or not G.nodes:
        return False

    primary_chain, support_activities, margin_id = _resolve_chains_and_margin(G, shapes, elements)
    pos = _compute_positions(primary_chain, support_activities, margin_id)
    _apply_shape_geometry(shapes, elements, pos, primary_chain, support_activities, margin_id)
    _apply_arrow_geometry(edges, shapes, primary_chain, support_activities)
    return True
