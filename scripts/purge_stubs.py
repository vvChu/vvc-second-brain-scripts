import os
from pathlib import Path

target_dir = Path(r'd:\VvC_Notes\04 - Permanent\concepts')
all_files = list(target_dir.glob('*.md'))
deleted_count = 0

for f in all_files:
    try:
        content = f.read_text(encoding='utf-8')
        if 'source_type: stub' in content:
            f.unlink()
            deleted_count += 1
            print(f'Deleted: {f.name}')
    except Exception as e:
        print(f'Error reading {f.name}: {e}')

print(f'\nTotal deleted: {deleted_count}')
