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

# ---------------------------------------------------------------------------
# Force UTF-8 stdout to avoid UnicodeEncodeError on Windows cp1252 console
# ---------------------------------------------------------------------------
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding='utf-8', errors='replace',
    )

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
GRAPH_DATA_PATH = SCRIPT_DIR / "graph_data.json"

VAULT_ROOT = Path(r"d:/VvC_Notes")
DIR_CONCEPTS = VAULT_ROOT / "04 - Permanent" / "concepts"
DIR_SOURCES = VAULT_ROOT / "04 - Permanent" / "sources"
DIR_TRANSCRIPTS = VAULT_ROOT / "04 - Permanent" / "sources" / "transcripts"
DIR_TOPICS = VAULT_ROOT / "04 - Permanent" / "topics"

# ---------------------------------------------------------------------------
# Terminal colours (ANSI — works in modern Windows terminals)
# ---------------------------------------------------------------------------
_SUPPORTS_COLOR = (
    hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
) or os.environ.get("FORCE_COLOR")

GREEN = "\033[92m" if _SUPPORTS_COLOR else ""
RED = "\033[91m" if _SUPPORTS_COLOR else ""
YELLOW = "\033[93m" if _SUPPORTS_COLOR else ""
CYAN = "\033[96m" if _SUPPORTS_COLOR else ""
BOLD = "\033[1m" if _SUPPORTS_COLOR else ""
RESET = "\033[0m" if _SUPPORTS_COLOR else ""


def _pass() -> str:
    return f"{GREEN}✅ PASS{RESET}"


def _fail() -> str:
    return f"{RED}❌ FAIL{RESET}"


# ---------------------------------------------------------------------------
# 1. Filesystem helpers
# ---------------------------------------------------------------------------
def _list_md(directory: Path, *, recursive: bool = True) -> list[Path]:
    """Return sorted list of .md files in *directory*.

    When *recursive* is False only direct children are returned (used for
    sources/ root which must exclude subdirectories).
    """
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


# ---------------------------------------------------------------------------
# 2. Minimal YAML parser (stdlib-only)
# ---------------------------------------------------------------------------
_WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
_YAML_LIST_ITEM_RE = re.compile(r"^\s*-\s+(.*)")
_YAML_SCALAR_RE = re.compile(r"^(\w[\w_]*)\s*:\s*(.*)")


def _parse_frontmatter(text: str) -> dict[str, object]:
    """Extract a *flat* dict from YAML frontmatter (best-effort, stdlib).

    Handles scalar values and simple list fields (``related``, ``tags``).
    Returns an empty dict when no valid frontmatter is found.
    """
    # Frontmatter delimited by leading/trailing '---'
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end].strip()

    result: dict[str, object] = {}
    current_key: str | None = None
    current_list: list[str] | None = None

    for raw_line in block.splitlines():
        line = raw_line.rstrip()

        # Blank line — reset context
        if not line.strip():
            if current_key and current_list is not None:
                result[current_key] = current_list
            current_key = None
            current_list = None
            continue

        # Check for list continuation
        m_item = _YAML_LIST_ITEM_RE.match(line)
        if m_item and current_list is not None:
            val = m_item.group(1).strip().strip("'\"")
            current_list.append(val)
            continue

        # Check for new scalar key
        m_scalar = _YAML_SCALAR_RE.match(line)
        if m_scalar:
            # Flush any pending list
            if current_key and current_list is not None:
                result[current_key] = current_list

            key = m_scalar.group(1)
            val = m_scalar.group(2).strip().strip("'\"")
            if val == "" or val == "[]":
                # Could be an empty list or start of a list block
                current_key = key
                current_list = []
            else:
                result[key] = val
                current_key = None
                current_list = None
            continue

        # List item outside of a key context — skip
        if m_item:
            continue

    # Flush final list
    if current_key and current_list is not None:
        result[current_key] = current_list

    return result


def _extract_body_wiki_links(text: str) -> list[str]:
    """Extract wiki-link targets from the body (after frontmatter).

    Strips ``concepts/`` prefix if present.
    """
    # Skip frontmatter
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            body = text[end + 4:]

    targets: list[str] = []
    for m in _WIKI_LINK_RE.finditer(body):
        raw = m.group(1).strip()
        # Normalize: remove optional path prefix
        if raw.startswith("concepts/"):
            raw = raw[len("concepts/"):]
        targets.append(raw)
    return targets


def _normalize_related_entry(entry: str) -> str:
    """Normalize a ``related`` field item to a plain slug/stem."""
    m = _WIKI_LINK_RE.search(entry)
    if m:
        raw = m.group(1).strip()
        if raw.startswith("concepts/"):
            raw = raw[len("concepts/"):]
        return raw
    # Already a plain slug
    return entry.strip()


