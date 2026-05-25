import sys
import re
import json
from pathlib import Path

# Provide lzstring if available
try:
    import lzstring
except ImportError:
    lzstring = None

# Add scripts to path to import the new validator
_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR))

from services.excalidraw_worker import _validate_excalidraw_json

def heal_diagrams():
    attachments_dir = Path(r"D:\VvC_Notes\03 - Resources\attachments")
    count = 0
    x = lzstring.LZString() if lzstring else None
    
    for file_path in attachments_dir.glob("*.excalidraw.md"):
        try:
            content = file_path.read_text(encoding="utf-8")
            
            # Extract JSON
            match = re.search(r"```(json|compressed-json)\n(.*?)\n```", content, re.DOTALL)
            if not match:
                continue
                
            code_type = match.group(1)
            json_str = match.group(2)
            
            if code_type == "compressed-json":
                if not x:
                    print("lzstring module is required to decompress compressed-json. Run 'pip install lzstring'")
                    continue
                # Decompress
                try:
                    json_str = json_str.replace('\n', '')
                    dec = x.decompressFromBase64(json_str)
                    if dec:
                        json_str = dec
                except Exception:
                    pass
            
            # Pass through our new healer!
            healed = _validate_excalidraw_json(json_str)
            if healed is None:
                print(f"Validation failed for {file_path.name}")
                continue
                
            healed_json, _ = healed
            
            # We want to save it as plaintext json for easier readability/debugging anyway
            new_block = f"```json\n{healed_json}\n```"
            
            # Replace the old block
            new_content = content.replace(match.group(0), new_block)
            
            if new_content != content:
                file_path.write_text(new_content, encoding="utf-8")
                print(f"Healed text elements in: {file_path.name}")
                count += 1
                
        except Exception as e:
            print(f"Error processing {file_path.name}: {e}")
            
    print(f"Total healed: {count}")

if __name__ == "__main__":
    heal_diagrams()
