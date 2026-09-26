"""VvC Knowledge Graph — Automated Verification Script.

Reads graph_data.json and validates it against the actual vault files:
  1. Node count matches .md file count across 4 target directories.
  2. Edge extraction spot-check (10 random nodes).
  3. Schema compliance for every node and edge.

Exit code 0 = all pass, 1 = any failure.
"""
from __future__ import annotations

import io
import json
import os
import random
import re
import sys
from pathlib import Path

# Force UTF-8 stdout to avoid UnicodeEncodeError on Windows cp1252 console
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SCRIPT_DIR = Path(__file__).resolve().parent
GRAPH_DATA_PATH = SCRIPT_DIR / "graph_data.json"

VAULT_ROOT = Path(__file__).resolve().parent.parent.parent
DIR_CONCEPTS = VAULT_ROOT / "04 - Permanent" / "concepts"
DIR_SOURCES = VAULT_ROOT / "04 - Permanent" / "sources"
DIR_TRANSCRIPTS = VAULT_ROOT / "04 - Permanent" / "sources" / "transcripts"
DIR_TOPICS = VAULT_ROOT / "04 - Permanent" / "topics"

_SUPPORTS_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty() or os.environ.get("FORCE_COLOR")
GREEN = "\033[92m" if _SUPPORTS_COLOR else ""
RED = "\033[91m" if _SUPPORTS_COLOR else ""
CYAN = "\033[96m" if _SUPPORTS_COLOR else ""
BOLD = "\033[1m" if _SUPPORTS_COLOR else ""
RESET = "\033[0m" if _SUPPORTS_COLOR else ""


def _pass() -> str:
    return f"{GREEN}✅ PASS{RESET}"


def _fail() -> str:
    return f"{RED}❌ FAIL{RESET}"


def _list_md(directory: Path, *, recursive: bool = True) -> list[Path]:
    """Return sorted list of .md files in *directory*."""
    if not directory.exists():
        return []
    if recursive:
        return sorted(directory.rglob("*.md"))
    return sorted(p for p in directory.iterdir() if p.suffix == ".md" and p.is_file())


def count_expected_files() -> dict[str, list[Path]]:
    """Return per-directory lists of .md files that should appear as nodes."""
    return {
        "concepts": _list_md(DIR_CONCEPTS),
        "sources": _list_md(DIR_SOURCES, recursive=False),
        "transcripts": _list_md(DIR_TRANSCRIPTS),
        "topics": _list_md(DIR_TOPICS),
    }


_WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
_YAML_LIST_ITEM_RE = re.compile(r"^\s*-\s+(.*)")
_YAML_SCALAR_RE = re.compile(r"^(\w[\w_]*)\s*:\s*(.*)")


