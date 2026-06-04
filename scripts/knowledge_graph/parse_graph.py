"""parse_graph.py — VvC Second Brain Vault → Knowledge Graph JSON.

Scans 4 directories under the vault, extracts YAML frontmatter + body
wiki-links, and produces graph_data.json with nodes and edges.

Usage:
    python parse_graph.py
"""

from __future__ import annotations

import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Force UTF-8 stdout to avoid UnicodeEncodeError on Windows cp1252 console
# ---------------------------------------------------------------------------
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding='utf-8', errors='replace',
    )

# ---------------------------------------------------------------------------
# YAML loader: prefer PyYAML, fall back to a stdlib regex parser
# ---------------------------------------------------------------------------
try:
    import yaml  # type: ignore[import-untyped]

    def _load_yaml(text: str) -> dict[str, Any]:
        """Parse YAML text with PyYAML (safe_load)."""
        try:
            data = yaml.safe_load(text)
            return data if isinstance(data, dict) else {}
        except yaml.YAMLError:
            return {}

except ImportError:

    def _load_yaml(text: str) -> dict[str, Any]:  # type: ignore[misc]
        """Minimal fallback YAML parser using only stdlib.

        Handles the subset of YAML used in vault frontmatter:
        scalar key-value pairs, simple lists, and quoted strings.
        """
        result: dict[str, Any] = {}
        current_key: str | None = None
        current_list: list[str] | None = None

        for raw_line in text.splitlines():
            line = raw_line.rstrip()

            # List continuation (indented or root-level)
            if re.match(r'^(\s+)-\s+', line) or line.startswith('- '):
                value = re.sub(r'^\s*-\s*', '', line).strip()
                value = value.strip("'\"")
                if current_list is not None:
                    current_list.append(value)
                continue

            # Key-value
            m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)', line)
            if m:
                key, val = m.group(1), m.group(2).strip()
                current_key = key
                if val in ("", "[]"):
                    current_list = []
                    result[key] = current_list
                else:
                    current_list = None
                    val = val.strip("'\"")
                    result[key] = val

        return result


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VAULT_ROOT = Path(__file__).resolve().parent.parent.parent  # d:/VvC_Notes
OUTPUT_PATH = Path(__file__).resolve().parent / "graph_data.json"

# Directory → assigned node type
SCAN_DIRS: list[tuple[Path, str]] = [
    (VAULT_ROOT / "04 - Permanent" / "concepts", "concept"),
    (VAULT_ROOT / "04 - Permanent" / "sources", "source"),         # root-level only
    (VAULT_ROOT / "04 - Permanent" / "sources" / "transcripts", "source"),
    (VAULT_ROOT / "04 - Permanent" / "topics", "topic"),
]

# Regex for body wiki-links: [[target]] or [[target|alias]]
_WIKILINK_RE = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')

