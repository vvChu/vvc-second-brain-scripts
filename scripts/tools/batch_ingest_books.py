"""Batch Ingestion script for V7R01_BIGBIM and Becoming_Steve_Jobs concepts.

Applies strict v8.15.10 standards via save_concept().
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Setup paths
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))

from core.frontmatter import build_concept_frontmatter
from pipeline.post_process import save_concept

_DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_concepts(filename: str) -> list[dict[str, Any]]:
    """Load concept fixtures from JSON data file."""
    path = _DATA_DIR / filename
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


BIGBIM_CONCEPTS: list[dict[str, Any]] = _load_concepts("bigbim_concepts.json")
STEVE_JOBS_CONCEPTS: list[dict[str, Any]] = _load_concepts("steve_jobs_concepts.json")


def build_note_content(c: dict[str, Any]) -> str:
    """Construct full concept note markdown with frontmatter and body."""
    clean_tags = [t for t in c.get("tags", []) if t not in ("knowledge", "type/concept")]
    source_chapter = c.get("source_chapter") or c.get("source_chapter: ") or ""

    fm_str = build_concept_frontmatter(
        title=c["title"],
        aliases=c.get("aliases", []),
        tags=clean_tags,
        source=c["source"],
        source_type=c.get("source_type", "text"),
        source_page=str(c.get("source_page", "")),
        source_chapter=source_chapter,
        ground_truth_page=str(c.get("ground_truth_page", "")),
        ground_truth_chapter=c.get("ground_truth_chapter", ""),
        summary=c["summary"],
        people=c.get("people", []),
        companies=c.get("companies", []),
        status="growing",
        related=[],
        confidence="high",
    )

    source_stem = Path(c["source"]).stem

    body = f"""> "{c['hook']}"
> — **{c['author']}**, trích dẫn trong *{c['work']}* ([[{source_stem}|{c['work']}]])

## Core Idea

{c['core_idea']}

## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)

> "{c['ground_truth']}"

---

## References

- [[{source_stem}]]
"""
    return fm_str.strip() + "\n\n" + body.strip() + "\n"


def _ingest_concept_group(title: str, concepts: list[dict[str, Any]]) -> list[Path]:
    """Ingest a list of concepts and return successfully saved paths."""
    print(f"\n=== INGESTING {title} ===")
    saved_paths: list[Path] = []
    for c in concepts:
        note_content = build_note_content(c)
        saved = save_concept(note_content)
        if saved:
            print(f"  [SAVED] {saved.name}")
            saved_paths.append(saved)
        else:
            print(f"  [FAILED] {c['title']}")
    return saved_paths


def main():
    """Run batch ingestion for all configured book concepts."""
    bigbim_saved = _ingest_concept_group("BIGBIM CONCEPTS", BIGBIM_CONCEPTS)
    steve_saved = _ingest_concept_group("STEVE JOBS CONCEPTS", STEVE_JOBS_CONCEPTS)
    total_saved = len(bigbim_saved) + len(steve_saved)
    total_target = len(BIGBIM_CONCEPTS) + len(STEVE_JOBS_CONCEPTS)
    print(f"\nTotal concepts successfully saved: {total_saved} / {total_target}")


if __name__ == "__main__":
    main()