# ---------------------------------------------------------------------------
# 3. Verification checks
# ---------------------------------------------------------------------------
def verify_node_count(
    graph: dict, expected_files: dict[str, list[Path]]
) -> tuple[bool, str]:
    """Check 1: node count matches .md file count."""
    nodes = graph.get("nodes", [])
    actual = len(nodes)

    counts = {k: len(v) for k, v in expected_files.items()}
    total_expected = sum(counts.values())

    lines = [
        f"  Expected: {total_expected} ("
        + ", ".join(f"{k}: {v}" for k, v in counts.items())
        + ")",
        f"  Actual:   {actual}",
    ]

    passed = actual == total_expected
    lines.append(f"  Status:   {_pass() if passed else _fail()}")
    if not passed:
        # Extra diagnostics: list missing / extra node ids
        expected_ids = set()
        for paths in expected_files.values():
            for p in paths:
                expected_ids.add(p.stem)
        actual_ids = {n.get("id", "") for n in nodes}
        missing = expected_ids - actual_ids
        extra = actual_ids - expected_ids
        if missing:
            sample = sorted(missing)[:10]
            lines.append(
                f"  Missing ({len(missing)}): {sample}{'...' if len(missing) > 10 else ''}"
            )
        if extra:
            sample = sorted(extra)[:10]
            lines.append(
                f"  Extra   ({len(extra)}): {sample}{'...' if len(extra) > 10 else ''}"
            )

    return passed, "\n".join(lines)


def verify_edge_extraction(graph: dict) -> tuple[bool, str]:
    """Check 2: edge type counts + spot-check 10 random nodes."""
    edges = graph.get("edges", [])
    nodes = graph.get("nodes", [])

    # Count by type
    type_counts: dict[str, int] = {}
    for e in edges:
        etype = e.get("type", "<missing>")
        type_counts[etype] = type_counts.get(etype, 0) + 1

    related_count = type_counts.get("related", 0)
    source_ref_count = type_counts.get("source_ref", 0)
    wiki_link_count = type_counts.get("wiki_link", 0)
    total = len(edges)

    lines = [
        f"  Related edges:     {related_count}",
        f"  Source ref edges:  {source_ref_count}",
        f"  Wiki link edges:   {wiki_link_count}",
        f"  Total edges:       {total}",
    ]

    # Basic sanity: each type should have ≥1 edge
    type_present = all(
        type_counts.get(t, 0) > 0 for t in ("related", "source_ref", "wiki_link")
    )
    if not type_present:
        missing_types = [
            t
            for t in ("related", "source_ref", "wiki_link")
            if type_counts.get(t, 0) == 0
        ]
        lines.append(
            f"  {_fail()} — missing edge types: {missing_types}"
        )

    # Build look-ups for spot-check
    edges_by_source: dict[str, list[dict]] = {}
    for e in edges:
        src = e.get("source", "")
        edges_by_source.setdefault(src, []).append(e)

    node_by_id: dict[str, dict] = {n["id"]: n for n in nodes if "id" in n}

    # Pick 10 random nodes that have a corresponding file we can read
    candidates = [
        n for n in nodes
        if n.get("file_path") and (VAULT_ROOT / n["file_path"]).is_file()
    ]
    sample_size = min(10, len(candidates))
    sample_nodes = random.sample(candidates, sample_size) if candidates else []

    spot_failures: list[str] = []

    for node in sample_nodes:
        nid = node["id"]
        fpath = VAULT_ROOT / node["file_path"]
        try:
            text = fpath.read_text(encoding="utf-8")
        except Exception:
            try:
                text = fpath.read_text(encoding="utf-8-sig")
            except Exception:
                spot_failures.append(f"    Cannot read {fpath}")
                continue

        fm = _parse_frontmatter(text)
        node_edges = edges_by_source.get(nid, [])
        edge_targets_by_type: dict[str, set[str]] = {}
        for e in node_edges:
            edge_targets_by_type.setdefault(e["type"], set()).add(e["target"])

        # Check related
        yaml_related = fm.get("related", [])
        if isinstance(yaml_related, str):
            yaml_related = [yaml_related] if yaml_related else []
        if isinstance(yaml_related, list) and yaml_related:
            related_slugs = {_normalize_related_entry(r) for r in yaml_related if r}
            graph_related = edge_targets_by_type.get("related", set())
            missing_related = related_slugs - graph_related
            if missing_related:
                spot_failures.append(
                    f"    {nid}: missing related edges for {sorted(missing_related)[:5]}"
                )

        # Check source_ref
        yaml_source = fm.get("source", "")
        if isinstance(yaml_source, str) and yaml_source:
            source_stem = yaml_source.replace(".md", "")
            graph_source_refs = edge_targets_by_type.get("source_ref", set())
            if source_stem and source_stem not in graph_source_refs:
                spot_failures.append(
                    f"    {nid}: missing source_ref edge → {source_stem}"
                )

        # Check wiki_links in body
        body_links = _extract_body_wiki_links(text)
        if body_links:
            # wiki_link edges should capture body links (minus those already
            # counted as related or source_ref)
            graph_wiki = edge_targets_by_type.get("wiki_link", set())
            graph_all = set()
            for s in edge_targets_by_type.values():
                graph_all |= s
            # We only flag if zero body links are captured when many exist
            captured = sum(1 for bl in body_links if bl in graph_all)
            if captured == 0 and len(body_links) > 0:
                spot_failures.append(
                    f"    {nid}: 0/{len(body_links)} body wiki-links captured"
                )

    spot_passed = len(spot_failures) == 0
    lines.append(
        f"  Spot-check ({sample_size} nodes): {_pass() if spot_passed else _fail()}"
    )
    if spot_failures:
        for f in spot_failures[:15]:
            lines.append(f)

    overall = type_present and spot_passed
    return overall, "\n".join(lines)


