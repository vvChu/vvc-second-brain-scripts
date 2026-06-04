"""Verify graph_data.json structure and content."""
import io
import json
import sys
from collections import Counter
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding='utf-8', errors='replace',
    )

data = json.loads(Path('d:/VvC_Notes/scripts/knowledge_graph/graph_data.json').read_text(encoding='utf-8'))

meta = data['metadata']
print('=== Metadata ===')
for k, v in meta.items():
    print(f'  {k}: {v}')

print('\n=== Node structure (first node) ===')
n = data['nodes'][0]
for k, v in n.items():
    print(f'  {k}: {repr(v)[:80]}')

print('\n=== Edge structure (first 3 edges) ===')
for e in data['edges'][:3]:
    print(f"  {e['source']} -> {e['target']} ({e['type']})")

edge_types = Counter(e['type'] for e in data['edges'])
print('\n=== Edge type breakdown ===')
for t, c in edge_types.most_common():
    print(f'  {t}: {c}')

node_types = Counter(n['type'] for n in data['nodes'])
print('\n=== Node type breakdown ===')
for t, c in node_types.most_common():
    print(f'  {t}: {c}')

# Check alexnet node
for n in data['nodes']:
    if n['id'] == 'alexnet_tac_dong_lich_su':
        print('\n=== Sample: alexnet_tac_dong_lich_su ===')
        for k, v in n.items():
            print(f'  {k}: {repr(v)[:100]}')
        break

# Check edges for alexnet
print('\n=== Edges from alexnet ===')
for e in data['edges']:
    if e['source'] == 'alexnet_tac_dong_lich_su':
        print(f"  -> {e['target']} ({e['type']})")

# Schema validation
print('\n=== Schema Validation ===')
required_meta_keys = {'generated_at', 'vault_root', 'total_nodes', 'total_edges'}
required_node_keys = {'id', 'title', 'type', 'tags', 'aliases', 'summary', 'source', 'file_path'}
required_edge_keys = {'source', 'target', 'type'}

meta_ok = required_meta_keys.issubset(meta.keys())
print(f'  metadata keys: {"PASS" if meta_ok else "FAIL"}')

nodes_ok = all(required_node_keys.issubset(n.keys()) for n in data['nodes'])
print(f'  node keys: {"PASS" if nodes_ok else "FAIL"}')

edges_ok = all(required_edge_keys.issubset(e.keys()) for e in data['edges'])
print(f'  edge keys: {"PASS" if edges_ok else "FAIL"}')

valid_types = {'concept', 'source', 'topic'}
types_ok = all(n['type'] in valid_types for n in data['nodes'])
print(f'  node types valid: {"PASS" if types_ok else "FAIL"}')

edge_type_set = {'related', 'source_ref', 'wiki_link'}
etypes_ok = all(e['type'] in edge_type_set for e in data['edges'])
print(f'  edge types valid: {"PASS" if etypes_ok else "FAIL"}')

total = meta['total_nodes']
print(f'\n  total_nodes: {total} (target: 2232, diff: {total - 2232})')
