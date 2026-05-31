"""VvC Second Brain — QC Vision Auto-Audit Worker (v7.0).

Simulates CCBA's auto-audit pipeline by triggering an LLM reasoning
pass focused on QC, generating a Coordination Matrix as CSV or XLSX.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
import pandas as pd
import io

from core.config import cfg
from core.log import log
from core.llm import call_llm
from services.diagram_base import spawn_worker

_logger = logging.getLogger("vvc.vision_qc")

from core.prompts.services import QC_MATRIX as _QC_PROMPT  # noqa: E402

def trigger_qc_generation(filename: str, source_text: str, query: str) -> None:
    """Trigger background QC matrix generation."""
    spawn_worker(
        target=_generate_qc,
        args=(filename, source_text, query),
        name=f"qc-{filename}",
    )

def _generate_qc(filename: str, source_text: str, query: str) -> None:
    """Worker function: generate CSV/XLSX file."""
    _logger.info(f"Generating QC Matrix: {filename}")
    log("diagram", f"QC Matrix generation started: {filename}")

    try:
        csv_text = call_llm(
            _QC_PROMPT.format(query=query, context=source_text[:2000]),
            task="reasoning",
        )
        
        if not csv_text:
            log("error", f"QC Matrix generation failed: {filename}")
            return
            
        csv_text = csv_text.strip()
        
        # Extract from XML tags
        table_match = re.search(r"<qc_table>\s*(.*?)\s*</qc_table>", csv_text, re.DOTALL)
        if table_match:
            csv_text = table_match.group(1).strip()
            
        # Clean markdown if LLM disobeyed
        if csv_text.startswith("```"):
            csv_text = re.sub(r"^```(?:markdown|md)?\n?", "", csv_text)
            csv_text = re.sub(r"\n?```$", "", csv_text)
            
        # Parse Markdown Table into pandas dataframe
        lines = [line.strip() for line in csv_text.split('\n') if line.strip() and '|' in line]
        if len(lines) > 2:
            # Extract headers (filter out empty strings caused by leading/trailing pipes)
            headers = [col.strip() for col in lines[0].split('|') if col.strip() or col == ''][1:-1]
            if not headers:
                headers = [col.strip() for col in lines[0].split('|') if col.strip()]
                
            data = []
            for line in lines[2:]: # Skip separator line
                row = [col.strip() for col in line.split('|')[1:-1]]
                if row:
                    row += [''] * (len(headers) - len(row))
                    data.append(row[:len(headers)])
            df = pd.DataFrame(data, columns=headers)
        else:
            raise ValueError("No valid Markdown table found.")
        
        output_dir = cfg.vault_root / "03 - Resources" / "qc_report"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_path = output_dir / filename
        
        if filename.endswith(".xlsx"):
            df.to_excel(str(output_path), index=False)
        else:
            df.to_csv(str(output_path), index=False, encoding="utf-8-sig")
            
        _logger.info(f"QC Matrix saved: {filename}")
        log("diagram", f"QC Matrix created: {filename}")
        
    except Exception as e:
        _logger.error(f"QC Matrix generation failed for {filename}: {e}")
        log("error", f"QC Matrix generation failed: {e}")
