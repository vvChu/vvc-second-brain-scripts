import os
from pathlib import Path
for root, dirs, files in os.walk(r'd:\VvC_Notes\scripts'):
    for f in files:
        if f.endswith('.py'):
            try:
                content = Path(root) / f
                text = content.read_text(encoding='utf-8')
                if '?nh ch?p' in text:
                    print(f"Found in {content}")
            except Exception: pass