def _parse_frontmatter(text: str) -> dict[str, object]:
    """Extract flat dict from YAML frontmatter (best-effort, stdlib)."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}

    result: dict[str, object] = {}
    curr_key, curr_list = None, None
    for raw_line in text[3:end].strip().splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            if curr_key and curr_list is not None:
                result[curr_key] = curr_list
            curr_key, curr_list = None, None
            continue
        m_item = _YAML_LIST_ITEM_RE.match(line)
        if m_item and curr_list is not None:
            curr_list.append(m_item.group(1).strip().strip("'\""))
            continue
        m_scalar = _YAML_SCALAR_RE.match(line)
        if m_scalar:
            if curr_key and curr_list is not None:
                result[curr_key] = curr_list
            key, val = m_scalar.group(1), m_scalar.group(2).strip().strip("'\"")
            if val in ("", "[]"):
                curr_key, curr_list = key, []
            else:
                result[key] = val
                curr_key, curr_list = None, None
    if curr_key and curr_list is not None:
        result[curr_key] = curr_list
    return result


def _extract_body_wiki_links(text: str) -> list[str]:
    """Extract wiki-link targets from body (after frontmatter)."""
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            body = text[end + 4:]
    targets: list[str] = []
    for m in _WIKI_LINK_RE.finditer(body):
        raw = m.group(1).strip()
        targets.append(raw[len("concepts/"):] if raw.startswith("concepts/") else raw)
    return targets


def _normalize_related_entry(entry: str) -> str:
    """Normalize related field item to a plain slug/stem."""
    m = _WIKI_LINK_RE.search(entry)
    if m:
        raw = m.group(1).strip()
        return raw[len("concepts/"):] if raw.startswith("concepts/") else raw
    return entry.strip()


def verify_node_count(graph: dict, expected_files: dict[str, list[Path]]) -> tuple[bool, str]:
    """Check 1: node count matches .md file count."""
    nodes = graph.get("nodes", [])
    actual = len(nodes)
    counts = {k: len(v) for k, v in expected_files.items()}
    total_expected = sum(counts.values())

    lines = [
        f"  Expected: {total_expected} (" + ", ".join(f"{k}: {v}" for k, v in counts.items()) + ")",
        f"  Actual:   {actual}",
    ]
    passed = actual == total_expected
    lines.append(f"  Status:   {_pass() if passed else _fail()}")
    if not passed:
        expected_ids = {p.stem for paths in expected_files.values() for p in paths}
        actual_ids = {n.get("id", "") for n in nodes}
        missing, extra = expected_ids - actual_ids, actual_ids - expected_ids
        if missing:
            lines.append(f"  Missing ({len(missing)}): {sorted(missing)[:10]}{'...' if len(missing) > 10 else ''}")
        if extra:
            lines.append(f"  Extra   ({len(extra)}): {sorted(extra)[:10]}{'...' if len(extra) > 10 else ''}")
    return passed, "\n".join(lines)


def _count_edge_types(edges: list[dict]) -> tuple[dict[str, int], list[str]]:
    """Count edges by type and return formatted summary lines."""
    type_counts: dict[str, int] = {}
    for e in edges:
        etype = e.get("type", "<missing>")
        type_counts[etype] = type_counts.get(etype, 0) + 1

    lines = [
        f"  Related edges:     {type_counts.get('related', 0)}",
        f"  Source ref edges:  {type_counts.get('source_ref', 0)}",
        f"  Wiki link edges:   {type_counts.get('wiki_link', 0)}",
        f"  Total edges:       {len(edges)}",
    ]
    missing = [t for t in ("related", "source_ref", "wiki_link") if type_counts.get(t, 0) == 0]
    if missing:
        lines.append(f"  {_fail()} — missing edge types: {missing}")
    return type_counts, lines


def _spot_check_single_node(node: dict, node_edges: list[dict]) -> list[str]:
    """Spot check a single node's edges against its markdown file content."""
    nid = node["id"]
    fpath = VAULT_ROOT / node["file_path"]
    try: text = fpath.read_text(encoding="utf-8")
    except Exception:
        try: text = fpath.read_text(encoding="utf-8-sig")
        except Exception: return [f"    Cannot read {fpath}"]

    fm = _parse_frontmatter(text)
    edge_targets: dict[str, set[str]] = {}
    for e in node_edges:
        edge_targets.setdefault(e["type"], set()).add(e["target"])

    failures = []
    yaml_rel = fm.get("related", [])
    if isinstance(yaml_rel, str): yaml_rel = [yaml_rel] if yaml_rel else []
    if isinstance(yaml_rel, list) and yaml_rel:
        missing = {_normalize_related_entry(r) for r in yaml_rel if r} - edge_targets.get("related", set())
        if missing: failures.append(f"    {nid}: missing related edges for {sorted(missing)[:5]}")

    yaml_src = fm.get("source", "")
    if isinstance(yaml_src, str) and yaml_src:
        src_stem = yaml_src.replace(".md", "")
        if src_stem and src_stem not in edge_targets.get("source_ref", set()):
            failures.append(f"    {nid}: missing source_ref edge → {src_stem}")

    body_links = _extract_body_wiki_links(text)
    if body_links:
        all_targets = set().union(*edge_targets.values()) if edge_targets else set()
        if sum(1 for bl in body_links if bl in all_targets) == 0 and len(body_links) > 0:
            failures.append(f"    {nid}: 0/{len(body_links)} body wiki-links captured")
    return failures


def _run_edge_spot_check(nodes: list[dict], edges_by_source: dict[str, list[dict]]) -> tuple[bool, list[str]]:
    """Spot check 10 random nodes against files."""
    candidates = [n for n in nodes if n.get("file_path") and (VAULT_ROOT / n["file_path"]).is_file()]
    sample_nodes = random.sample(candidates, min(10, len(candidates))) if candidates else []

    spot_failures = []
    for node in sample_nodes:
        spot_failures.extend(_spot_check_single_node(node, edges_by_source.get(node["id"], [])))

    passed = len(spot_failures) == 0
    lines = [f"  Spot-check ({len(sample_nodes)} nodes): {_pass() if passed else _fail()}"]
    lines.extend(spot_failures[:15])
    return passed, lines


