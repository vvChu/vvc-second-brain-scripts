import json
from grandalf.graphs import Graph, Vertex, Edge
from grandalf.layouts import SugiyamaLayout
from core.config import cfg

class View(object):
    pass


def heuristic_bind_arrows(shapes, arrows):
    import math
    def dist(p1, p2):
        return math.hypot(p1[0]-p2[0], p1[1]-p2[1])
        
    def center(shape):
        return (shape.get('x',0) + shape.get('width',100)/2, 
                shape.get('y',0) + shape.get('height',100)/2)
                
    shape_centers = {sid: center(s) for sid, s in shapes.items()}
    
    for arr in arrows:
        pts = arr.get('points', [[0,0],[100,100]])
        if not pts: continue
        
        ax, ay = arr.get('x', 0), arr.get('y', 0)
        start_pt = (ax + pts[0][0], ay + pts[0][1])
        end_pt = (ax + pts[-1][0], ay + pts[-1][1])
        
        sb = arr.get('startBinding')
        eb = arr.get('endBinding')
        
        start_id = sb.get('elementId') if isinstance(sb, dict) else (sb if isinstance(sb, str) else None)
        end_id = eb.get('elementId') if isinstance(eb, dict) else (eb if isinstance(eb, str) else None)
        
        if not start_id or start_id not in shapes:
            # find closest to start_pt
            closest = min(shape_centers.keys(), key=lambda sid: dist(start_pt, shape_centers[sid]))
            arr['startBinding'] = {'elementId': closest, 'focus': 0, 'gap': 15}
            
        if not end_id or end_id not in shapes:
            # find closest to end_pt
            closest = min(shape_centers.keys(), key=lambda sid: dist(end_pt, shape_centers[sid]))
            arr['endBinding'] = {'elementId': closest, 'focus': 0, 'gap': 15}


def apply_sugiyama_layout(elements: list[dict]) -> bool:
    """
    Applies Sugiyama Hierarchical Layout to the given Excalidraw elements.
    Mutates the elements list in place. Returns True if layout was applied.
    """
    shapes = {}
    arrows = []
    
    # 1. Identify shapes and arrows
    for el in elements:
        t = el.get("type")
        if t in ("rectangle", "ellipse", "diamond"):
            shapes[el["id"]] = el
        elif t == "arrow":
            arrows.append(el)
            
    if not shapes:
        return False
        
    heuristic_bind_arrows(shapes, arrows)
    vertices = []
    vertex_map = {}
    
    for sid, shape in shapes.items():
        v = Vertex(sid)
        v.view = View()
        v.view.w = shape.get("width", 150)
        v.view.h = shape.get("height", 100)
        vertices.append(v)
        vertex_map[sid] = v
        
    edges = []
    for arr in arrows:
        sb = arr.get("startBinding")
        eb = arr.get("endBinding")
        
        start_id = sb.get("elementId") if isinstance(sb, dict) else (sb if isinstance(sb, str) else None)
        end_id = eb.get("elementId") if isinstance(eb, dict) else (eb if isinstance(eb, str) else None)
        
        if start_id in shapes and end_id in shapes:
            e = Edge(vertex_map[start_id], vertex_map[end_id])
            edges.append(e)
            
            # Ensure proper bindings in Excalidraw JSON
            if not isinstance(sb, dict):
                arr["startBinding"] = {"elementId": start_id, "focus": 0, "gap": 15}
            if not isinstance(eb, dict):
                arr["endBinding"] = {"elementId": end_id, "focus": 0, "gap": 15}
                
    g = Graph(vertices, edges)
    
    # Run Sugiyama for each connected component
    current_y_offset = 100
    for c in g.C:
        sug = SugiyamaLayout(c)
        sug.init_all()
        # You can configure spacing here
        sug.xspace = 80
        sug.yspace = 80
        sug.draw()
        
        # Ensure all vertices have an 'xy' attribute (fallback for isolated nodes)
        for v in c.sV:
            if not hasattr(v.view, 'xy'):
                v.view.xy = (0.0, 0.0)
                
        # Find the bounding box of this component to shift it properly
        min_x = min(v.view.xy[0] - v.view.w/2 for v in c.sV)
        min_y = min(v.view.xy[1] - v.view.h/2 for v in c.sV)
        max_y = max(v.view.xy[1] + v.view.h/2 for v in c.sV)
        
        # Shift all vertices in this component
        for v in c.sV:
            # Shift X to start at 100
            shifted_cx = v.view.xy[0] - min_x + 100
            # Shift Y to start at current_y_offset
            shifted_cy = v.view.xy[1] - min_y + current_y_offset
            
            shape = shapes[v.data]
            old_x = shape.get("x", 0)
            old_y = shape.get("y", 0)
            
            new_x = shifted_cx - v.view.w / 2
            new_y = shifted_cy - v.view.h / 2
            
            dx = new_x - old_x
            dy = new_y - old_y
            
            shape["x"] = float(new_x)
            shape["y"] = float(new_y)
            shape["roughness"] = 0
            if shape.get("type") == "rectangle" and "roundness" not in shape:
                shape["roundness"] = {"type": 3}
            if "strokeColor" not in shape or shape["strokeColor"] == "#000000" or shape["strokeColor"] == "#0f172a":
                shape["strokeColor"] = cfg.excalidraw_stroke_color
            if "backgroundColor" not in shape or shape["backgroundColor"] == "transparent":
                shape["backgroundColor"] = cfg.excalidraw_background_color
            
            # Move bound text
            for bound in shape.get("boundElements", []):
                if isinstance(bound, dict) and bound.get("type") == "text":
                    tid = bound["id"]
                    for el in elements:
                        if el.get("id") == tid and el.get("type") == "text":
                            el["x"] = float(el.get("x", 0) + dx)
                            el["y"] = float(el.get("y", 0) + dy)
                            
        # Move offset for next component
        current_y_offset += (max_y - min_y) + 100
        
    # Update arrows geometrically with Orthogonal (Elbow) routing
    for arr in arrows:
        sb = arr.get("startBinding")
        eb = arr.get("endBinding")
        start_id = sb.get("elementId") if isinstance(sb, dict) else (sb if isinstance(sb, str) else None)
        end_id = eb.get("elementId") if isinstance(eb, dict) else (eb if isinstance(eb, str) else None)
        
        if start_id in shapes and end_id in shapes:
            s_shape = shapes[start_id]
            e_shape = shapes[end_id]
            
            # Since Sugiyama is Top-Down, arrows start at BOTTOM of source and end at TOP of target
            sx = float(s_shape["x"] + s_shape.get("width", 100) / 2)
            sy = float(s_shape["y"] + s_shape.get("height", 100) + 5) # +5px gap
            
            ex = float(e_shape["x"] + e_shape.get("width", 100) / 2)
            ey = float(e_shape["y"] - 5) # -5px gap
            
            arr["x"] = sx
            arr["y"] = sy
            
            dx = ex - sx
            dy = ey - sy
            
            # Elbow connector points
            mid_y = dy / 2
            arr["points"] = [
                [0.0, 0.0],
                [0.0, float(mid_y)],
                [float(dx), float(mid_y)],
                [float(dx), float(dy)]
            ]
            
            # Apply aesthetics to Arrow (Technical/Light Mode)
            arr["roughness"] = 0
            arr["strokeColor"] = "#0f172a" # slate-900 (Darker for Light Mode contrast)
            arr["roundness"] = {"type": 3} # Sharp elbows (type 3) or use 2 for curved elbows
            
    return True
