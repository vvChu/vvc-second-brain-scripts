"""VvC Second Brain — Fallback Diagram Generator.

Generates minimal valid warning/error diagrams for Mermaid, Excalidraw,
and D2 when generation fails, preventing broken links in Obsidian.
"""

from __future__ import annotations

import html
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path

from core.config import cfg

_logger = logging.getLogger("vvc.diagram.fallback")


def sanitize_mermaid(text: str) -> str:
    """Escape characters that break Mermaid syntax."""
    return (
        text.replace('"', "'")
        .replace("(", "❨")
        .replace(")", "❩")
        .replace("[", "❲")
        .replace("]", "❳")
        .replace("{", "❴")
        .replace("}", "❵")
        .replace("<", "‹")
        .replace(">", "›")
        .replace("&", "+")
        .replace("#", "Nr")
    )


def _clean_diagram_title(diagram_name: str, extensions: tuple[str, ...]) -> str:
    """Extract clean Title Cased diagram title stripped of technical extensions."""
    clean_title = Path(diagram_name).name
    for ext in extensions:
        if clean_title.endswith(ext):
            clean_title = clean_title[: -len(ext)]
            break
    return clean_title.replace("_", " ").title()


def _render_mermaid_fallback(diagram_name: str, clean_error: str) -> str:
    """Render a minimal valid warning Mermaid diagram."""
    clean_title = _clean_diagram_title(diagram_name, (".mermaid.md", ".mermaid", ".md"))
    safe_title = sanitize_mermaid(clean_title)
    safe_error = clean_error.replace('"', "'").replace("<", "&lt;").replace(">", "&gt;")
    mermaid_code = (
        "flowchart TD\n"
        f'    err["⚠️ Không thể khởi tạo sơ đồ: {safe_title}<br/><i>{safe_error}</i>"]\n'
        "    style err fill:#fee2e2,stroke:#ef4444,stroke-width:2px,color:#991b1b;\n"
    )
    return f"```mermaid\n{mermaid_code}```\n"


def _build_fallback_card(card_id: str, text_id: str) -> dict[str, Any]:
    """Build rectangular warning card element for Excalidraw fallback."""
    return {
        "id": card_id,
        "type": "rectangle",
        "x": 100,
        "y": 100,
        "width": 380,
        "height": 100,
        "angle": 0,
        "strokeColor": "#ef4444",
        "backgroundColor": "#fee2e2",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "dashed",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "roundness": {"type": 3},
        "seed": 1000,
        "version": 1,
        "versionNonce": 1,
        "isDeleted": False,
        "boundElements": [{"id": text_id, "type": "text"}],
    }


def _build_fallback_text(card_id: str, text_id: str, text_label: str) -> dict[str, Any]:
    """Build centered warning text element bound to card container."""
    return {
        "id": text_id,
        "type": "text",
        "x": 120,
        "y": 125,
        "width": 340,
        "height": 50,
        "angle": 0,
        "strokeColor": "#991b1b",
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "roundness": None,
        "seed": 1001,
        "version": 1,
        "versionNonce": 1,
        "isDeleted": False,
        "boundElements": None,
        "text": text_label,
        "fontSize": 16,
        "fontFamily": 3,
        "textAlign": "center",
        "verticalAlign": "middle",
        "containerId": card_id,
        "originalText": text_label,
    }


def _build_excalidraw_fallback_elements(card_id: str, text_id: str, text_label: str) -> list[dict[str, Any]]:
    """Build card and bound centered text element for Excalidraw fallback."""
    return [
        _build_fallback_card(card_id, text_id),
        _build_fallback_text(card_id, text_id, text_label),
    ]