def verify_edge_extraction(graph: dict) -> tuple[bool, str]:
    """Check 2: edge type counts + spot-check 10 random nodes."""
    edges, nodes = graph.get("edges", []), graph.get("nodes", [])
    type_counts, lines = _count_edge_types(edges)

    edges_by_source: dict[str, list[dict]] = {}
    for e in edges:
        edges_by_source.setdefault(e.get("source", ""), []).append(e)

    spot_passed, spot_lines = _run_edge_spot_check(nodes, edges_by_source)
    lines.extend(spot_lines)
    type_present = all(type_counts.get(t, 0) > 0 for t in ("related", "source_ref", "wiki_link"))
    return type_present and spot_passed, "\n".join(lines)


def _validate_node_schemas(nodes: list[dict]) -> list[str]:
    """Validate schema compliance for all nodes."""
    valid_types = {"concept", "source", "topic"}
    errors = []
    for i, n in enumerate(nodes):
        problems = []
        if not isinstance(n.get("id"), str) or not n["id"]: problems.append("missing/invalid 'id'")
        if not isinstance(n.get("title"), str): problems.append("missing/invalid 'title'")
        if n.get("type") not in valid_types: problems.append(f"invalid type '{n.get('type')}'")
        if not isinstance(n.get("tags"), list): problems.append("missing/invalid 'tags' (must be array)")
        if problems:
            errors.append(f"    {n.get('id', f'<index {i}>')}: {', '.join(problems)}")
    return errors


def _validate_edge_schemas(edges: list[dict]) -> list[str]:
    """Validate schema compliance for all edges."""
    valid_types = {"related", "source_ref", "wiki_link"}
    errors = []
    for i, e in enumerate(edges):
        problems = []
        if not isinstance(e.get("source"), str) or not e["source"]: problems.append("missing/invalid 'source'")
        if not isinstance(e.get("target"), str) or not e["target"]: problems.append("missing/invalid 'target'")
        if e.get("type") not in valid_types: problems.append(f"invalid type '{e.get('type')}'")
        if problems:
            errors.append(f"    edge[{i}]: {', '.join(problems)}")
    return errors


def verify_schema(graph: dict) -> tuple[bool, str]:
    """Check 3: schema compliance for nodes and edges."""
    nodes, edges = graph.get("nodes", []), graph.get("edges", [])
    node_errors = _validate_node_schemas(nodes)
    edge_errors = _validate_edge_schemas(edges)

    lines = [
        f"  Nodes with valid schema: {len(nodes) - len(node_errors)}/{len(nodes)}",
        f"  Edges with valid schema: {len(edges) - len(edge_errors)}/{len(edges)}",
    ]
    passed = not node_errors and not edge_errors
    lines.append(f"  Status: {_pass() if passed else _fail()}")
    if node_errors:
        lines.append(f"  Node errors ({len(node_errors)}):")
        lines.extend(node_errors[:10])
        if len(node_errors) > 10: lines.append(f"    ... and {len(node_errors) - 10} more")
    if edge_errors:
        lines.append(f"  Edge errors ({len(edge_errors)}):")
        lines.extend(edge_errors[:10])
        if len(edge_errors) > 10: lines.append(f"    ... and {len(edge_errors) - 10} more")
    return passed, "\n".join(lines)


def _load_graph_data() -> dict | None:
    """Load and validate graph_data.json."""
    if not GRAPH_DATA_PATH.exists():
        print(f"{RED}ERROR: {GRAPH_DATA_PATH} not found.{RESET}\n  Run parse_graph.py first.")
        return None
    try:
        with open(GRAPH_DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        print(f"{RED}ERROR: graph_data.json root must be a JSON object{RESET}")
    except json.JSONDecodeError as exc:
        print(f"{RED}ERROR: graph_data.json is not valid JSON — {exc}{RESET}")
    return None


def main() -> int:
    """Run all verification checks and return exit code (0=pass, 1=fail)."""
    print(f"\n{BOLD}=== VvC Knowledge Graph Verification ==={RESET}\n")
    graph = _load_graph_data()
    if graph is None:
        return 1

    checks = [
        ("[NODE COUNT]", lambda: verify_node_count(graph, count_expected_files())),
        ("[EDGE EXTRACTION]", lambda: verify_edge_extraction(graph)),
        ("[SCHEMA COMPLIANCE]", lambda: verify_schema(graph)),
    ]
    all_passed = True
    for label, fn in checks:
        print(f"{CYAN}{label}{RESET}")
        ok, report = fn()
        print(report + "\n")
        if not ok:
            all_passed = False

    status = f"{GREEN}✅ ALL CHECKS PASSED" if all_passed else f"{RED}❌ SOME CHECKS FAILED"
    print(f"{BOLD}=== OVERALL: {status}{RESET}{BOLD} ==={RESET}\n")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
