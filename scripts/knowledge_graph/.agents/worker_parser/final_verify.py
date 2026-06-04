"""Final clean verification: parse vault and check output."""
import io
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding='utf-8', errors='replace',
    )

import importlib.util
import json
from pathlib import Path

# Import parse_graph module
spec = importlib.util.spec_from_file_location(
    'parse_graph',
    'd:/VvC_Notes/scripts/knowledge_graph/parse_graph.py',
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# Check yaml availability
try:
    import yaml
    print(f"PyYAML: {yaml.__version__}")
except ImportError:
    print("PyYAML: NOT AVAILABLE (using fallback)")

# Parse
data = mod.parse_vault()

# Write
out = Path('d:/VvC_Notes/scripts/knowledge_graph/graph_data.json')
json_str = json.dumps(data, ensure_ascii=False, indent=2)
out.write_text(json_str, encoding='utf-8')

meta = data['metadata']
print(f"\ntotal_nodes = {meta['total_nodes']}")
print(f"total_edges = {meta['total_edges']}")
print(f"File size: {out.stat().st_size:,} bytes")

# Quick schema check
from collections import Counter
node_types = Counter(n['type'] for n in data['nodes'])
edge_types = Counter(e['type'] for e in data['edges'])
print(f"\nNode types: {dict(node_types)}")
print(f"Edge types: {dict(edge_types)}")

target = 2232
diff = meta['total_nodes'] - target
status = 'PASS' if abs(diff) <= 2 else 'FAIL'
print(f"\nNode count check: {status} ({meta['total_nodes']} vs {target}, diff={diff})")
