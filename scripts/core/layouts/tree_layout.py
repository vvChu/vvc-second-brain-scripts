import math
import networkx as nx
from core.config import cfg
from services.diagram_base import (
    compute_safe_arrow_endpoints,
    sync_bound_text_translation,
)

def apply_tree_layout(elements: list[dict], direction: str = "td") -> bool:
    """Applies a clean Hierarchical Tree Layout to Excalidraw elements.
    Mutates elements in place. Returns True if successfully applied.
    """
    shapes = {}
    arrows = []
    
    for el in elements:
        t = el.get("type")
        if t in ("rectangle", "ellipse", "diamond"):
            shapes[el["id"]] = el
        elif t == "arrow":
            arrows.append(el)
            
    if not shapes:
        return False
        
    # Build NetworkX DiGraph to analyze hierarchy
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
            
    if not G.nodes:
        return False
        
    # 1. Auto-detect Root Node
    # Root is a node with in-degree = 0. If multiple or none exist, pick the one with max degree
    roots = [n for n, d in G.in_degree() if d == 0]
    if len(roots) == 1:
        root_id = roots[0]
    elif len(roots) > 1:
        # Multiple roots, pick the one with maximum out-degree
        root_id = max(roots, key=G.out_degree)
    else:
        # Cycle or undirected, pick node with maximum degree
        degrees = dict(G.degree())
        root_id = max(degrees, key=degrees.get) if degrees else list(G.nodes)[0]

    # 2. Build a strict Spanning Tree using BFS from the Root
    # This prevents infinite loops if there are cycle relationships
    tree_edges = list(nx.bfs_edges(G, root_id))
    T = nx.DiGraph()
    T.add_node(root_id)
    T.add_edges_from(tree_edges)
    
    # Ensure all isolated nodes are also added to the tree under root
    for n in G.nodes:
        if n not in T:
            T.add_node(n)
            T.add_edge(root_id, n)

    # 3. Calculate tree structure properties (Depth and Leaf counts)
    depths = nx.single_source_shortest_path_length(T, root_id)
    
    # Compute leaf count for each node (used to distribute spacing proportionally)
    leaf_counts = {}
    def compute_leaves(node):
        children = list(T.successors(node))
        if not children:
            leaf_counts[node] = 1
            return 1
        count = sum(compute_leaves(c) for c in children)
        leaf_counts[node] = count
        return count
        
    compute_leaves(root_id)

    # 4. Position calculation using a leaf-based proportional distribution
    pos = {}
    current_leaf_index = 0
    leaf_spacing = 180.0
    level_spacing = 180.0
    
    start_x, start_y = 600.0, 100.0
    
    def layout_node(node):
        nonlocal current_leaf_index
        children = list(T.successors(node))
        depth = depths[node]
        
        if not children:
            # It's a leaf node. Position it at the next leaf index
            coord = current_leaf_index * leaf_spacing
            current_leaf_index += 1
            if direction == "td":
                pos[node] = (coord, start_y + depth * level_spacing)
            else: # lr
                pos[node] = (start_x + depth * level_spacing, coord)
        else:
            # Layout all children first
            for c in children:
                layout_node(c)
                
            # Parent is placed at the average coordinate of its children
            child_coords = [pos[c][0] if direction == "td" else pos[c][1] for c in children]
            avg_coord = sum(child_coords) / len(child_coords)
            
            if direction == "td":
                pos[node] = (avg_coord, start_y + depth * level_spacing)
            else: # lr
                pos[node] = (start_x + depth * level_spacing, avg_coord)
                
    layout_node(root_id)
    
    # Shift coordinate system so it fits nicely on the canvas
    all_x = [p[0] for p in pos.values()]
    all_y = [p[1] for p in pos.values()]
    
    min_x = min(all_x) if all_x else 0
    min_y = min(all_y) if all_y else 0
    
    target_start_x = 100.0 if direction == "td" else 150.0
    target_start_y = 100.0
    
    shift_x = target_start_x - min_x
    shift_y = target_start_y - min_y
    
    for nid in pos:
        pos[nid] = (pos[nid][0] + shift_x, pos[nid][1] + shift_y)

    # 5. Apply shape coordinate mutations and Academic aesthetics
    for sid, (cx, cy) in pos.items():
        shape = shapes[sid]
        
        old_x = shape.get("x", 0)
        old_y = shape.get("y", 0)
        
        shape_w = shape.get("width", 150)
        shape_h = shape.get("height", 100)
        
        new_x = cx - shape_w / 2
        new_y = cy - shape_h / 2
        
        dx = new_x - old_x
        dy = new_y - old_y
        
        shape["x"] = float(new_x)
        shape["y"] = float(new_y)
        
        # Apply Academic Aesthetics
        shape["roughness"] = 0
        shape["backgroundColor"] = cfg.excalidraw_background_color
        shape["strokeColor"] = cfg.excalidraw_stroke_color
        shape["strokeWidth"] = cfg.excalidraw_stroke_width
        shape["fillStyle"] = "solid"
        
        if sid == root_id:
            shape["strokeWidth"] = 3
            if shape.get("type") == "rectangle" and "roundness" not in shape:
                shape["roundness"] = {"type": 3} # rounded box for root
        else:
            if shape.get("type") == "rectangle" and "roundness" not in shape:
                shape["roundness"] = {"type": 3}
                
        sync_bound_text_translation(shape, elements, dx, dy)

    # 6. Apply Orthogonal (Elbow) Connectors to Spanning Tree arrows
    for arr, sid, eid in edges:
        # Check if this edge belongs to our BFS spanning tree
        is_tree_edge = T.has_edge(sid, eid)
        
        s_shape = shapes[sid]
        e_shape = shapes[eid]
        
        s_w = s_shape.get("width", 150)
        s_h = s_shape.get("height", 100)
        e_w = e_shape.get("width", 150)
        e_h = e_shape.get("height", 100)
        
        if is_tree_edge:
            if direction == "td":
                # Start at bottom of parent, end at top of child
                start_x = float(s_shape["x"] + s_w / 2)
                start_y = float(s_shape["y"] + s_h + 5)
                end_x = float(e_shape["x"] + e_w / 2)
                end_y = float(e_shape["y"] - 5)
                
                arr["x"] = start_x
                arr["y"] = start_y
                
                dx = end_x - start_x
                dy = end_y - start_y
                
                # Orthogonal Elbow points (down -> across -> down)
                mid_y = dy / 2
                arr["points"] = [
                    [0.0, 0.0],
                    [0.0, float(mid_y)],
                    [float(dx), float(mid_y)],
                    [float(dx), float(dy)]
                ]
            else: # direction == "lr"
                # Start at right of parent, end at left of child
                start_x = float(s_shape["x"] + s_w + 5)
                start_y = float(s_shape["y"] + s_h / 2)
                end_x = float(e_shape["x"] - 5)
                end_y = float(e_shape["y"] + e_h / 2)
                
                arr["x"] = start_x
                arr["y"] = start_y
                
                dx = end_x - start_x
                dy = end_y - start_y
                
                # Orthogonal Elbow points (across -> down -> across)
                mid_x = dx / 2
                arr["points"] = [
                    [0.0, 0.0],
                    [float(mid_x), 0.0],
                    [float(mid_x), float(dy)],
                    [float(dx), float(dy)]
                ]
                
            arr["roundness"] = {"type": 3} # sharp elbows
        else:
            # Non-tree relation edge: use dashed ray-trimmed straight line
            start_x, start_y, end_x, end_y = compute_safe_arrow_endpoints(s_shape, e_shape)
                
            arr["x"] = start_x
            arr["y"] = start_y
            arr["points"] = [[0.0, 0.0], [float(end_x - start_x), float(end_y - start_y)]]
            arr["strokeStyle"] = "dashed"
            
        # Apply Arrow Aesthetics
        arr["roughness"] = 0
        arr["strokeColor"] = cfg.excalidraw_stroke_color
        arr["strokeWidth"] = cfg.excalidraw_stroke_width
        
    return True
