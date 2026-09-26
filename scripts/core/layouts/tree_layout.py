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


def _find_tree_root(G: nx.DiGraph) -> str:
    """Auto-detect tree root by in-degree=0, max out-degree, or max total degree."""
    roots = [n for n, d in G.in_degree() if d == 0]
    if len(roots) == 1:
        return roots[0]
    if len(roots) > 1:
        return max(roots, key=G.out_degree)
    degrees = dict(G.degree())
    return max(degrees, key=degrees.get) if degrees else list(G.nodes)[0]


def _build_spanning_tree(G: nx.DiGraph, root_id: str) -> nx.DiGraph:
    """Build a strict spanning tree using BFS to eliminate cycles and attach orphans."""
    tree_edges = list(nx.bfs_edges(G, root_id))
    T = nx.DiGraph()
    T.add_node(root_id)
    T.add_edges_from(tree_edges)
    for n in G.nodes:
        if n not in T:
            T.add_node(n)
            T.add_edge(root_id, n)
    return T


def _compute_tree_positions(
    T: nx.DiGraph, root_id: str, direction: str
) -> dict[str, tuple[float, float]]:
    """Compute leaf-proportional positions and normalize to canvas offset."""
    depths = nx.single_source_shortest_path_length(T, root_id)
    pos: dict[str, tuple[float, float]] = {}
    current_leaf_index = 0
    leaf_spacing = 180.0
    level_spacing = 180.0
    start_x, start_y = 600.0, 100.0

    def layout_node(node: str) -> None:
        nonlocal current_leaf_index
        children = list(T.successors(node))
        depth = depths[node]
        if not children:
            coord = current_leaf_index * leaf_spacing
            current_leaf_index += 1
            pos[node] = (
                (coord, start_y + depth * level_spacing)
                if direction == "td"
                else (start_x + depth * level_spacing, coord)
            )
        else:
            for c in children:
                layout_node(c)
            child_coords = [
                pos[c][0] if direction == "td" else pos[c][1] for c in children
            ]
            avg_coord = sum(child_coords) / len(child_coords)
            pos[node] = (
                (avg_coord, start_y + depth * level_spacing)
                if direction == "td"
                else (start_x + depth * level_spacing, avg_coord)
            )

    layout_node(root_id)

    all_x = [p[0] for p in pos.values()]
    all_y = [p[1] for p in pos.values()]
    min_x = min(all_x) if all_x else 0.0
    min_y = min(all_y) if all_y else 0.0
    shift_x = (100.0 if direction == "td" else 150.0) - min_x
    shift_y = 100.0 - min_y

    return {nid: (p[0] + shift_x, p[1] + shift_y) for nid, p in pos.items()}


def _apply_tree_shapes(
    shapes: dict[str, dict],
    pos: dict[str, tuple[float, float]],
    root_id: str,
    elements: list[dict],
) -> None:
    """Update shape positions, border radius, and grayscale styling."""
    for sid, (cx, cy) in pos.items():
        shape = shapes[sid]
        old_x, old_y = shape.get("x", 0), shape.get("y", 0)
        sw, sh = shape.get("width", 150), shape.get("height", 100)
        new_x, new_y = cx - sw / 2, cy - sh / 2

        shape["x"] = float(new_x)
        shape["y"] = float(new_y)
        shape["roughness"] = 0
        shape["backgroundColor"] = cfg.excalidraw_background_color
        shape["strokeColor"] = cfg.excalidraw_stroke_color
        shape["strokeWidth"] = 3 if sid == root_id else cfg.excalidraw_stroke_width
        shape["fillStyle"] = "solid"
        if shape.get("type") == "rectangle" and "roundness" not in shape:
            shape["roundness"] = {"type": 3}

        sync_bound_text_translation(shape, elements, new_x - old_x, new_y - old_y)


def _apply_tree_arrows(
    edges: list[tuple[dict, str, str]],
    shapes: dict[str, dict],
    T: nx.DiGraph,
    direction: str,
) -> None:
    """Apply orthogonal elbow connectors for tree edges and dashed rays for cross edges."""
    for arr, sid, eid in edges:
        s_shape, e_shape = shapes[sid], shapes[eid]
        sw, sh = s_shape.get("width", 150), s_shape.get("height", 100)
        ew, eh = e_shape.get("width", 150), e_shape.get("height", 100)

        if T.has_edge(sid, eid):
            if direction == "td":
                sx, sy = float(s_shape["x"] + sw / 2), float(s_shape["y"] + sh + 5)
                ex, ey = float(e_shape["x"] + ew / 2), float(e_shape["y"] - 5)
                dx, dy = ex - sx, ey - sy
                mid_y = dy / 2
                arr["points"] = [
                    [0.0, 0.0],
                    [0.0, float(mid_y)],
                    [float(dx), float(mid_y)],
                    [float(dx), float(dy)],
                ]
            else:
                sx, sy = float(s_shape["x"] + sw + 5), float(s_shape["y"] + sh / 2)
                ex, ey = float(e_shape["x"] - 5), float(e_shape["y"] + eh / 2)
                dx, dy = ex - sx, ey - sy
                mid_x = dx / 2
                arr["points"] = [
                    [0.0, 0.0],
                    [float(mid_x), 0.0],
                    [float(mid_x), float(dy)],
                    [float(dx), float(dy)],
                ]
            arr["x"] = sx
            arr["y"] = sy
            arr["roundness"] = {"type": 3}
        else:
            sx, sy, ex, ey = compute_safe_arrow_endpoints(s_shape, e_shape)
            arr["x"] = sx
            arr["y"] = sy
            arr["points"] = [[0.0, 0.0], [float(ex - sx), float(ey - sy)]]
            arr["strokeStyle"] = "dashed"

        arr["roughness"] = 0
        arr["strokeColor"] = cfg.excalidraw_stroke_color
        arr["strokeWidth"] = cfg.excalidraw_stroke_width


def apply_tree_layout(elements: list[dict], direction: str = "td") -> bool:
    """Applies a clean Hierarchical Tree Layout to Excalidraw elements.
    Mutates elements in place. Returns True if successfully applied.
    """
    shapes, edges, G = _extract_shapes_and_edges(elements)
    if not shapes or not G.nodes:
        return False

    root_id = _find_tree_root(G)
    T = _build_spanning_tree(G, root_id)
    pos = _compute_tree_positions(T, root_id, direction)

    _apply_tree_shapes(shapes, pos, root_id, elements)
    _apply_tree_arrows(edges, shapes, T, direction)
    return True
