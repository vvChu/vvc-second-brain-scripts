# -*- coding: utf-8 -*-
import os
import re
from pathlib import Path

concepts_dir = Path(r'G:\My Drive\VvC_Vault\04 - Permanent\concepts')

# Match ![[pXXX_chXX_YYYYMMDD_jpg]]
# Group 1: the stem (pXXX_chXX_YYYYMMDD)
# Group 2: the extension (jpg or png)
pattern = re.compile(r'!\[\[(p\d{3}_ch\d{2}_\d+)_(jpg|png)\]\]', re.IGNORECASE)

stats = {
    'files_checked': 0,
    'files_fixed': 0,
    'total_replacements': 0
}

for f in concepts_dir.glob('*.md'):
    stats['files_checked'] += 1
    content = f.read_text(encoding='utf-8')
    
    new_content, count = pattern.subn(r'![[\1.\2]]', content)
    
    if count > 0:
        f.write_text(new_content, encoding='utf-8')
        stats['files_fixed'] += 1
        stats['total_replacements'] += count
        print(f"Fixed {count} link(s) in {f.name}")

print("\n--- Fix Image Links Complete ---")
print(f"Files Checked: {stats['files_checked']}")
print(f"Files Fixed: {stats['files_fixed']}")
print(f"Total Links Replaced: {stats['total_replacements']}")
