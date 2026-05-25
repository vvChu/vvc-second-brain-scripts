import json
import re

with open(r'd:\VvC_Notes\03 - Resources\attachments\test_diagram.excalidraw.md', 'r', encoding='utf-8') as f:
    raw = f.read()
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
    if json_match:
        data = json.loads(json_match.group(1))
        for el in data.get('elements', []):
            if el.get('type') == 'arrow':
                print(f"Arrow: points={el.get('points')}, roundness={el.get('roundness')}, x={el.get('x')}, y={el.get('y')}")
            elif el.get('type') == 'rectangle':
                print(f"Rect: x={el.get('x')}, y={el.get('y')}, w={el.get('width')}, h={el.get('height')}")
