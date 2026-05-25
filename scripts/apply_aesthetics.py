import os
import json
import re
import lzstring
from pathlib import Path
from organic_layout import apply_organic_aesthetics

def batch_apply_aesthetics():
    attachments_dir = Path(r"d:\VvC_Notes\03 - Resources\attachments")
    x = lzstring.LZString()
    count = 0
    
    for file_path in attachments_dir.glob("*.excalidraw.md"):
        if "co_cau" in file_path.name:
            continue
            
        print(f"Applying aesthetics to {file_path.name}...")
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
            
            if apply_organic_aesthetics(elements):
                data["elements"] = elements
                new_json = json.dumps(data, ensure_ascii=False, indent=2)
                new_block = f"```json\n{new_json}\n```"
                new_content = content.replace(match.group(0), new_block)
                file_path.write_text(new_content, encoding="utf-8")
                print(f"Success: {file_path.name}")
                count += 1
            else:
                print(f"Skipped: {file_path.name}")
                
        except Exception as e:
            print(f"Error on {file_path.name}: {e}")
            
    print(f"Total updated: {count}")

if __name__ == "__main__":
    batch_apply_aesthetics()
