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
from services.diagram_base import find_diagram_context, spawn_worker, save_diagram_file, select_template

_logger = logging.getLogger("vvc.mermaid")

_MERMAID_PROMPT = """Tạo sơ đồ Mermaid cho nội dung sau:

NGỮ CẢNH:
{context}

QUY TẮC:
1. Chỉ trả về mã Mermaid (KHÔNG có ```mermaid fences, không giải thích gì thêm)
2. Dùng tiếng Việt cho labels khi phù hợp
3. Ưu tiên flowchart TD (Top-Down) cho sơ đồ cây/phân cấp hoặc flowchart LR (Left-to-Right) cho các chuỗi tuyến tính/tiến trình
4. Dùng dấu ngoặc kép cho labels chứa ký tự đặc biệt: id["Label (info)"]
5. KHÔNG dùng HTML tags trong labels
6. Giữ sơ đồ gọn gàng, tối đa 15-20 nodes
7. Cấu trúc rõ ràng, sử dụng các kết nối nét liền (-->), nét đậm (==>) hoặc nét đứt (-.->) để thể hiện mối quan hệ chính phụ.
8. CHỌN ĐÚNG LOẠI SƠ ĐỒ theo nội dung:
   - `flowchart TD`: phân cấp, cây tổ chức, phân rã khái niệm
   - `flowchart LR`: chuỗi tiến trình, pipeline, value chain ngang
   - `timeline`: diễn biến theo thời gian, giai đoạn phát triển, lịch sử tiến hóa (VD: Strategy evolution qua các thập kỷ)
   - `pie`: phân bổ tỷ lệ, cơ cấu thành phần, breakdown phần trăm (VD: 6 hợp phần EOS)
   - `mindmap`: brainstorm, phân nhánh ý tưởng từ 1 chủ đề trung tâm
   - `graph TD`: quan hệ đa chiều không phân cấp rõ ràng
9. TEXT WRAPPING — BẮT BUỘC để đảm bảo text hiển thị đầy đủ trong node:
   - Mỗi dòng trong label TỐI ĐA 20 ký tự (kể cả dấu cách)
   - Dùng \\n để xuống dòng khi label dài hơn 20 ký tự
   - Ví dụ ĐÚNG:  A["Nhận diện\\nbối cảnh\\nthị trường"]
   - Ví dụ SAI:   A["Nhận diện bối cảnh thị trường và môi trường kinh doanh"]
   - Với `timeline` và `pie`: không cần \\n vì Mermaid tự wrap
"""


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
        task="reasoning",
    )

    if not mermaid_code:
        log("error", f"Mermaid generation failed: {diagram_name}")
        return

    # Clean up output
    mermaid_code = _clean_mermaid(mermaid_code)

    if not mermaid_code:
        log("error", f"Mermaid validation failed: {diagram_name}")
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

    return raw.strip()


def _apply_academic_theme_to_mermaid(mermaid_code: str) -> str:
    """Post-processor that parses the Mermaid code, strips any inline custom classes,
    declares a consistent Academic Grayscale Theme, and assigns nodes to their respective classes.
    """
    # 1. Clean existing class declarations to avoid conflicts
    lines = [line for line in mermaid_code.split("\n") if "classDef" not in line and not line.strip().startswith("class ")]
    cleaned_code = "\n".join(lines)
    
    # 2. Extract node IDs from the code using regex
    # Matches node definitions like a["text"] or b(text) or c{text}
    node_pattern = re.compile(r"\b([a-zA-Z0-9_-]+)\s*(?:\[.*?\]|\(.*?\)|{.*?})")
    nodes = set(node_pattern.findall(cleaned_code))
    
    if not nodes:
        # Fallback: extract anything that looks like an ID in arrows: a --> b
        arrow_pattern = re.compile(r"\b([a-zA-Z0-9_-]+)\s*[-=~.]+")
        nodes = set(arrow_pattern.findall(cleaned_code))
        
    if not nodes:
        return cleaned_code

    # 3. Analyze connections to find root/hub for principal styling
    in_degrees = {n: 0 for n in nodes}
    out_degrees = {n: 0 for n in nodes}
    
    # Matches a --> b, a ==> b or a -.-> b
    edge_pattern = re.compile(r"\b([a-zA-Z0-9_-]+)\s*(?:-->|==>|-\.-\.>)\s*\b([a-zA-Z0-9_-]+)\b")
    edges = edge_pattern.findall(cleaned_code)
    for u, v in edges:
        if u in nodes and v in nodes:
            out_degrees[u] += 1
            in_degrees[v] += 1
            
    # Find root (in-degree == 0, or max out-degree if none)
    roots = [n for n in nodes if in_degrees[n] == 0]
    if len(roots) == 1:
        principal_node = roots[0]
    elif len(roots) > 1:
        principal_node = max(roots, key=lambda n: out_degrees[n])
    else:
        # Cycle or complex flow: pick the node with max total degree
        principal_node = max(nodes, key=lambda n: in_degrees[n] + out_degrees[n])
        
    # Find auxiliary nodes (connected by dashed arrows -.-> or containing auxiliary keywords)
    auxiliary_nodes = set()
    dashed_edge_pattern = re.compile(r"\b([a-zA-Z0-9_-]+)\s*-\.-\.>\s*\b([a-zA-Z0-9_-]+)\b")
    dashed_edges = dashed_edge_pattern.findall(cleaned_code)
    for u, v in dashed_edges:
        if v in nodes:
            auxiliary_nodes.add(v)
            
    # Assemble class assignments at the end of the file (Tail-end CSS assignment)
    class_assignments = []
    for nid in nodes:
        if nid == principal_node:
            class_assignments.append(f"class {nid} principal;")
        elif nid in auxiliary_nodes:
            class_assignments.append(f"class {nid} auxiliary;")
        else:
            class_assignments.append(f"class {nid} standard;")
            
    # Academic Book Grayscale class definitions
    class_defs = [
        "classDef principal fill:#f1f5f9,stroke:#0f172a,stroke-width:2px;",
        "classDef standard fill:#ffffff,stroke:#334155,stroke-width:1px;",
        "classDef auxiliary fill:#ffffff,stroke:#64748b,stroke-width:1px,stroke-dasharray: 5 5;"
    ]
    
    return cleaned_code + "\n\n" + "\n".join(class_defs) + "\n" + "\n".join(class_assignments)
