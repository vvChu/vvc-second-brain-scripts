import json
import re
from pathlib import Path

file_path = Path(r"D:\VvC_Notes\03 - Resources\attachments\value_chain_ai.excalidraw.md")
content = file_path.read_text(encoding="utf-8")

json_match = re.search(r"```json\n(.*?)\n```", content, re.DOTALL)
if not json_match:
    print("JSON not found")
    exit(1)

data = json.loads(json_match.group(1))
elements = data.get("elements", [])

texts = []

for el in elements:
    # Clean professional look
    el["roughness"] = 0
    
    if el.get("type") == "text":
        # Professional font (3 = Cascadia / Monospace, 2 = Helvetica)
        # Let's use 2 (Helvetica/Normal) for a cleaner business look, or 3 as per SKILL.md. 
        # SKILL.md recommends 3.
        el["fontFamily"] = 3
        
        # Fix the spacing issue caused by \n\n
        txt = el.get("text", "")
        txt = txt.replace("\n\n", "\n")
        el["text"] = txt
        
        texts.append(f"{txt}\n^{el['id']}")
        
        # Center align
        if el.get("containerId"):
            el["textAlign"] = "center"
            el["verticalAlign"] = "middle"

text_elements_md = "\n\n".join(texts)
new_json = json.dumps(data, ensure_ascii=False, indent=2)

new_content = f"""---
excalidraw-plugin: parsed
tags: [excalidraw]
---
==⚠  Switch to EXCALIDRAW VIEW in the MORE OPTIONS menu of this document. ⚠==

# Text Elements
{text_elements_md}

%%
# Drawing
```json\n{new_json}\n```
%%
"""

file_path.write_text(new_content, encoding="utf-8")
print("Layout fixed")