def _render_excalidraw_fallback(diagram_name: str, clean_error: str) -> str:
    """Render a minimal valid warning Excalidraw document."""
    clean_title = _clean_diagram_title(diagram_name, (".excalidraw.md", ".excalidraw", ".md"))
    card_id = "carderr1"
    text_id = "texterr1"
    text_label = f"⚠️ Sơ đồ: {clean_title}\n{clean_error}"

    elements = _build_excalidraw_fallback_elements(card_id, text_id, text_label)
    data = {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": elements,
        "appState": {"viewBackgroundColor": "#ffffff", "currentItemFontFamily": 3},
        "files": {},
    }
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    return (
        "---\n"
        "excalidraw-plugin: parsed\n"
        "tags: [excalidraw]\n"
        "---\n"
        "==⚠  Switch to EXCALIDRAW VIEW in the MORE OPTIONS menu of this document. ⚠==\n\n"
        "# Excalidraw Data\n\n"
        "## Text Elements\n"
        f"{text_label} ^{text_id}\n\n"
        "%%\n"
        "## Drawing\n"
        f"```json\n{json_str}\n```\n"
        "%%\n"
    )


def _render_d2_fallback(diagram_name: str, clean_error: str) -> tuple[str, str, str]:
    """Render fallback D2 source code and minimal standalone SVG."""
    clean_title = _clean_diagram_title(diagram_name, (".d2.svg", ".svg", ".d2"))
    if diagram_name.endswith(".d2.svg"):
        d2_filename = diagram_name[:-4]
    elif diagram_name.endswith(".svg"):
        d2_filename = diagram_name[:-4] + ".d2"
    else:
        d2_filename = f"{diagram_name}.d2"

    safe_d2_title = clean_title.replace('"', "'")
    safe_d2_error = clean_error.replace('"', "'")
    d2_code = (
        f'error: "⚠️ Không thể khởi tạo sơ đồ: {safe_d2_title}\\n{safe_d2_error}" {{\n'
        '  style: {\n'
        '    fill: "#fee2e2"\n'
        '    stroke: "#ef4444"\n'
        '  }\n'
        '}\n'
    )
    safe_svg_title = html.escape(clean_title, quote=True)
    safe_svg_error = html.escape(clean_error, quote=True)
    svg_content = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="450" height="120" viewBox="0 0 450 120">\n'
        '  <rect x="10" y="10" width="430" height="100" rx="8" fill="#fee2e2" stroke="#ef4444" stroke-width="2" stroke-dasharray="4 4"/>\n'
        f'  <text x="225" y="50" font-family="sans-serif" font-size="14" font-weight="bold" fill="#991b1b" text-anchor="middle">⚠️ Sơ đồ D2: {safe_svg_title}</text>\n'
        f'  <text x="225" y="75" font-family="sans-serif" font-size="12" fill="#7f1d1d" text-anchor="middle">{safe_svg_error}</text>\n'
        '</svg>\n'
    )
    return d2_filename, d2_code, svg_content


def save_fallback_diagram(
    diagram_name: str,
    error_reason: str,
    diagram_type: str,
    save_fn: Callable[[str, str, str], None],
    attachments_dir: Path | None = None,
) -> None:
    """Save a minimal, valid warning diagram file to prevent broken links in Obsidian."""
    clean_error = error_reason.replace('"', "'").strip()
    dtype = diagram_type.lower()
    target_dir = attachments_dir or cfg.attachments_dir

    if dtype == "mermaid":
        save_fn(diagram_name, _render_mermaid_fallback(diagram_name, clean_error), "mermaid")
    elif dtype == "excalidraw":
        save_fn(diagram_name, _render_excalidraw_fallback(diagram_name, clean_error), "excalidraw")
    elif dtype == "d2":
        d2_filename, d2_code, svg_content = _render_d2_fallback(diagram_name, clean_error)
        safe_d2_filename = re.sub(r'[<>:"/\\|?*]', "_", d2_filename)
        try:
            d2_path = target_dir / safe_d2_filename
            d2_path.parent.mkdir(parents=True, exist_ok=True)
            d2_path.write_text(d2_code, encoding="utf-8")
        except OSError:
            pass
        save_fn(diagram_name, svg_content, "d2")
    else:
        _logger.warning(f"Unknown diagram type for fallback: {diagram_type}")