# Regex to normalise the related field entries (same pattern)
_RELATED_RE = re.compile(r'^\[\[([^\]|]+)(?:\|[^\]]+)?\]\]$')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a markdown file into (frontmatter_dict, body_text).

    Returns ({}, full_text) when no valid frontmatter is found.
    """
    # Frontmatter must start with '---' on the first line (allow BOM / \r\n)
    stripped = text.lstrip('\ufeff')
    if not stripped.startswith('---'):
        return {}, text

    # Find the closing '---' (handle \r\n and \n)
    # Search for \n--- on its own line
    end_idx = stripped.find('\n---', 3)
    if end_idx == -1:
        return {}, text

    yaml_text = stripped[3:end_idx].strip()
    body = stripped[end_idx + 4:]  # skip past '\n---'

    fm = _load_yaml(yaml_text)
    return fm, body


def _normalise_related_entry(entry: Any) -> str | None:
    """Normalise a single entry from the `related` YAML list.

    Returns the bare slug/stem, or None if unusable.
    """
    if not isinstance(entry, str):
        return None
    entry = entry.strip()
    if not entry:
        return None

    # Try wiki-link extraction
    m = _RELATED_RE.match(entry)
    if m:
        target = m.group(1).strip()
    else:
        target = entry

    # Strip path prefixes (e.g. concepts/foo → foo)
    if '/' in target:
        target = target.rsplit('/', 1)[-1]

    # Strip .md extension if present
    if target.endswith('.md'):
        target = target[:-3]

    return target if target else None


def _extract_body_wikilinks(body: str) -> set[str]:
    """Extract all wiki-link targets from the markdown body."""
    targets: set[str] = set()
    for m in _WIKILINK_RE.finditer(body):
        target = m.group(1).strip()
        # Strip path prefixes
        if '/' in target:
            target = target.rsplit('/', 1)[-1]
        # Strip .md extension if present
        if target.endswith('.md'):
            target = target[:-3]
        if target:
            targets.add(target)
    return targets


def _source_ref_target(source_val: Any) -> str | None:
    """Extract a node-id from the YAML `source` field.

    The field may be a filename like 'foo.md' or 'foo.epub' —
    only .md files and bare slugs map to actual source notes.
    """
    if not isinstance(source_val, str):
        return None
    source_val = source_val.strip()
    if not source_val:
        return None
    # Only treat .md references as edges to source nodes
    if source_val.endswith('.md'):
        return source_val[:-3]
    # Some files reference without .md extension — accept as-is if they
    # look like a plausible node id (no dots = no extension = slug)
    if '.' not in source_val:
        return source_val
    # Skip .epub, .pdf, etc. — those are external files, not vault nodes
    return None


def _safe_str_list(val: Any) -> list[str]:
    """Coerce a YAML value to list[str], handling None / scalar / list."""
    if val is None:
        return []
    if isinstance(val, str):
        return [val] if val else []
    if isinstance(val, list):
        return [str(v) for v in val if v is not None]
    return []


# ---------------------------------------------------------------------------
# Core parse
# ---------------------------------------------------------------------------

def parse_vault() -> dict[str, Any]:
    """Parse the entire vault and return the graph data structure."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    t_start = time.perf_counter()

    for dir_path, node_type in SCAN_DIRS:
        if not dir_path.is_dir():
            print(f"  [WARN] Directory not found: {dir_path}")
            continue

        md_files = sorted(dir_path.glob('*.md'))
        for md_file in md_files:
            node_id = md_file.stem

            # Avoid duplicates (shouldn't happen but guard)
            if node_id in node_ids:
                continue
            node_ids.add(node_id)

            # Read file
            try:
                text = md_file.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue

            # Parse frontmatter + body (empty files get default node)
            if text.strip():
                fm, body = _split_frontmatter(text)
            else:
                fm, body = {}, ''

            # Build node
            title = fm.get('title', node_id)
            if isinstance(title, str):
                title = title.strip('"').strip("'")
            else:
                title = str(title) if title is not None else node_id

            # Compute relative path for file_path field
            try:
                rel_path = md_file.relative_to(VAULT_ROOT).as_posix()
            except ValueError:
                rel_path = str(md_file)

            node: dict[str, Any] = {
                'id': node_id,
                'title': title,
                'type': node_type,
                'tags': _safe_str_list(fm.get('tags')),
                'aliases': _safe_str_list(fm.get('aliases')),
                'summary': fm.get('summary', '') or '',
                'source': _source_ref_target(fm.get('source')) or '',
                'file_path': rel_path,
            }
            nodes.append(node)

            # ---- Edges ----
            edge_targets_used: set[str] = set()

            # 1. related edges
            related_raw = fm.get('related')
            if isinstance(related_raw, list):
                for entry in related_raw:
                    target = _normalise_related_entry(entry)
                    if target and target != node_id:
                        edge_targets_used.add(target)
                        edges.append({
                            'source': node_id,
                            'target': target,
                            'type': 'related',
                        })

            # 2. source_ref edge
            source_target = _source_ref_target(fm.get('source'))
            if source_target and source_target != node_id:
                edge_targets_used.add(source_target)
                edges.append({
                    'source': node_id,
                    'target': source_target,
                    'type': 'source_ref',
                })

            # 3. wiki_link edges (body only, excluding already-captured)
            body_links = _extract_body_wikilinks(body)
            for target in sorted(body_links):
                if target not in edge_targets_used and target != node_id:
                    edges.append({
                        'source': node_id,
                        'target': target,
                        'type': 'wiki_link',
                    })

    elapsed = time.perf_counter() - t_start

    # Build output
    graph_data: dict[str, Any] = {
        'metadata': {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'vault_root': str(VAULT_ROOT).replace('\\', '/') + '/',
            'total_nodes': len(nodes),
            'total_edges': len(edges),
        },
        'nodes': nodes,
        'edges': edges,
    }

    # Stats
    type_counts: dict[str, int] = {}
    for n in nodes:
        t = n['type']
        type_counts[t] = type_counts.get(t, 0) + 1

    print(f"  Parsed {len(nodes)} nodes in {elapsed:.2f}s")
    for t, c in sorted(type_counts.items()):
        print(f"    {t}: {c}")
    print(f"  Total edges: {len(edges)}")

    return graph_data


def main() -> None:
    """Entry point: parse vault and write graph_data.json."""
    print("=== VvC Knowledge Graph Parser ===")
    print(f"  Vault root: {VAULT_ROOT}")
    print(f"  Output: {OUTPUT_PATH}")
    print()

    graph_data = parse_vault()

    # Write JSON
    json_str = json.dumps(graph_data, ensure_ascii=False, indent=2)
    OUTPUT_PATH.write_text(json_str, encoding='utf-8')
    print(f"\n  Written to {OUTPUT_PATH}")
    print(f"  File size: {OUTPUT_PATH.stat().st_size:,} bytes")

    # Write JS (for frontend <script> loading)
    js_path = OUTPUT_PATH.with_suffix('.js')
    js_path.write_text(
        'window.GRAPH_DATA = ' + json_str + ';\n',
        encoding='utf-8',
    )
    print(f'  Written to {js_path}')

    # Sample nodes
    print("\n  --- Sample nodes (first 3) ---")
    for node in graph_data['nodes'][:3]:
        title_display = node['title'][:60]
        print(f"    {node['id']} ({node['type']}): {title_display}")


if __name__ == '__main__':
    main()
