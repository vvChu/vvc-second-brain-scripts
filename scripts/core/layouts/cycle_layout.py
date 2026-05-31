import math
import networkx as nx
from core.config import cfg
from services.diagram_base import get_shape_boundary_point

def apply_cycle_layout(elements: list[dict]) -> bool:
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
        
    # Attempt to order nodes by cycle path (e.g. A->B->C->A)
    # Use simple topological sort if DAG, or cycle finding if cyclic
    try:
        cycles = list(nx.simple_cycles(G))
        if cycles:
            # Use the largest cycle for ordering
            ordered_nodes = max(cycles, key=len)
            # Add remaining nodes
            for n in G.nodes:
                if n not in ordered_nodes:
                    ordered_nodes.append(n)
        else:
            ordered_nodes = list(G.nodes)
    except Exception:
        ordered_nodes = list(G.nodes)
    
    # Calculate positions
    pos = {}
    center_x, center_y = 600, 400
    n = len(ordered_nodes)
    
    if n > 0:
        radius = max(250, n * 60)
        angle_step = 2 * math.pi / n
        for i, nid in enumerate(ordered_nodes):
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
        
        # Ellipse preferred for cycles
        if "shape" not in shape and shape.get("type") == "rectangle":
            # Just keeping what LLM said for now unless explicitly forcing ellipse
            pass
            
        for bound in shape.get("boundElements", []):
            if isinstance(bound, dict) and bound.get("type") == "text":
                tid = bound["id"]
                for el in elements:
                    if el.get("id") == tid and el.get("type") == "text":
                        el["x"] = float(el.get("x", 0) + dx)
                        el["y"] = float(el.get("y", 0) + dy)
                        el["strokeColor"] = cfg.excalidraw_stroke_color
                        el["fontFamily"] = cfg.excalidraw_font_family
                        
    # 2. Update arrows geometrically with curved path
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
        
        # Calculate mid point, pushed outwards slightly to form a curve
        mx = (sx + ex) / 2
        my = (sy + ey) / 2
        
        # Vector from center to mid point
        v_cx = mx - center_x
        v_cy = my - center_y
        v_dist = math.hypot(v_cx, v_cy)
        if v_dist > 0:
            push_amount = 50
            mx = mx + (v_cx / v_dist) * push_amount
            my = my + (v_cy / v_dist) * push_amount

        if dist > 0:
            # Exact boundary intersection (handles wide rectangles correctly)
            bsx, bsy = get_shape_boundary_point(s_shape, dx, dy)
            bex, bey = get_shape_boundary_point(e_shape, -dx, -dy)
            start_x = bsx + (dx / dist) * 5
            start_y = bsy + (dy / dist) * 5
            end_x = bex - (dx / dist) * 5
            end_y = bey - (dy / dist) * 5
        else:
            start_x, start_y, end_x, end_y = sx, sy, ex, ey
            
        arr["x"] = start_x
        arr["y"] = start_y
        
        arr["points"] = [
            [0.0, 0.0],
            [float(mx - start_x), float(my - start_y)],
            [float(end_x - start_x), float(end_y - start_y)]
        ]
        
        arr["roughness"] = 0
        arr["strokeColor"] = cfg.excalidraw_stroke_color
        arr["strokeWidth"] = cfg.excalidraw_stroke_width
        arr["roundness"] = {"type": 2} # Curved line
        if arr.get("strokeStyle") != "dashed":
            arr["strokeStyle"] = "solid"
            
    return True
