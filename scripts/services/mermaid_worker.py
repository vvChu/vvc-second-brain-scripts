"""VvC Second Brain — Mermaid Worker (v8.0 — Template-Enhanced).

Generates Mermaid diagrams via LLM. Saves as .mermaid.md for Obsidian native rendering.

Usage:
    from services.mermaid_worker import trigger_mermaid_generation
    trigger_mermaid_generation("flow.mermaid.md", context_text)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from core.config import cfg
from core.llm import call_llm
from core.log import log
from services.diagram_base import (
    find_diagram_context,
    save_diagram_file,
    save_fallback_diagram,
    select_template,
    spawn_worker,
    wrap_label,
)

_logger = logging.getLogger("vvc.mermaid")

from core.prompts.services import MERMAID_GENERATE as _MERMAID_PROMPT  # noqa: E402
from core.markdown_sanitizer import heal_mermaid_edge_syntax  # noqa: E402

__all__ = [
    "trigger_mermaid_generation",
    "normalize_mermaid_direction",
    "_normalize_mermaid_direction",
    "_clean_mermaid",
    "_apply_academic_theme_to_mermaid",
]


def trigger_mermaid_generation(diagram_name: str, source_text: str) -> None:
    """Trigger background Mermaid diagram generation."""
    spawn_worker(
        target=_generate_mermaid,
        args=(diagram_name, source_text),
        name=f"mermaid-{diagram_name}",
    )


def _generate_mermaid(diagram_name: str, source_text: str) -> None:
    """Worker function: generate Mermaid diagram with template-enhanced prompting."""
    context = find_diagram_context(diagram_name, source_text)

    _logger.info(f"Generating Mermaid: {diagram_name}")
    log("diagram", f"Mermaid generation started: {diagram_name}")

    # Dynamic template injection via embedding similarity
    prompt = _MERMAID_PROMPT.format(context=context)
    template = select_template(context, diagram_type="mermaid")
    if template:
        desc = template.get("description", "")
        prompt += (
            f"\n\nVÍ DỤ THAM KHẢO (từ {template.get('source', '')}):\n"
            f"Loại sơ đồ phù hợp: {desc}\n```{template.get('example', '').strip()}```\n"
            f"Hãy tham khảo cấu trúc trên, nhưng PHẢI điều chỉnh nội dung theo ngữ cảnh thực tế."
        )
        _logger.info(f"Injected template: {desc[:50]}")

    mermaid_code = call_llm(prompt, task="synthesis")
    if not mermaid_code:
        log("error", f"Mermaid generation failed: {diagram_name}")
        save_fallback_diagram(diagram_name, "Lỗi kết nối hoặc LLM không trả về phản hồi", "mermaid")
        return

    # Clean up output
    mermaid_code = _clean_mermaid(mermaid_code)
    if not mermaid_code:
        log("error", f"Mermaid validation failed: {diagram_name}")
        save_fallback_diagram(diagram_name, "Lỗi cú pháp Mermaid không hợp lệ", "mermaid")
        return

    # Post-process to automatically inject Grayscale Academic Theme classDefs & assignments
    mermaid_code = _apply_academic_theme_to_mermaid(mermaid_code)
    save_diagram_file(diagram_name, f"```mermaid\n{mermaid_code}\n```\n", "mermaid")


def _clean_mermaid(raw: str) -> str:
    """Clean and validate Mermaid code."""
    raw = raw.strip()
    m = re.search(r"```(?:mermaid)?\s*(.*?)\s*```", raw, re.DOTALL)
    raw = m.group(1).strip() if m else re.sub(r"^```(?:mermaid)?\s*\n|\n```\s*$", "", raw).strip()

    valid_types = ("graph", "flowchart", "sequencediagram", "classdiagram", "statediagram", "gantt", "pie", "mindmap", "timeline")
    first_line = raw.split("\n")[0].strip().lower()
    if not any(first_line.startswith(t) for t in valid_types):
        _logger.warning(f"Invalid Mermaid: doesn't start with valid type: {first_line}")
        return ""

    return normalize_mermaid_direction(heal_mermaid_edge_syntax(raw).strip())


def normalize_mermaid_direction(code: str) -> str:
    """Normalize Mermaid flowchart direction for mobile responsiveness."""
    if not code:
        return ""

    if re.search(r"\b(?:flowchart|graph)\s+LR\b", code, re.IGNORECASE):
        clean_code = re.sub(r"%%[^\n]*|\"[^\"]*\"|'[^']*'", "", code)
        arrow_count = len(re.findall(r"-->|==>|-\.->|\.->", clean_code))
        if arrow_count > 3:
            _logger.info(f"Normalizing Mermaid direction: {arrow_count} links in LR flowchart -> TD")
            code = re.sub(r"\b(flowchart|graph)\s+LR\b", r"\1 TD", code, count=1, flags=re.IGNORECASE)
    return code


_normalize_mermaid_direction = normalize_mermaid_direction


_MERMAID_SHAPE_PATTERN = re.compile(
    r"(?P<prefix>\b[a-zA-Z0-9_-]+\s*)(?:"
    r"\(\(\(\s*(?P<double_circle>.*?)\s*\)\)\)|\(\(\s*(?P<circle>.*?)\s*\)\)|"
    r"\(\[\s*(?P<stadium>.*?)\s*\]\)|\[\(\s*(?P<cylinder>.*?)\s*\)\]|"
    r"\{\{\s*(?P<hexagon>.*?)\s*\}\}|\[\/\s*(?P<parallelogram>.*?)\s*\/\]|"
    r"\[\\\\\s*(?P<parallelogram_alt>.*?)\s*\\\\\]|\[\s*(?P<rect>[^\[\]]+?)\s*\]|"
    r"\(\s*(?P<rounded>[^()]+?)\s*\)|\{\s*(?P<diamond>[^{}]+?)\s*\})"
)

_MERMAID_SHAPE_WRAPPERS = {
    "double_circle": ("(((", ")))"), "circle": ("((", "))"), "stadium": ("([", "])"),
    "cylinder": ("[(", ")]"), "hexagon": ("{{", "}}"), "parallelogram": ("[/", "/]"),
    "parallelogram_alt": ("[\\", "\\]"), "rect": ("[", "]"), "rounded": ("(", ")"), "diamond": ("{", "}"),
}


def _format_mermaid_node_content(content: str) -> str:
    """Sanitize and wrap single node content string preserving allowed HTML tags."""
    is_quoted = (content.startswith('"') and content.endswith('"')) or (content.startswith("'") and content.endswith("'"))
    raw_text = content[1:-1] if is_quoted else content
    raw_text = re.sub(r"\\n|\n", "<br/>", raw_text)

    preserved_tags: list[str] = []
    def _save_tag(match: re.Match) -> str:
        idx = len(preserved_tags)
        preserved_tags.append(match.group(0))
        return f"__HTML_TAG_{idx}__"

    protected = re.sub(r"</?(?:b|i|em|strong|br)\b[^>]*>", _save_tag, raw_text, flags=re.IGNORECASE)
    parts = re.split(r"<br\s*/?>", protected, flags=re.IGNORECASE)
    sanitized_parts = []
    for p in parts:
        p_clean = p.strip()
        if p_clean:
            s = p_clean.replace('"', "'")
            s = re.sub(r"[\[\]\{\}]", "", s)
            sanitized_parts.append(wrap_label(s))
        else:
            sanitized_parts.append("")

    result = "<br/>".join(sanitized_parts)
    for idx, tag in enumerate(preserved_tags):
        result = result.replace(f"__HTML_TAG_{idx}__", tag)
    return result


def _format_mermaid_labels(code: str) -> str:
    """Sanitize and wrap labels in Mermaid nodes while preserving HTML formatting and shape delimiters."""
    def _repl(m: re.Match) -> str:
        prefix = m.group("prefix")
        if prefix.strip().startswith(("classDef", "class ", "style", "linkStyle", "subgraph")):
            return m.group(0)
        for kind, (op, cl) in _MERMAID_SHAPE_WRAPPERS.items():
            val = m.group(kind)
            if val is not None:
                return f'{prefix}{op}"{_format_mermaid_node_content(val)}"{cl}'
        return m.group(0)

    return _MERMAID_SHAPE_PATTERN.sub(_repl, code)


def _extract_mermaid_topology(
    code: str,
) -> tuple[set[str], set[str], list[tuple[str, str, str]]]:
    """Extract subgraph IDs, node IDs, and directed edges from Mermaid code."""
    subgraph_ids = set(re.findall(r"subgraph\s+([a-zA-Z0-9_-]+)", code))
    node_pattern = re.compile(r"\b([a-zA-Z0-9_-]+)\s*(?:\[.*?\]|\(.*?\)|{.*?})")
    nodes = set(node_pattern.findall(code))

    edge_pattern = re.compile(
        r"\b([a-zA-Z0-9_-]+)"
        r"(?:\s*(?:\[.*?\]|\(.*?\)|{.*?}))?"
        r"\s*(-(?:\.|\-|=)+>|==>|--+|-\.-|--\s*.*?-->|-\.\s*.*?\.->)"
        r"(?:\s*\|[^|]*\|)?"
        r"\s*(?=(\b([a-zA-Z0-9_-]+)))"
    )
    edges = [(m.group(1), m.group(2), m.group(3)) for m in edge_pattern.finditer(code)]
    for u, _, v in edges:
        if u not in subgraph_ids:
            nodes.add(u)
        if v not in subgraph_ids:
            nodes.add(v)

    return subgraph_ids, {n for n in nodes if n not in subgraph_ids}, edges


def _find_principal_and_auxiliary_nodes(
    nodes: set[str], edges: list[tuple[str, str, str]]
) -> tuple[str | None, set[str]]:
    """Determine the root/hub principal node and set of auxiliary nodes."""
    in_degrees = {n: 0 for n in nodes}
    out_degrees = {n: 0 for n in nodes}
    auxiliary_nodes = set()

    for u, arrow_str, v in edges:
        if u in nodes and v in nodes:
            if ">" in arrow_str:
                out_degrees[u] += 1
                in_degrees[v] += 1
            else:
                out_degrees[u] += 1
                out_degrees[v] += 1
            if "-.-" in arrow_str or "-." in arrow_str:
                auxiliary_nodes.add(v)

    principal_node = None
    if nodes:
        roots = [n for n in nodes if in_degrees[n] == 0]
        if len(roots) == 1:
            principal_node = roots[0]
        elif len(roots) > 1:
            principal_node = max(roots, key=lambda n: out_degrees[n])
        else:
            principal_node = max(nodes, key=lambda n: in_degrees[n] + out_degrees[n])

    return principal_node, auxiliary_nodes


def _build_academic_theme_blocks(
    subgraph_ids: set[str],
    nodes: set[str],
    assigned_nodes: set[str],
    principal_node: str | None,
    auxiliary_nodes: set[str],
    existing_class_defs: list[str],
    existing_assignments: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Construct class definitions, style assignments, and node class mappings."""
    class_defs = [
        "classDef principal fill:#f1f5f9,stroke:#0f172a,stroke-width:2px;",
        "classDef standard fill:#ffffff,stroke:#334155,stroke-width:1px;",
        "classDef auxiliary fill:#ffffff,stroke:#64748b,stroke-width:1px,stroke-dasharray: 5 5;",
    ]
    for cdef in existing_class_defs:
        parts = cdef.split()
        if len(parts) > 1 and parts[1] not in ("principal", "standard", "auxiliary"):
            class_defs.append(cdef)

    style_assignments = [
        f"style {sg_id} fill:#f8fafc,stroke:#334155,stroke-width:1px;"
        for sg_id in sorted(subgraph_ids)
    ]

    class_assignments = list(existing_assignments)
    for nid in sorted(nodes):
        if nid in assigned_nodes:
            continue
        if nid == principal_node:
            class_assignments.append(f"class {nid} principal;")
        elif nid in auxiliary_nodes:
            class_assignments.append(f"class {nid} auxiliary;")
        else:
            class_assignments.append(f"class {nid} standard;")

    return class_defs, style_assignments, class_assignments


