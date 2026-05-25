import os
import re
from pathlib import Path

target_dir = Path(r'd:\VvC_Notes\04 - Permanent\concepts')
if not target_dir.exists():
    print(f'Error: Directory {target_dir} does not exist!')
    exit(1)

all_files = list(target_dir.glob('*.md'))
print(f'Total files in concepts: {len(all_files)}')

# Check for FolderSync or GDrive conflicts
conflict_pattern = re.compile(r'(?:\(\d+\)|\.sync-conflict|conflict)')
conflict_files = [f for f in all_files if conflict_pattern.search(f.name)]

print(f'\nConflict/Duplicate files found: {len(conflict_files)}')
for f in conflict_files[:10]:
    print(f' - {f.name}')

# Check for stub files
stub_count = 0
for f in all_files:
    try:
        content = f.read_text(encoding='utf-8')
        if 'source_type: stub' in content:
            stub_count += 1
            if stub_count <= 5:
                print(f'Found stub: {f.name}')
    except Exception as e:
        pass

print(f'\nTotal stubs found: {stub_count}')
