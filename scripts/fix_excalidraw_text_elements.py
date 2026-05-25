import re
from pathlib import Path

def fix_excalidraw_files():
    attachments_dir = Path(r"D:\VvC_Notes\03 - Resources\attachments")
    count = 0
    
    for file_path in attachments_dir.glob("*.excalidraw.md"):
        try:
            content = file_path.read_text(encoding="utf-8")
            
            # Use regex to find the Text Elements block and replace it with an empty one
            # The block starts at "# Text Elements" and ends at "%%"
            pattern = re.compile(r"(# Text Elements\s*\n).*?(%%)", re.DOTALL)
            
            new_content, num_subs = pattern.subn(r"\1\n\2", content)
            
            if num_subs > 0 and new_content != content:
                file_path.write_text(new_content, encoding="utf-8")
                print(f"Fixed: {file_path.name}")
                count += 1
                
        except Exception as e:
            print(f"Error processing {file_path.name}: {e}")
            
    print(f"Total fixed: {count}")

if __name__ == "__main__":
    fix_excalidraw_files()