def _apply_academic_theme_to_mermaid(mermaid_code: str) -> str:
    """Post-processor that parses Mermaid code, preserves custom semantic classes (alert, law),
    declares consistent Academic Grayscale Theme, and assigns unassigned nodes to appropriate classes.
    """
    mermaid_code = normalize_mermaid_direction(mermaid_code)

    existing_class_defs = [l.strip() for l in mermaid_code.split("\n") if l.strip().startswith("classDef ")]
    existing_assignments = [l.strip() for l in mermaid_code.split("\n") if l.strip().startswith("class ")]

    assigned_nodes = set()
    for ass in existing_assignments:
        match = re.match(r"class\s+([^;]+?)\s+([a-zA-Z0-9_-]+);?", ass)
        if match:
            for n in match.group(1).split(","):
                assigned_nodes.add(n.strip())

    cleaned_lines = [
        l for l in mermaid_code.split("\n")
        if not l.strip().startswith("classDef ") and not l.strip().startswith("class ")
    ]
    cleaned_code = "\n".join(cleaned_lines)

    non_empty = [l.strip() for l in cleaned_code.split("\n") if l.strip() and not l.strip().startswith("%%")]
    first_line = non_empty[0].lower() if non_empty else ""
    if not (first_line.startswith("flowchart") or first_line.startswith("graph")):
        return cleaned_code

    cleaned_code = _format_mermaid_labels(cleaned_code)
    subgraph_ids, nodes, edges = _extract_mermaid_topology(cleaned_code)
    if not nodes and not subgraph_ids:
        return cleaned_code

    principal_node, auxiliary_nodes = _find_principal_and_auxiliary_nodes(nodes, edges)
    class_defs, style_assignments, class_assignments = _build_academic_theme_blocks(
        subgraph_ids, nodes, assigned_nodes, principal_node, auxiliary_nodes,
        existing_class_defs, existing_assignments,
    )

    output_parts = [cleaned_code, "\n".join(class_defs)]
    if style_assignments:
        output_parts.append("\n".join(style_assignments))
    if class_assignments:
        output_parts.append("\n".join(class_assignments))

    return "\n\n".join(output_parts)

