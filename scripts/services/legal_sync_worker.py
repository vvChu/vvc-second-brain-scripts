"""VvC Second Brain — Legal Sync Worker (v7.0).

Pulls legal updates from CCBA Legal Registry and synthesizes them as
concept notes in the permanent vault via standard Quality Gate & VectorStore.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from core.config import cfg
from core.llm import call_llm
from core.log import log
from core.prompts.services import LEGAL_CONCEPT as _LEGAL_PROMPT
from pipeline.post_process import save_concept
from services.diagram_base import spawn_worker

_logger = logging.getLogger("vvc.legal_sync")


def _find_legal_registry() -> Path | None:
    """Find the legal registry yaml file in local spoke or hub platform."""
    hub_path_str = os.environ.get("CCBA_HUB_PATH", r"D:\GitHubProjects\ccba-agent-platform")  # ccba:allow-machine-path
    hub_root = Path(hub_path_str)
    candidates = [
        cfg.vault_root / ".agents" / "skills" / "ccba-legal-document-tracker" / "resources" / "legal_registry.yaml",
        hub_root / ".agents" / "skills" / "ccba-legal-document-tracker" / "resources" / "legal_registry.yaml",
        hub_root / ".md" / "data" / "legal_registry.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def trigger_legal_sync() -> None:
    """Trigger background legal sync."""
    spawn_worker(
        target=_generate_legal_sync,
        args=(),
        name="legal-sync",
    )


def _generate_legal_sync() -> None:
    """Worker function: fetch and save legal updates via standard Quality Gate."""
    _logger.info("Generating Legal Update Concept")
    log("lifecycle", "Legal Sync started")

    try:
        registry_path = _find_legal_registry()
        if not registry_path:
            _logger.warning("No CCBA Legal Registry found. Skipping legal sync.")
            log("warning", "Legal Sync skipped: registry not found")
            return

        registry_data = registry_path.read_text(encoding="utf-8")
        today = datetime.now().strftime("%Y-%m-%d")
        prompt = _LEGAL_PROMPT.format(date=today, registry_data=registry_data)

        note_content = call_llm(
            prompt,
            task="synthesis",
        )

        if not note_content:
            log("error", "Legal Sync generation failed: empty response")
            return

        note_content = note_content.strip()
        if note_content.startswith("```markdown"):
            note_content = note_content[11:]
        elif note_content.startswith("```"):
            note_content = note_content[3:]
        if note_content.endswith("```"):
            note_content = note_content[:-3]
        note_content = note_content.strip()

        # Save via pipeline.post_process to enforce Quality Gate, Snake_Case title & VectorStore hot-insert
        saved_path = save_concept(note_content, book_name="CCBA Legal Registry")
        if saved_path:
            try:
                from wiki_maintain import rebuild_incremental
                rebuild_incremental(saved_path)
            except Exception as moc_err:
                _logger.warning(f"Failed incremental MOC rebuild: {moc_err}")

            _logger.info(f"Legal Update saved: {saved_path.name}")
            log("lifecycle", f"Legal Sync completed: {saved_path.name}")
        else:
            _logger.info("Legal Update subsumed or skipped by Quality Gate / Semantic Merger.")

    except Exception as e:
        _logger.error(f"Legal Sync failed: {e}")
        log("error", f"Legal Sync failed: {e}")


if __name__ == "__main__":
    # Allow running as a standalone cronjob
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    _generate_legal_sync()
