import math
import networkx as nx
from core.config import cfg
from services.diagram_base import (
    compute_safe_arrow_endpoints,
    sync_bound_text_translation,
)

def apply_concentric_layout(elements: list[dict]) -> bool:
    """Applies Concentric Ring Layout to Excalidraw elements.
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
        
    # Build NetworkX Graph for shortest path distance calculation
    G = nx.Graph()
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
        
    # Identify Hub node (node with highest degree) as the center
    degrees = dict(G.degree())
    if not degrees:
        return False
    hub_id = max(degrees, key=degrees.get)
    
    # Calculate shortest path length from hub to all other nodes (BFS distance)
    lengths = nx.single_source_shortest_path_length(G, hub_id)
    
    # Group nodes by distance (layers)
    layers = {}
    for nid in G.nodes:
        dist = lengths.get(nid, 999) # fallback for disconnected components
        if dist not in layers:
            layers[dist] = []
        layers[dist].append(nid)
        
    # Layout positions dict
    pos = {}
    center_x, center_y = 600, 400
    pos[hub_id] = (center_x, center_y)
    
    # Distribute nodes along concentric rings
    sorted_dists = sorted([d for d in layers.keys() if d != 999 and d > 0])
    
    # Add disconnected nodes to the outermost ring
    disconnected_nodes = layers.get(999, [])
    
    for ring_idx, dist in enumerate(sorted_dists, 1):
        ring_nodes = layers[dist]
        if dist == sorted_dists[-1] and disconnected_nodes:
            ring_nodes.extend(disconnected_nodes)
            disconnected_nodes = []
            
        n = len(ring_nodes)
        if n > 0:
            # Circle radius increases with each ring layer
            radius = 200 + (ring_idx - 1) * 180
            angle_step = 2 * math.pi / n
            for i, nid in enumerate(ring_nodes):
                angle = i * angle_step - math.pi / 2 # Start at 12 o'clock
                pos[nid] = (
                    center_x + radius * math.cos(angle),
                    center_y + radius * math.sin(angle)
                )
                
    # Place remaining disconnected nodes if any
    if disconnected_nodes:
        outer_radius = 200 + len(sorted_dists) * 180
        n = len(disconnected_nodes)
        angle_step = 2 * math.pi / n
        for i, nid in enumerate(disconnected_nodes):
            angle = i * angle_step - math.pi / 2
            pos[nid] = (
                center_x + outer_radius * math.cos(angle),
                center_y + outer_radius * math.sin(angle)
            )

    # 1. Update shape positions and apply Academic Grayscale Theme
    for sid, (x, y) in pos.items():
        shape = shapes[sid]
        
        old_x = shape.get("x", 0)
        old_y = shape.get("y", 0)
        
        shape_w = shape.get("width", 150)
        shape_h = shape.get("height", 100)
        
        new_x = x - shape_w / 2
        new_y = y - shape_h / 2
        
        dx = new_x - old_x
        dy = new_y - old_y
        
        shape["x"] = float(new_x)
        shape["y"] = float(new_y)
        
        # --- Academic Book Aesthetics ---
        shape["roughness"] = 0
        shape["backgroundColor"] = cfg.excalidraw_background_color
        shape["strokeColor"] = cfg.excalidraw_stroke_color
        shape["strokeWidth"] = cfg.excalidraw_stroke_width
        shape["fillStyle"] = "solid"
        
        # Highlight Core node
        if sid == hub_id:
            shape["strokeWidth"] = 3
            # Set to ellipse to stand out in the center
            if shape.get("type") == "rectangle":
                shape["roundness"] = {"type": 3}
        
        sync_bound_text_translation(shape, elements, dx, dy)

    # 2. Update arrows geometrically using center-to-center ray trimming (Straight Lines)
    for arr, sid, eid in edges:
        s_shape = shapes[sid]
        e_shape = shapes[eid]
        
        start_x, start_y, end_x, end_y = compute_safe_arrow_endpoints(s_shape, e_shape)
            
        arr["x"] = start_x
        arr["y"] = start_y
        arr["points"] = [[0.0, 0.0], [float(end_x - start_x), float(end_y - start_y)]]
        
        # Apply Grayscale Theme to Arrow
        arr["roughness"] = 0
        arr["strokeColor"] = cfg.excalidraw_stroke_color
        arr["strokeWidth"] = cfg.excalidraw_stroke_width
        if arr.get("strokeStyle") != "dashed":
            arr["strokeStyle"] = "solid"
            
    return True
