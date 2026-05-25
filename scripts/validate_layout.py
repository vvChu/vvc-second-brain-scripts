import json
import re
from pathlib import Path

content = Path(r'd:\VvC_Notes\03 - Resources\attachments\test_sugiyama_flow.excalidraw.md').read_text(encoding='utf-8')
match = re.search(r'```(?:json)?\n(.*?)\n```', content, re.DOTALL)
if match:
    data = json.loads(match.group(1))
    for el in data.get('elements', []):
        if el.get('type') in ('rectangle', 'ellipse'):
            print(f"Node: {el.get('id'):<10} | x: {el.get('x'):>6.1f} | y: {el.get('y'):>6.1f}")
            for b in el.get('boundElements', []):
                for e2 in data.get('elements', []):
                    if e2.get('id') == b.get('id'):
                        text = e2.get('text', '').replace('\n', ' ')
                        print(f"   -> Text '{text:<30}' | x: {e2.get('x'):>6.1f} | y: {e2.get('y'):>6.1f}")
        if el.get('type') == 'arrow':
            print(f"Arrow from {el.get('startBinding',{}).get('elementId')} to {el.get('endBinding',{}).get('elementId')}")
