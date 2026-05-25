import json
import re
from pathlib import Path

file_path = Path(r"D:\VvC_Notes\03 - Resources\attachments\value_chain_ai.excalidraw.md")
content = file_path.read_text(encoding="utf-8")

# Extract JSON
json_match = re.search(r"```json\n(.*?)\n```", content, re.DOTALL)
if not json_match:
    print("JSON not found")
    exit(1)

data = json.loads(json_match.group(1))

texts = []
elements = data.get("elements", [])
containers = {el["id"]: el for el in elements if "id" in el}

for el in elements:
    if el.get("type") == "text":
        txt = el.get("text", "")
        # Obsidian Excalidraw uses the exact text for block ref
        texts.append(f"{txt}\n^{el['id']}")
        
        # Add boundElements to container
        c_id = el.get("containerId")
        if c_id and c_id in containers:
            c = containers[c_id]
            if "boundElements" not in c or not c["boundElements"]:
                c["boundElements"] = []
            # Check if already bound
            if not any(b.get("id") == el["id"] for b in c["boundElements"]):
                c["boundElements"].append({"id": el["id"], "type": "text"})
                
        # Fix colors for dark mode visibility (use SKILL.md colors)
        el["strokeColor"] = "#ffffff" if el.get("containerId") else "#1e40af"

# Fix shape colors to match SKILL.md palette so they don't invert to pure black
for el in elements:
    if el.get("type") in ["rectangle", "ellipse", "diamond"]:
        el["backgroundColor"] = "#3b82f6"
        el["strokeColor"] = "#1e3a5f"
        el["fillStyle"] = "solid"
        el["roughness"] = 0
        el["opacity"] = 100
        
    # Also fix arrow colors to be visible
    elif el.get("type") == "arrow":
        el["strokeColor"] = "#1e3a5f"
        el["strokeWidth"] = 2

new_json = json.dumps(data, ensure_ascii=False, indent=2)

text_elements_md = "\n\n".join(texts)

new_content = f"""---
excalidraw-plugin: parsed
tags: [excalidraw]
---
==⚠  Switch to EXCALIDRAW VIEW in the MORE OPTIONS menu of this document. ⚠==

# Text Elements
{text_elements_md}

%%
# Drawing
```json
{new_json}
```
%%
"""

file_path.write_text(new_content, encoding="utf-8")
print("Fixed successfully")
