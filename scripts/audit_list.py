# -*- coding: utf-8 -*-
from pathlib import Path
import json

concepts_dir = Path(r'G:\My Drive\VvC_Vault\04 - Permanent\concepts')
res = {'stubs': [], 'placeholders': []}

for f in concepts_dir.glob('*.md'):
    content = f.read_text(encoding='utf-8').lower()
    if 'source_type: stub' in content: res['stubs'].append(f.name)
    if 'câu của bạn ở đây' in content or 'tóm tắt 2-3 câu' in content: res['placeholders'].append(f.name)

print(json.dumps(res, indent=2))
