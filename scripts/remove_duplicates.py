import re
from pathlib import Path

concepts_dir = Path(r'd:\VvC_Notes\04 - Permanent\concepts')

# Regex to match files ending in _\d.md or _\d_\d.md
dup_pattern = re.compile(r'^(.+)_(\d+)((_\d+)?)\.md$')

removed = 0
for f in concepts_dir.glob("*.md"):
    match = dup_pattern.match(f.name)
    if match:
        base_name = match.group(1) + ".md"
        base_file = concepts_dir / base_name
        
        # Exceptions: if the base name isn't actually a base file
        # E.g., if the file is just named something with a number at the end natively.
        if base_file.exists():
            f.unlink()
            print(f"Removed duplicate: {f.name}")
            removed += 1

print(f"Total removed: {removed}")
