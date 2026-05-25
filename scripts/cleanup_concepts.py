from pathlib import Path
import re

concepts_dir = Path(r"d:\VvC_Notes\04 - Permanent\concepts")

deleted_count = 0
for file_path in concepts_dir.glob("*_*.md"):
    # Match files ending in _<number>.md
    match = re.search(r"_(?P<num>\d+)\.md$", file_path.name)
    if match:
        base_name = file_path.name[:match.start()] + ".md"
        base_path = concepts_dir / base_name
        
        # Only delete if the base file without the number ACTUALLY exists
        # This prevents deleting files like cot_moc_imagenet_2012.md
        if base_path.exists():
            print(f"Deleting duplicate: {file_path.name} (Base: {base_name} exists)")
            file_path.unlink()
            deleted_count += 1

print(f"Cleanup complete. Deleted {deleted_count} duplicate concepts.")
