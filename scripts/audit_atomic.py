# -*- coding: utf-8 -*-
import os
import re
from pathlib import Path

concepts_dir = Path(r'G:\My Drive\VvC_Vault\04 - Permanent\concepts')

stats = {
    'total': 0,
    'too_short': [],
    'too_long': [],
    'no_core_idea': [],
    'placeholders': [],
    'stubs': []
}

for f in concepts_dir.glob('*.md'):
    stats['total'] += 1
    content = f.read_text(encoding='utf-8')
    
    body = content.split('---', 2)[-1] if '---' in content else content
    body_len = len(body.strip())
    
    if body_len < 300:
        stats['too_short'].append((f.name, body_len))
    elif body_len > 4000:
        stats['too_long'].append((f.name, body_len))
        
    if '## Core Idea' not in content and '## 1. Core Idea' not in content:
        stats['no_core_idea'].append(f.name)
        
    if 'câu của bạn ở đây' in content.lower() or 'tóm tắt 2-3 câu' in content.lower():
        stats['placeholders'].append(f.name)
        
    if 'source_type: stub' in content:
        stats['stubs'].append(f.name)

print(f"Total Concepts: {stats['total']}")
print(f"Too Short (<300 chars): {len(stats['too_short'])}")
for n, l in sorted(stats['too_short'], key=lambda x: x[1])[:5]: print(f"  - {n} ({l} chars)")
print(f"Too Long (>4000 chars - possible non-atomic): {len(stats['too_long'])}")
for n, l in sorted(stats['too_long'], key=lambda x: x[1], reverse=True)[:5]: print(f"  - {n} ({l} chars)")
print(f"Missing Core Idea: {len(stats['no_core_idea'])}")
for n in stats['no_core_idea'][:5]: print(f"  - {n}")
print(f"Has Placeholders: {len(stats['placeholders'])}")
print(f"Stubs: {len(stats['stubs'])}")
