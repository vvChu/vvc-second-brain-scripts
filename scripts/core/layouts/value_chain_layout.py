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

def apply_value_chain_layout(elements: list[dict]) -> bool:
    """Applies Michael Porter's Value Chain Layout to Excalidraw elements.
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
        
    # Build Directed Graph (DiGraph) for dependency analysis
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

    # 1. Identify Primary Chain (Longest Path in DAG)
    primary_chain = []
    try:
        if nx.is_directed_acyclic_graph(G):
            # Find the longest path in DAG as the primary activity flow
            primary_chain = nx.dag_longest_path(G)
        else:
            # Fallback to topological sort or degree based chain
            primary_chain = list(nx.topological_sort(G))
    except Exception:
        # Emergency fallback: order by out-degree descending
        degrees = dict(G.out_degree())
        primary_chain = sorted(degrees, key=degrees.get, reverse=True)
        
    # 2. Support Activities (anything not in the primary chain)
    support_activities = [n for n in G.nodes if n not in primary_chain]
    
    # Margin node detection:
    # Only convert the last node to Margin if it explicitly contains margin keywords
    margin_id = None
    if primary_chain and G.out_degree(primary_chain[-1]) == 0 and len(primary_chain) > 1:
        candidate = primary_chain[-1]
        if len(primary_chain) >= 3 and _node_has_margin_keyword(shapes[candidate], elements):
            margin_id = candidate
            primary_chain = primary_chain[:-1]

    # Calculate coordinates
    pos = {}
    start_x = 150
    primary_y = 520
    support_y = 300
    step_x = 220
    
    # Position primary activities horizontally
    for idx, nid in enumerate(primary_chain):
        pos[nid] = (start_x + idx * step_x, primary_y)
        
    # Position support activities on the upper row
    n_support = len(support_activities)
    if n_support > 0:
        # Span support activities evenly above the primary chain
        max_primary_x = start_x + max(0, len(primary_chain) - 1) * step_x
        span_width = max_primary_x - start_x
        
        if n_support == 1:
            pos[support_activities[0]] = (start_x + span_width / 2, support_y)
        else:
            support_step = span_width / (n_support - 1) if n_support > 1 else step_x
            for idx, nid in enumerate(support_activities):
                pos[nid] = (start_x + idx * support_step, support_y)
                
    # Position Margin node at the far right
    if margin_id:
        last_primary_x = start_x + len(primary_chain) * step_x
        pos[margin_id] = (last_primary_x + 50, primary_y)

    # 3. Update shape coordinates and aesthetics
    for sid, (cx, cy) in pos.items():
        shape = shapes[sid]
        
        old_x = shape.get("x", 0)
        old_y = shape.get("y", 0)
        
        shape_w = shape.get("width", 150)
        shape_h = shape.get("height", 100)
        
        # If it's a margin node, style it as a Diamond (standard Porter Margin triangle/diamond shape)
        if sid == margin_id:
            shape["type"] = "diamond"
            shape_w = max(shape_w, 120)
            shape_h = max(shape_h, 120)
            shape["width"] = shape_w
            shape["height"] = shape_h
            
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
        
        # Style variations
        if sid in primary_chain:
            shape["strokeWidth"] = 2
            if shape.get("type") == "rectangle" and "roundness" not in shape:
                shape["roundness"] = {"type": 3} # Clean rounded edges
        elif sid in support_activities:
            # Dashed outlines for support or thinner lines
            shape["strokeWidth"] = 1.5
            shape["strokeStyle"] = "dashed"
            
        sync_bound_text_translation(shape, elements, dx, dy)

    # 4. Update arrow geometry with clean routing
    for arr, sid, eid in edges:
        s_shape = shapes[sid]
        e_shape = shapes[eid]
        
        s_w = s_shape.get("width", 150)
        s_h = s_shape.get("height", 100)
        e_w = e_shape.get("width", 150)
        e_h = e_shape.get("height", 100)
        
        # Check positions relative to rows
        s_is_support = sid in support_activities
        e_is_primary = eid in primary_chain
        
        sx = float(s_shape["x"] + s_w / 2)
        sy = float(s_shape["y"] + s_h / 2)
        ex = float(e_shape["x"] + e_w / 2)
        ey = float(e_shape["y"] + e_h / 2)
        
        # Case A: Support activity connecting down to Primary activity
        if s_is_support and e_is_primary:
            gap = float(e_shape["y"] - (s_shape["y"] + s_h))
            pad = min(5.0, (gap - 2.0) / 2.0) if gap > 12.0 else 0.0
            start_x = sx
            start_y = float(s_shape["y"] + s_h + pad)
            end_x = sx
            end_y = float(e_shape["y"] - pad)

            arr["x"] = start_x
            arr["y"] = start_y
            arr["points"] = [[0.0, 0.0], [0.0, float(end_y - start_y)]]
            arr["strokeStyle"] = "dashed"  # dashed for support connections

        # Case B, C & Fallback: Safe ray-trimmed endpoints
        else:
            start_x, start_y, end_x, end_y = compute_safe_arrow_endpoints(s_shape, e_shape)
            arr["x"] = start_x
            arr["y"] = start_y
            arr["points"] = [[0.0, 0.0], [float(end_x - start_x), float(end_y - start_y)]]
            arr["strokeStyle"] = "solid"

        # Apply Arrow Aesthetics
        arr["roughness"] = 0
        arr["strokeColor"] = cfg.excalidraw_stroke_color
        arr["strokeWidth"] = cfg.excalidraw_stroke_width
        
    return True
