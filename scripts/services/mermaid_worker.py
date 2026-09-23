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
    sanitize_mermaid,
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
        example_code = template.get("example", "")
        desc = template.get("description", "")
        source_ref = template.get("source", "")
        prompt += (
            f"\n\nVÍ DỤ THAM KHẢO (từ {source_ref}):\n"
            f"Loại sơ đồ phù hợp: {desc}\n"
            f"```\n{example_code.strip()}\n```\n"
            f"Hãy tham khảo cấu trúc trên, nhưng PHẢI điều chỉnh nội dung theo ngữ cảnh thực tế."
        )
        _logger.info(f"Injected template: {desc[:50]}")

    mermaid_code = call_llm(
        prompt,
        task="synthesis",
    )

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

    # Save as .mermaid.md
    md_content = f"```mermaid\n{mermaid_code}\n```\n"
    save_diagram_file(diagram_name, md_content, "mermaid")


def _clean_mermaid(raw: str) -> str:
    """Clean and validate Mermaid code."""
    raw = raw.strip()

    # Extract Mermaid block using regex to ignore any conversational text
    mermaid_match = re.search(r"```(?:mermaid)?\s*(.*?)\s*```", raw, re.DOTALL)
    if mermaid_match:
        raw = mermaid_match.group(1).strip()
    else:
        # Fallback if no markdown fences
        raw = re.sub(r"^```(?:mermaid)?\s*\n", "", raw.strip())
        raw = re.sub(r"\n```\s*$", "", raw)
        raw = raw.strip()

    # Basic validation: must start with a valid diagram type
    first_line = raw.split("\n")[0].strip().lower()
    valid_types = ["graph", "flowchart", "sequencediagram", "classDiagram",
                   "statediagram", "gantt", "pie", "mindmap", "timeline"]
    if not any(first_line.startswith(t.lower()) for t in valid_types):
        _logger.warning(f"Invalid Mermaid: doesn't start with valid type: {first_line}")
        return ""

    raw = heal_mermaid_edge_syntax(raw)
    return normalize_mermaid_direction(raw.strip())


def normalize_mermaid_direction(code: str) -> str:
    """Normalize Mermaid flowchart direction for mobile responsiveness.

    If a flowchart uses LR (Left-to-Right) layout but contains more than 3
    arrow connections (-->), automatically switch to TD (Top-Down) layout to
    prevent horizontal overflow on narrow mobile screens.

    Args:
        code: Mermaid diagram source code.

    Returns:
        Mermaid source code with direction normalized to TD if arrow count > 3.
    """
    if not code:
        return ""

    if re.search(r"\b(?:flowchart|graph)\s+LR\b", code, re.IGNORECASE):
        # Strip comments and quoted label strings to avoid false arrow matches in labels
        clean_code = re.sub(r"%%[^\n]*", "", code)
        clean_code = re.sub(r'"[^"]*"|\'[^\']*\'', "", clean_code)

        # Count directional arrow links (--> or thick ==> or dotted -.-> / -. text .->)
        arrow_count = len(re.findall(r"-->|==>|-\.->|\.->", clean_code))
        if arrow_count > 3:
            _logger.info(
                f"Normalizing Mermaid direction: detected {arrow_count} links in LR flowchart, switching to TD for mobile responsiveness."
            )
            code = re.sub(
                r"\b(flowchart|graph)\s+LR\b",
                r"\1 TD",
                code,
                count=1,
                flags=re.IGNORECASE,
            )
    return code


_normalize_mermaid_direction = normalize_mermaid_direction


def _format_mermaid_labels(code: str) -> str:
    """Sanitize and wrap labels in Mermaid nodes while preserving HTML formatting and shape delimiters."""
    def _format_content(content: str) -> str:
        is_quoted = (content.startswith('"') and content.endswith('"')) or (content.startswith("'") and content.endswith("'"))
        raw_text = content[1:-1] if is_quoted else content
        raw_text = re.sub(r"\\n|\n", "<br/>", raw_text)

        # Protect standard HTML formatting tags (<b>, <i>, <em>, <strong>, <br/>)
        preserved_tags = []
        def _save_tag(match: re.Match) -> str:
            idx = len(preserved_tags)
            preserved_tags.append(match.group(0))
            return f"__HTML_TAG_{idx}__"

        protected_text = re.sub(r"</?(?:b|i|em|strong|br)\b[^>]*>", _save_tag, raw_text, flags=re.IGNORECASE)

        parts = re.split(r"<br\s*/?>", protected_text, flags=re.IGNORECASE)
        sanitized_parts = []
        for p in parts:
            p_clean = p.strip()
            if p_clean:
                # Sanitize quotes and structural brackets inside labels
                s = p_clean.replace('"', "'")
                s = re.sub(r"[\[\]\{\}]", "", s)
                w = wrap_label(s)
                sanitized_parts.append(w)
            else:
                sanitized_parts.append("")
        
        result = "<br/>".join(sanitized_parts)
        for idx, tag in enumerate(preserved_tags):
            result = result.replace(f"__HTML_TAG_{idx}__", tag)
        return result

    pattern = re.compile(
        r"(?P<prefix>\b[a-zA-Z0-9_-]+\s*)"
        r"(?:"
        r"\(\(\(\s*(?P<double_circle>.*?)\s*\)\)\)"
        r"|\(\(\s*(?P<circle>.*?)\s*\)\)"
        r"|\(\[\s*(?P<stadium>.*?)\s*\]\)"
        r"|\[\(\s*(?P<cylinder>.*?)\s*\)\]"
        r"|\{\{\s*(?P<hexagon>.*?)\s*\}\}"
        r"|\[\/\s*(?P<parallelogram>.*?)\s*\/\]"
        r"|\[\\\\\s*(?P<parallelogram_alt>.*?)\s*\\\\\]"
        r"|\[\s*(?P<rect>[^\[\]]+?)\s*\]"
        r"|\(\s*(?P<rounded>[^()]+?)\s*\)"
        r"|\{\s*(?P<diamond>[^{}]+?)\s*\}"
        r")"
    )

    shape_wrappers = {
        "double_circle": ("(((", ")))"),
        "circle": ("((", "))"),
        "stadium": ("([", "])"),
        "cylinder": ("[(", ")]"),
        "hexagon": ("{{", "}}"),
        "parallelogram": ("[/", "/]"),
        "parallelogram_alt": ("[\\", "\\]"),
        "rect": ("[", "]"),
        "rounded": ("(", ")"),
        "diamond": ("{", "}"),
    }

    def _repl(m: re.Match) -> str:
        prefix = m.group("prefix")
        if prefix.strip().startswith(("classDef", "class ", "style", "linkStyle", "subgraph")):
            return m.group(0)
        for kind, (op, cl) in shape_wrappers.items():
            val = m.group(kind)
            if val is not None:
                formatted = _format_content(val)
                return f'{prefix}{op}"{formatted}"{cl}'
        return m.group(0)

    return pattern.sub(_repl, code)


