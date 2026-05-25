import os
import json
import re
import networkx as nx
import lzstring
from pathlib import Path

def apply_networkx_layout(elements):
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
        
    # Check if they are stacked (x == 100 or x spacing is weird)
    xs = [s.get("x") for s in shapes.values()]
    if not (xs and all(x == 100 or x == xs[0] for x in xs)):
        # Maybe they are not purely stacked, but if they are close, let's still layout
        pass
        
    G = nx.Graph()
    for sid in shapes:
        G.add_node(sid)
        
    edges = []
    for arr in arrows:
        sb = arr.get("startBinding")
        eb = arr.get("endBinding")
        
        start_id = sb.get("elementId") if isinstance(sb, dict) else (sb if isinstance(sb, str) else None)
        end_id = eb.get("elementId") if isinstance(eb, dict) else (eb if isinstance(eb, str) else None)
        
        if start_id in shapes and end_id in shapes:
            G.add_edge(start_id, end_id)
            edges.append((arr, start_id, end_id))
            # Also ensure arrows actually bind properly
            if not isinstance(sb, dict):
                arr["startBinding"] = {"elementId": start_id, "focus": 0, "gap": 15}
            if not isinstance(eb, dict):
                arr["endBinding"] = {"elementId": end_id, "focus": 0, "gap": 15}

    # If graph is disconnected, spring layout still handles it by separating components
    pos = nx.spring_layout(G, k=1.5, scale=400, center=(500, 400), iterations=100)
    
    # Update shape positions
    for sid, (x, y) in pos.items():
        shape = shapes[sid]
        
        # Calculate delta to move text too
        old_x = shape.get("x", 0)
        old_y = shape.get("y", 0)
        dx = x - old_x
        dy = y - old_y
        
        shape["x"] = float(x)
        shape["y"] = float(y)
        
        # Move bound text
        for bound in shape.get("boundElements", []):
            if isinstance(bound, dict) and bound.get("type") == "text":
                tid = bound["id"]
                for el in elements:
                    if el.get("id") == tid and el.get("type") == "text":
                        el["x"] = float(el.get("x", 0) + dx)
                        el["y"] = float(el.get("y", 0) + dy)
                        
    # Update arrows geometrically
    for arr, sid, eid in edges:
        s_shape = shapes[sid]
        e_shape = shapes[eid]
        
        # Centers
        sx = float(s_shape["x"] + s_shape.get("width", 100) / 2)
        sy = float(s_shape["y"] + s_shape.get("height", 100) / 2)
        
        ex = float(e_shape["x"] + e_shape.get("width", 100) / 2)
        ey = float(e_shape["y"] + e_shape.get("height", 100) / 2)
        
        arr["x"] = sx
        arr["y"] = sy
        arr["points"] = [[0.0, 0.0], [float(ex - sx), float(ey - sy)]]
        
    return True

def fix_layouts():
    attachments_dir = Path(r"d:\VvC_Notes\03 - Resources\attachments")
    x = lzstring.LZString()
    count = 0
    
    for file_path in attachments_dir.glob("*.excalidraw.md"):
        try:
            content = file_path.read_text(encoding="utf-8")
            match = re.search(r"```(json|compressed-json)\n(.*?)\n```", content, re.DOTALL)
            if not match: continue
            
            code_type = match.group(1)
            json_str = match.group(2)
            if code_type == "compressed-json":
                json_str = json_str.replace("\n", "")
                dec = x.decompressFromBase64(json_str)
                if dec: json_str = dec
                
            data = json.loads(json_str)
            elements = data.get("elements", [])
            
            # Check if stacked
            shapes = [el for el in elements if el.get("type") in ("rectangle", "ellipse", "diamond")]
            if not shapes: continue
            xs = [s.get("x") for s in shapes]
            
            # Only fix if all x are identical or it's clearly a stacked vertical line
            if len(set(xs)) <= 2: 
                if apply_networkx_layout(elements):
                    data["elements"] = elements
                    new_json = json.dumps(data, ensure_ascii=False, indent=2)
                    new_block = f"```json\n{new_json}\n```"
                    new_content = content.replace(match.group(0), new_block)
                    file_path.write_text(new_content, encoding="utf-8")
                    print(f"Fixed layout for {file_path.name}")
                    count += 1
        except Exception as e:
            print(f"Error on {file_path.name}: {e}")
            
    print(f"Total fixed: {count}")

if __name__ == "__main__":
    fix_layouts()
