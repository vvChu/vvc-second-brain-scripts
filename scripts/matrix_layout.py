import math
import uuid
from core.config import cfg

def apply_matrix_layout(elements: list[dict], style="cross") -> bool:
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
        
    # Find bounding box of all shapes
    min_x = min([s.get("x", 0) for s in shapes.values()]) if shapes else 0
    max_x = max([s.get("x", 0) + s.get("width", 150) for s in shapes.values()]) if shapes else 1000
    min_y = min([s.get("y", 0) for s in shapes.values()]) if shapes else 0
    max_y = max([s.get("y", 0) + s.get("height", 100) for s in shapes.values()]) if shapes else 1000
    
    # Expand slightly
    pad = 100
    min_x -= pad
    max_x += pad
    min_y -= pad
    max_y += pad
    
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2
    
    background_elements = []
    
    if style == "cross":
        # Draw a crosshair (2x2 grid)
        # Vertical line
        v_line = {
            "id": f"matrix_v_{uuid.uuid4().hex[:8]}",
            "type": "arrow",
            "x": cx,
            "y": min_y,
            "width": 0,
            "height": max_y - min_y,
            "strokeColor": "#a8a29e",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 0,
            "points": [[0, 0], [0, float(max_y - min_y)]],
            "startArrowhead": None,
            "endArrowhead": None
        }
        # Horizontal line
        h_line = {
            "id": f"matrix_h_{uuid.uuid4().hex[:8]}",
            "type": "arrow",
            "x": min_x,
            "y": cy,
            "width": max_x - min_x,
            "height": 0,
            "strokeColor": "#a8a29e",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 0,
            "points": [[0, 0], [float(max_x - min_x), 0]],
            "startArrowhead": None,
            "endArrowhead": None
        }
        background_elements.extend([v_line, h_line])
        
    elif style == "axis":
        # Draw X and Y axes
        # Y axis (left side)
        y_axis = {
            "id": f"axis_y_{uuid.uuid4().hex[:8]}",
            "type": "arrow",
            "x": min_x + 50,
            "y": max_y - 50,
            "width": 0,
            "height": max_y - min_y,
            "strokeColor": cfg.excalidraw_stroke_color,
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 0,
            "points": [[0, 0], [0, float(-(max_y - min_y))]],
            "startArrowhead": None,
            "endArrowhead": "arrow"
        }
        # X axis (bottom side)
        x_axis = {
            "id": f"axis_x_{uuid.uuid4().hex[:8]}",
            "type": "arrow",
            "x": min_x + 50,
            "y": max_y - 50,
            "width": max_x - min_x,
            "height": 0,
            "strokeColor": cfg.excalidraw_stroke_color,
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 0,
            "points": [[0, 0], [float(max_x - min_x), 0]],
            "startArrowhead": None,
            "endArrowhead": "arrow"
        }
        background_elements.extend([y_axis, x_axis])

    # Prepend background so it's drawn behind nodes
    # We will modify elements in place, so we insert at the beginning
    elements[0:0] = background_elements

    # Apply Academic Grayscale Aesthetics to nodes
    for s_id, shape in shapes.items():
        shape["roughness"] = 0
        shape["backgroundColor"] = cfg.excalidraw_background_color
        shape["strokeColor"] = cfg.excalidraw_stroke_color
        shape["strokeWidth"] = cfg.excalidraw_stroke_width
        
        # Matrix/Scatter plots often use Diamond or Circle shapes in books
        if "shape" not in shape and shape.get("type") == "rectangle":
            # Just keep as is
            pass
            
        for bound in shape.get("boundElements", []):
            if isinstance(bound, dict) and bound.get("type") == "text":
                tid = bound["id"]
                for el in elements:
                    if el.get("id") == tid and el.get("type") == "text":
                        el["strokeColor"] = cfg.excalidraw_stroke_color
                        el["fontFamily"] = cfg.excalidraw_font_family
                        
    # Update arrows (if any exist in matrix)
    for arr in arrows:
        arr["roughness"] = 0
        arr["strokeColor"] = cfg.excalidraw_stroke_color
        if arr.get("strokeStyle") != "dashed":
            arr["strokeStyle"] = "solid"

    return True
