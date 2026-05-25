import os
import re
from pathlib import Path

# Add scripts directory to path to import local modules
import sys
sys.path.insert(0, str(Path(r"d:\VvC_Notes\scripts")))

from core.llm import call_llm
from services.excalidraw_worker import _validate_excalidraw_json, _MD_TEMPLATE

PROMPT_TEMPLATE = """Re-generate an Excalidraw diagram that visualizes the following text elements as a cohesive conceptual diagram (flowchart or organizational structure).

TEXT ELEMENTS TO INCLUDE:
{texts}

CRITICAL RULES FOR EXCALIDRAW JSON:
1. Output ONLY valid Excalidraw JSON (no markdown fences, no explanation).
2. Shapes CANNOT have a "text" field directly. Text MUST be a separate element bound via `containerId`.
3. Shapes MUST include the text element in their `boundElements` array.
4. Connect shapes with arrows and ENSURE proper `startBinding` and `endBinding` values.
5. Generate a logical structure representing the concepts above.
"""

def recover_files():
    attachments_dir = Path(r"d:\VvC_Notes\03 - Resources\attachments")
    files = attachments_dir.glob("*.excalidraw.md")
    count = 0
    
    for file_path in files:
        if file_path.name in ('test_sugiyama_flow.excalidraw.md'):
            continue
            
        content = file_path.read_text(encoding="utf-8")
        
        # Check if it was touched by our previous script (has "excalidraw-plugin: parsed")
        # and has Text Elements
        if "## Text Elements" not in content and "# Text Elements" not in content:
            continue
            
        # Extract texts
        texts = []
        in_text_section = False
        for line in content.splitlines():
            if "Text Elements" in line:
                in_text_section = True
                continue
            if in_text_section:
                if line.startswith("%%") or line.startswith("# Drawing"):
                    break
                text = line.strip()
                if text:
                    # Remove trailing ^ID
                    text = re.sub(r'\s*\^[a-zA-Z0-9_]+$', '', text)
                    if text and text not in texts:
                        texts.append(text)
                        
        if not texts:
            continue
            
        print(f"Recovering {file_path.name} with {len(texts)} texts...")
        
        prompt = PROMPT_TEMPLATE.format(texts="\n".join(f"- {t}" for t in texts))
        
        json_content = call_llm(prompt, task="reasoning")
        if not json_content:
            print(f"Failed LLM call for {file_path.name}")
            continue
            
        result = _validate_excalidraw_json(json_content)
        if not result:
            print(f"Failed validation for {file_path.name}")
            continue
            
        new_json, _ = result
        new_md = _MD_TEMPLATE.format(json_content=new_json)
        
        # Write back
        file_path.write_text(new_md, encoding="utf-8")
        print(f"Successfully recovered {file_path.name}")
        count += 1
        
    print(f"Total recovered: {count}")

if __name__ == "__main__":
    recover_files()