def _apply_academic_theme_to_mermaid(mermaid_code: str) -> str:
    """Post-processor that parses the Mermaid code, preserves custom semantic classes (alert, law),
    declares consistent Academic Grayscale Theme, and assigns unassigned nodes to appropriate classes.
    """
    mermaid_code = normalize_mermaid_direction(mermaid_code)

    # 1. Extract existing class definitions and assignments to preserve custom semantic classes
    existing_class_defs = [
        line.strip() for line in mermaid_code.split("\n")
        if line.strip().startswith("classDef ")
    ]
    existing_assignments = [
        line.strip() for line in mermaid_code.split("\n")
        if line.strip().startswith("class ")
    ]

    assigned_nodes = set()
    for ass in existing_assignments:
        match = re.match(r"class\s+([^;]+?)\s+([a-zA-Z0-9_-]+);?", ass)
        if match:
            for n in match.group(1).split(","):
                assigned_nodes.add(n.strip())

    lines = [
        line for line in mermaid_code.split("\n")
        if not line.strip().startswith("classDef ") and not line.strip().startswith("class ")
    ]
    cleaned_code = "\n".join(lines)

    # Guard: ONLY apply theme if diagram type starts with flowchart or graph
    non_empty = [l.strip() for l in cleaned_code.split("\n") if l.strip() and not l.strip().startswith("%%")]
    first_line = non_empty[0].lower() if non_empty else ""
    if not (first_line.startswith("flowchart") or first_line.startswith("graph")):
        return cleaned_code

    # 2. Format labels with HTML formatting preservation
    cleaned_code = _format_mermaid_labels(cleaned_code)

    # 3. Extract subgraphs to exclude them from node classes and apply styling
    subgraph_pattern = re.compile(r"subgraph\s+([a-zA-Z0-9_-]+)")
    subgraph_ids = set(subgraph_pattern.findall(cleaned_code))

    # 4. Extract node IDs from shape declarations
    node_pattern = re.compile(r"\b([a-zA-Z0-9_-]+)\s*(?:\[.*?\]|\(.*?\)|{.*?})")
    nodes = set(node_pattern.findall(cleaned_code))

    # 5. Extract edges and additional nodes using lookahead
    edge_pattern = re.compile(
        r"\b([a-zA-Z0-9_-]+)"
        r"(?:\s*(?:\[.*?\]|\(.*?\)|{.*?}))?"
        r"\s*(-(?:\.|\-|=)+>|==>|--+|-\.-|--\s*.*?-->|-\.\s*.*?\.->)"
        r"(?:\s*\|[^|]*\|)?"
        r"\s*(?=(\b([a-zA-Z0-9_-]+)))"
    )
    edges = [(m.group(1), m.group(2), m.group(3)) for m in edge_pattern.finditer(cleaned_code)]

    for u, arrow_str, v in edges:
        if u not in subgraph_ids:
            nodes.add(u)
        if v not in subgraph_ids:
            nodes.add(v)

    # Exclude subgraph IDs from nodes
    nodes = {n for n in nodes if n not in subgraph_ids}

    if not nodes and not subgraph_ids:
        return cleaned_code

    # 6. Analyze connections to find root/hub for principal styling
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

    # Class definitions: standard academic grayscale + preserved custom classes
    class_defs = [
        "classDef principal fill:#f1f5f9,stroke:#0f172a,stroke-width:2px;",
        "classDef standard fill:#ffffff,stroke:#334155,stroke-width:1px;",
        "classDef auxiliary fill:#ffffff,stroke:#64748b,stroke-width:1px,stroke-dasharray: 5 5;"
    ]
    for cdef in existing_class_defs:
        c_name = cdef.split()[1] if len(cdef.split()) > 1 else ""
        if c_name not in ("principal", "standard", "auxiliary"):
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

    output_parts = [cleaned_code, "\n".join(class_defs)]
    if style_assignments:
        output_parts.append("\n".join(style_assignments))
    if class_assignments:
        output_parts.append("\n".join(class_assignments))

    return "\n\n".join(output_parts)

