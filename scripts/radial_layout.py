import math
import networkx as nx
from core.config import cfg

def apply_radial_layout(elements: list[dict]) -> bool:
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
            
    # Find the hub (node with highest degree)
    if not G.nodes:
        return False
        
    degrees = dict(G.degree())
    hub_id = max(degrees, key=degrees.get)
    
    # Calculate positions
    pos = {}
    center_x, center_y = 600, 400
    pos[hub_id] = (center_x, center_y)
    
    other_nodes = [n for n in G.nodes if n != hub_id]
    n = len(other_nodes)
    if n > 0:
        # Dynamic radius based on number of nodes to avoid overlapping
        radius = max(300, n * 50)
        angle_step = 2 * math.pi / n
        for i, nid in enumerate(other_nodes):
            angle = i * angle_step - math.pi / 2 # Start at 12 o'clock
            pos[nid] = (
                center_x + radius * math.cos(angle),
                center_y + radius * math.sin(angle)
            )
            
    # 1. Update shape positions and Academic Grayscale Aesthetics
    for sid, (x, y) in pos.items():
        shape = shapes[sid]
        
        old_x = shape.get("x", 0)
        old_y = shape.get("y", 0)
        
        # Center the shape on the calculated pos
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
        
        # Hub node gets special treatment (e.g. bold or solid fill)
        if sid == hub_id:
            shape["strokeWidth"] = 3
        
        # Maintain shape if specified by LLM, otherwise default to ellipse for Radial
        if "shape" not in shape and shape.get("type") == "rectangle":
            # For radial, ellipses usually look better for the outer nodes
            pass
            
        # Move bound text
        for bound in shape.get("boundElements", []):
            if isinstance(bound, dict) and bound.get("type") == "text":
                tid = bound["id"]
                for el in elements:
                    if el.get("id") == tid and el.get("type") == "text":
                        el["x"] = float(el.get("x", 0) + dx)
                        el["y"] = float(el.get("y", 0) + dy)
                        el["strokeColor"] = cfg.excalidraw_stroke_color
                        el["fontFamily"] = cfg.excalidraw_font_family
                        
    # 2. Update arrows geometrically with center-to-center ray trimming (Straight Lines)
    for arr, sid, eid in edges:
        s_shape = shapes[sid]
        e_shape = shapes[eid]
        
        s_w = s_shape.get("width", 150)
        s_h = s_shape.get("height", 100)
        e_w = e_shape.get("width", 150)
        e_h = e_shape.get("height", 100)
        
        sx = float(s_shape["x"] + s_w / 2)
        sy = float(s_shape["y"] + s_h / 2)
        ex = float(e_shape["x"] + e_w / 2)
        ey = float(e_shape["y"] + e_h / 2)
        
        dx = ex - sx
        dy = ey - sy
        dist = math.hypot(dx, dy)
        if dist > 0:
            s_rad = min(s_w, s_h) / 2 + 5
            e_rad = min(e_w, e_h) / 2 + 5
            
            start_x = sx + (dx / dist) * s_rad
            start_y = sy + (dy / dist) * s_rad
            end_x = ex - (dx / dist) * e_rad
            end_y = ey - (dy / dist) * e_rad
        else:
            start_x, start_y, end_x, end_y = sx, sy, ex, ey
            
        arr["x"] = start_x
        arr["y"] = start_y
        arr["points"] = [[0.0, 0.0], [float(end_x - start_x), float(end_y - start_y)]]
        
        # Arrow Academic Aesthetics
        arr["roughness"] = 0
        arr["strokeColor"] = cfg.excalidraw_stroke_color
        arr["strokeWidth"] = cfg.excalidraw_stroke_width
        # Preserve dashed if specified, else solid
        if arr.get("strokeStyle") != "dashed":
            arr["strokeStyle"] = "solid"
            
    return True
