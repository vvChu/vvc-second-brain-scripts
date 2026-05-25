import os
import json
import re
import lzstring
from pathlib import Path
from sugiyama_layout import apply_sugiyama_layout

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
            
            # Apply Sugiyama layout
            if apply_sugiyama_layout(elements):
                data["elements"] = elements
                new_json = json.dumps(data, ensure_ascii=False, indent=2)
                new_block = f"```json\n{new_json}\n```"
                new_content = content.replace(match.group(0), new_block)
                file_path.write_text(new_content, encoding="utf-8")
                print(f"Applied Sugiyama layout to {file_path.name}")
                count += 1
        except Exception as e:
            print(f"Error on {file_path.name}: {e}")
            
    print(f"Total processed: {count}")

if __name__ == "__main__":
    fix_layouts()
