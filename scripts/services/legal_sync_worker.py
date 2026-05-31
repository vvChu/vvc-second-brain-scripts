"""VvC Second Brain — Legal Sync Worker (v7.0).

Simulates CCBA's legal document tracker by pulling legal updates
and saving them as concept notes in the permanent vault.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from core.config import cfg
from core.log import log
from core.llm import call_llm
from services.diagram_base import spawn_worker

_logger = logging.getLogger("vvc.legal_sync")

from core.prompts.services import LEGAL_CONCEPT as _LEGAL_PROMPT  # noqa: E402

def trigger_legal_sync() -> None:
    """Trigger background legal sync."""
    spawn_worker(
        target=_generate_legal_sync,
        args=(),
        name="legal-sync",
    )

def _generate_legal_sync() -> None:
    """Worker function: fetch and save legal updates."""
    _logger.info("Generating Legal Update Concept")
    log("lifecycle", "Legal Sync started")

    try:
        registry_path = Path(r"D:\GitHubProjects\ccba-agent-platform\.agent\.agent\skills\legal-document-tracker\registry\legal_registry.yaml")
        registry_data = "No registry data found."
        if registry_path.exists():
            registry_data = registry_path.read_text(encoding="utf-8")
            
        today = datetime.now().strftime("%Y-%m-%d")
        prompt = _LEGAL_PROMPT.format(date=today, registry_data=registry_data)
        
        note_content = call_llm(
            prompt,
            task="synthesis",
        )
        
        if not note_content:
            log("error", "Legal Sync generation failed")
            return
            
        note_content = note_content.strip()
        if note_content.startswith("```markdown"):
            note_content = note_content[11:]
            if note_content.endswith("```"):
                note_content = note_content[:-3]
        note_content = note_content.strip()
        
        # Save to 04 - Permanent/concepts
        filename = f"legal_update_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        output_dir = cfg.vault_root / "04 - Permanent" / "concepts"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_path = output_dir / filename
        output_path.write_text(note_content, encoding="utf-8")
            
        _logger.info(f"Legal Update saved: {filename}")
        log("lifecycle", f"Legal Sync completed: {filename}")
        
    except Exception as e:
        _logger.error(f"Legal Sync failed: {e}")
        log("error", f"Legal Sync failed: {e}")

if __name__ == "__main__":
    # Allow running as a standalone cronjob
    import sys
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    _generate_legal_sync()
