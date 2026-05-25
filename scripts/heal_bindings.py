import os
import json
import re
import lzstring
from pathlib import Path
import sys

sys.path.insert(0, str(Path(r"d:\VvC_Notes\scripts")))
from core.llm import call_llm
from sugiyama_layout import apply_sugiyama_layout

PROMPT = """You are a diagram topology extractor. I have a set of diagram nodes with their text content and IDs.
Based on the text content, infer the logical flow (directed edges) between these nodes to represent a flowchart, architecture, or roadmap.
Output ONLY a JSON array of objects with "source" and "target" fields. No markdown fences. Do NOT include any nodes that are not in the list.

NODES:
{nodes}

Example output:
[
  {{"source": "node1", "target": "node2"}},
  {{"source": "node2", "target": "node3"}}
]
"""

def heal_bindings():
    attachments_dir = Path(r"d:\VvC_Notes\03 - Resources\attachments")
    x = lzstring.LZString()
    count = 0
    
    # We can skip files that we know are manually crafted or already correct
    # e.g., co_cau_tu_van_xay_dung_ai.excalidraw.md
    
    for file_path in attachments_dir.glob("*.excalidraw.md"):
        if "co_cau" in file_path.name:
            continue
            
        print(f"Processing {file_path.name}...")
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
            
            shapes = {el["id"]: el for el in elements if el.get("type") in ("rectangle", "ellipse", "diamond")}
            texts = {el["id"]: el for el in elements if el.get("type") == "text"}
            
            # Map text content to shapes
            shape_texts = {}
            for sid, shape in shapes.items():
                bound_texts = []
                for bound in shape.get("boundElements", []):
                    if isinstance(bound, dict) and bound.get("id") in texts:
                        bound_texts.append(texts[bound["id"]].get("text", ""))
                    elif isinstance(bound, str) and bound in texts:
                        bound_texts.append(texts[bound].get("text", ""))
                
                # check containerId
                for tid, text_el in texts.items():
                    if text_el.get("containerId") == sid:
                        text_val = text_el.get("text", "")
                        if text_val and text_val not in bound_texts:
                            bound_texts.append(text_val)
                            
                shape_texts[sid] = " ".join(bound_texts).strip().replace("\n", " ")
            
            if len(shapes) < 2:
                continue
                
            nodes_str = "\n".join([f"- ID: {sid} | Text: {text}" for sid, text in shape_texts.items() if text])
            if not nodes_str:
                print(f"Skipping {file_path.name} (no text)")
                continue
                
            # Check if this file actually has bad bindings (e.g. all self loops)
            arrows = [el for el in elements if el.get("type") == "arrow"]
            bad_arrows = 0
            for arr in arrows:
                sb = arr.get("startBinding", {})
                eb = arr.get("endBinding", {})
                sid = sb.get("elementId") if isinstance(sb, dict) else sb
                eid = eb.get("elementId") if isinstance(eb, dict) else eb
                if sid == eid or not sid or not eid:
                    bad_arrows += 1
            
            if arrows and bad_arrows == 0:
                print(f"Skipping {file_path.name} (arrows seem valid)")
                continue
                
            print(f"Extracting topology for {file_path.name}...")
            prompt = PROMPT.format(nodes=nodes_str)
            
            # Use call_llm (will route to AI gateway or fallback)
            response = call_llm(prompt, task="reasoning")
            if not response:
                print(f"Failed LLM for {file_path.name}")
                continue
                
            json_match = re.search(r'\[\s*\{.*?\}\s*\]', response, re.DOTALL)
            if json_match:
                edges_json = json_match.group(0)
            else:
                edges_json = response
                
            try:
                edges = json.loads(edges_json)
                if isinstance(edges, dict):
                    edges = [edges]
            except Exception as e:
                print(f"Failed to parse JSON for {file_path.name}: {e}")
                continue
                
            new_elements = [el for el in elements if el.get("type") != "arrow"]
            
            arrow_id_counter = 1
            for edge in edges:
                src = edge.get("source")
                tgt = edge.get("target")
                if src in shapes and tgt in shapes and src != tgt:
                    new_arrow = {
                        "type": "arrow",
                        "id": f"arrow_healed_{arrow_id_counter}",
                        "x": 0, "y": 0,
                        "width": 100, "height": 100,
                        "strokeColor": "#1e1e1e",
                        "backgroundColor": "transparent",
                        "fillStyle": "solid",
                        "strokeWidth": 2,
                        "roughness": 0,
                        "opacity": 100,
                        "startBinding": {"elementId": src, "focus": 0, "gap": 15},
                        "endBinding": {"elementId": tgt, "focus": 0, "gap": 15},
                        "points": [[0,0], [100,100]],
                        "endArrowhead": "arrow"
                    }
                    new_elements.append(new_arrow)
                    arrow_id_counter += 1
                    
            if arrow_id_counter > 1:
                data["elements"] = new_elements
                apply_sugiyama_layout(data["elements"])
                
                new_json = json.dumps(data, ensure_ascii=False, indent=2)
                new_block = f"```json\n{new_json}\n```"
                new_content = content.replace(match.group(0), new_block)
                file_path.write_text(new_content, encoding="utf-8")
                print(f"Healed and layout applied to {file_path.name}")
                count += 1
            else:
                print(f"No valid edges returned for {file_path.name}")
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error on {file_path.name}: {e}")
            
    print(f"Total healed: {count}")

if __name__ == "__main__":
    heal_bindings()
