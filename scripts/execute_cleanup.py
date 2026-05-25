# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
import shutil
from pathlib import Path

concepts_dir = Path(r'G:\My Drive\VvC_Vault\04 - Permanent\concepts')
archive_dir = Path(r'G:\My Drive\VvC_Vault\99 - Archive\Non_Atomic_Review')
archive_dir.mkdir(parents=True, exist_ok=True)

stats = {
    'deleted_stubs': 0,
    'deleted_placeholders': 0,
    'deleted_short': 0,
    'moved_long': 0
}

for f in list(concepts_dir.glob('*.md')):
    try:
        content = f.read_text(encoding='utf-8')
        body = content.split('---', 2)[-1] if '---' in content else content
        body_len = len(body.strip())
        
        # Phase 1: Stubs and Placeholders
        is_stub = 'source_type: stub' in content
        has_placeholder = 'câu của bạn ở đây' in content.lower() or 'tóm tắt 2-3 câu' in content.lower()
        
        if is_stub:
            f.unlink()
            stats['deleted_stubs'] += 1
            print(f"Deleted stub: {f.name}")
            continue
            
        if has_placeholder:
            f.unlink()
            stats['deleted_placeholders'] += 1
            print(f"Deleted placeholder: {f.name}")
            continue
            
        # Phase 2: Too Short (< 200 chars)
        if body_len < 200:
            f.unlink()
            stats['deleted_short'] += 1
            print(f"Deleted short ({body_len}c): {f.name}")
            continue
            
        # Phase 3: Too Long (> 4000 chars)
        if body_len > 4000:
            dest = archive_dir / f.name
            shutil.move(str(f), str(dest))
            stats['moved_long'] += 1
            print(f"Moved long ({body_len}c): {f.name}")
            continue

    except Exception as e:
        print(f"Error processing {f.name}: {e}")

print(f"\nCleanup Complete!")
print(f"Stubs Deleted: {stats['deleted_stubs']}")
print(f"Placeholders Deleted: {stats['deleted_placeholders']}")
print(f"Short Files Deleted: {stats['deleted_short']}")
print(f"Long Files Moved: {stats['moved_long']}")
