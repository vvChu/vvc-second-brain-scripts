"""VvC Second Brain — Document Generation Worker (v7.0).

Generates Word (.docx) files from LLM markdown response.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from docx import Document

from core.config import cfg
from core.log import log
from services.diagram_base import spawn_worker

_logger = logging.getLogger("vvc.doc")


def trigger_doc_generation(filename: str, source_text: str) -> None:
    """Trigger background DOCX generation.

    Args:
        filename: Filename (e.g. "report.docx").
        source_text: Full response text to convert to word.
    """
    spawn_worker(
        target=_generate_doc,
        args=(filename, source_text),
        name=f"doc-{filename}",
    )


def _generate_doc(filename: str, source_text: str) -> None:
    """Worker function: generate DOCX file."""
    _logger.info(f"Generating DOCX: {filename}")
    log("diagram", f"DOCX generation started: {filename}")

    try:
        doc = Document()
        
        # Strip the trigger tag itself to avoid putting it in the word doc
        clean_text = re.sub(r"!\[\[.*?\]\]", "", source_text)
        
        # Simple markdown to DOCX conversion
        for line in clean_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            
            # Remove blockquote styling
            if line.startswith("> "):
                line = line[2:]
            
            if line.startswith("# "):
                doc.add_heading(line[2:].strip(), level=1)
            elif line.startswith("## "):
                doc.add_heading(line[3:].strip(), level=2)
            elif line.startswith("### "):
                doc.add_heading(line[4:].strip(), level=3)
            elif line.startswith("- ") or line.startswith("* "):
                # Basic bullet list
                text = line[2:].strip()
                # Clean up bold syntax for basic text
                text = text.replace("**", "")
                doc.add_paragraph(text, style='List Bullet')
            elif re.match(r"^\d+\.\s+", line):
                # Numbered list
                text = re.sub(r"^\d+\.\s+", "", line).strip()
                text = text.replace("**", "")
                doc.add_paragraph(text, style='List Number')
            else:
                # Normal paragraph
                text = line.replace("**", "")
                doc.add_paragraph(text)

        output_dir = cfg.vault_root / "03 - Resources" / "doc"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_path = output_dir / filename
        doc.save(str(output_path))
        
        _logger.info(f"DOCX saved: {filename}")
        log("diagram", f"DOCX created: {filename}")
        
    except Exception as e:
        _logger.error(f"DOCX generation failed for {filename}: {e}")
        log("error", f"DOCX generation failed: {e}")
