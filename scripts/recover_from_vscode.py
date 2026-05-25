import os, json, shutil
from urllib.parse import unquote

vscode_history_dir = r"C:\Users\chuvu\AppData\Roaming\Code\User\History"
scripts_dir = r"d:\VvC_Notes\scripts"

# Find all 0 byte files in scripts/
empty_files = []
for root, _, files in os.walk(scripts_dir):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            if os.path.getsize(path) == 0:
                empty_files.append(path)

print(f"Found {len(empty_files)} empty .py files. Searching VS Code history...")

# Build a mapping of file path to its VS Code History folder
history_map = {}
for root, _, files in os.walk(vscode_history_dir):
    if 'entries.json' in files:
        try:
            with open(os.path.join(root, 'entries.json'), encoding='utf-8') as jf:
                data = json.load(jf)
                resource = data.get('resource', '')
                if resource.startswith('file:///'):
                    # Convert file:///d%3A/... to d:\...
                    path = unquote(resource[8:]).replace('/', '\\')
                    # capitalize drive letter for matching
                    if path[1] == ':':
                        path = path[0].lower() + path[1:]
                    history_map[path] = root
        except Exception as e:
            pass

recovered = 0
for empty_file in empty_files:
    # try to match path
    empty_file_lower = empty_file.lower()
    matched_history_dir = None
    for h_path, h_dir in history_map.items():
        if h_path.lower() == empty_file_lower:
            matched_history_dir = h_dir
            break
            
    if matched_history_dir:
        # Get the latest entry
        entries_json = os.path.join(matched_history_dir, 'entries.json')
        try:
            with open(entries_json, encoding='utf-8') as jf:
                data = json.load(jf)
                entries = data.get('entries', [])
                if entries:
                    # Sort by timestamp descending
                    entries.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
                    # Find the latest entry that has a non-zero size
                    for entry in entries:
                        entry_id = entry.get('id')
                        backup_file = os.path.join(matched_history_dir, entry_id)
                        if os.path.exists(backup_file) and os.path.getsize(backup_file) > 0:
                            # Restore!
                            shutil.copy2(backup_file, empty_file)
                            recovered += 1
                            print(f"Recovered: {empty_file}")
                            break
        except Exception as e:
            print(f"Error recovering {empty_file}: {e}")

print(f"\nRecovered {recovered} out of {len(empty_files)} files from VS Code Local History.")