def verify_schema(graph: dict) -> tuple[bool, str]:
    """Check 3: schema compliance for nodes and edges."""
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    valid_node_types = {"concept", "source", "topic"}
    valid_edge_types = {"related", "source_ref", "wiki_link"}

    node_errors: list[str] = []
    for i, n in enumerate(nodes):
        problems: list[str] = []
        if not isinstance(n.get("id"), str) or not n["id"]:
            problems.append("missing/invalid 'id'")
        if not isinstance(n.get("title"), str):
            problems.append("missing/invalid 'title'")
        if n.get("type") not in valid_node_types:
            problems.append(f"invalid type '{n.get('type')}'")
        if not isinstance(n.get("tags"), list):
            problems.append("missing/invalid 'tags' (must be array)")
        if problems:
            nid = n.get("id", f"<index {i}>")
            node_errors.append(f"    {nid}: {', '.join(problems)}")

    edge_errors: list[str] = []
    for i, e in enumerate(edges):
        problems: list[str] = []
        if not isinstance(e.get("source"), str) or not e["source"]:
            problems.append("missing/invalid 'source'")
        if not isinstance(e.get("target"), str) or not e["target"]:
            problems.append("missing/invalid 'target'")
        if e.get("type") not in valid_edge_types:
            problems.append(f"invalid type '{e.get('type')}'")
        if problems:
            edge_errors.append(f"    edge[{i}]: {', '.join(problems)}")

    valid_nodes = len(nodes) - len(node_errors)
    valid_edges = len(edges) - len(edge_errors)

    lines = [
        f"  Nodes with valid schema: {valid_nodes}/{len(nodes)}",
        f"  Edges with valid schema: {valid_edges}/{len(edges)}",
    ]

    passed = len(node_errors) == 0 and len(edge_errors) == 0
    lines.append(f"  Status: {_pass() if passed else _fail()}")
    if node_errors:
        lines.append(f"  Node errors ({len(node_errors)}):")
        for e in node_errors[:10]:
            lines.append(e)
        if len(node_errors) > 10:
            lines.append(f"    ... and {len(node_errors) - 10} more")
    if edge_errors:
        lines.append(f"  Edge errors ({len(edge_errors)}):")
        for e in edge_errors[:10]:
            lines.append(e)
        if len(edge_errors) > 10:
            lines.append(f"    ... and {len(edge_errors) - 10} more")

    return passed, "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    """Run all verification checks and return exit code (0=pass, 1=fail)."""
    print(f"\n{BOLD}=== VvC Knowledge Graph Verification ==={RESET}\n")

    # Load graph data
    if not GRAPH_DATA_PATH.exists():
        print(
            f"{RED}ERROR: {GRAPH_DATA_PATH} not found.{RESET}\n"
            "  Run parse_graph.py first to generate graph_data.json.\n"
            "  Example:  python d:/VvC_Notes/scripts/knowledge_graph/parse_graph.py"
        )
        return 1

    try:
        with open(GRAPH_DATA_PATH, encoding="utf-8") as f:
            graph = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"{RED}ERROR: graph_data.json is not valid JSON — {exc}{RESET}")
        return 1

    if not isinstance(graph, dict):
        print(f"{RED}ERROR: graph_data.json root must be a JSON object{RESET}")
        return 1

    # Collect expected files
    expected_files = count_expected_files()

    all_passed = True

    # --- Check 1: Node count ---
    print(f"{CYAN}[NODE COUNT]{RESET}")
    ok, report = verify_node_count(graph, expected_files)
    print(report)
    if not ok:
        all_passed = False
    print()

    # --- Check 2: Edge extraction ---
    print(f"{CYAN}[EDGE EXTRACTION]{RESET}")
    ok, report = verify_edge_extraction(graph)
    print(report)
    if not ok:
        all_passed = False
    print()

    # --- Check 3: Schema compliance ---
    print(f"{CYAN}[SCHEMA COMPLIANCE]{RESET}")
    ok, report = verify_schema(graph)
    print(report)
    if not ok:
        all_passed = False
    print()

    # --- Overall ---
    if all_passed:
        print(f"{BOLD}=== OVERALL: {GREEN}✅ ALL CHECKS PASSED{RESET}{BOLD} ==={RESET}\n")
        return 0
    else:
        print(f"{BOLD}=== OVERALL: {RED}❌ SOME CHECKS FAILED{RESET}{BOLD} ==={RESET}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
