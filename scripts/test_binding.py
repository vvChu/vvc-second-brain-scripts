import json
import re
from pathlib import Path
content = Path(r'd:\VvC_Notes\03 - Resources\attachments\diagram_to_chuc_moi.excalidraw.md').read_text(encoding='utf-8')
match = re.search(r'```(?:json|compressed-json)\n(.*?)\n```', content, re.DOTALL)
if match:
    code_type = 'compressed-json' if 'compressed-json' in content[:500] else 'json'
    json_str = match.group(1)
    if code_type == 'compressed-json':
        import lzstring
        json_str = lzstring.LZString().decompressFromBase64(json_str.replace('\n', ''))
    data = json.loads(json_str)
    arrows = [el for el in data.get('elements', []) if el.get('type') == 'arrow']
    print(f'Total arrows: {len(arrows)}')
    for arr in arrows:
        sb = arr.get('startBinding')
        eb = arr.get('endBinding')
        print(f"Arrow {arr.get('id')}: start={sb}, end={eb}")
