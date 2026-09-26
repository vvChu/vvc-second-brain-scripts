"""VvC Second Brain — QC Vision Auto-Audit Worker (v7.0).

Simulates CCBA's auto-audit pipeline by triggering an LLM reasoning
pass focused on QC, generating a Coordination Matrix as CSV or XLSX.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    pd = None

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

def _parse_qc_markdown_table(raw_response: str) -> tuple[list[str], list[list[str]]]:
    """Parse Markdown table from LLM output into headers and rows."""
    text = raw_response.strip()
    table_match = re.search(r"<qc_table>\s*(.*?)\s*</qc_table>", text, re.DOTALL)
    if table_match:
        text = table_match.group(1).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:markdown|md)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    lines = [line.strip() for line in text.split("\n") if line.strip() and "|" in line]
    if len(lines) <= 2:
        raise ValueError("No valid Markdown table found.")

    headers = [col.strip() for col in lines[0].split("|") if col.strip() or col == ""][1:-1]
    if not headers:
        headers = [col.strip() for col in lines[0].split("|") if col.strip()]

    data = []
    for line in lines[2:]:
        row = [col.strip() for col in line.split("|")[1:-1]]
        if row:
            row += [""] * (len(headers) - len(row))
            data.append(row[: len(headers)])
    return headers, data


def _save_qc_matrix(output_path: Path, filename: str, headers: list[str], data: list[list[str]]) -> None:
    """Save parsed table data as .xlsx or .csv."""
    if filename.endswith(".xlsx"):
        if pd is None:
            raise ImportError("pandas is required for .xlsx export")
        df = pd.DataFrame(data, columns=headers)
        df.to_excel(str(output_path), index=False)
    else:
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(data)


def _generate_qc(filename: str, source_text: str, query: str) -> None:
    """Worker function: generate CSV/XLSX file."""
    _logger.info(f"Generating QC Matrix: {filename}")
    log("diagram", f"QC Matrix generation started: {filename}")

    try:
        csv_text = call_llm(
            _QC_PROMPT.format(query=query, context=source_text[:2000]),
            task="synthesis",
        )
        if not csv_text:
            log("error", f"QC Matrix generation failed: {filename}")
            return

        headers, data = _parse_qc_markdown_table(csv_text)
        output_dir = cfg.vault_root / "03 - Resources" / "qc_report"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename
        _save_qc_matrix(output_path, filename, headers, data)

        _logger.info(f"QC Matrix saved: {filename}")
        log("diagram", f"QC Matrix created: {filename}")
    except Exception as e:
        _logger.error(f"QC Matrix generation failed for {filename}: {e}")
        log("error", f"QC Matrix generation failed: {e}")
