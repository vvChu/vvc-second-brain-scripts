"""VvC Second Brain — Command Topic Auto-Saver.

Saves substantive Command.md responses (>= 2500 chars) as Topic notes per AGENTS.md §4.6.
Separates pure content synthesis from filesystem I/O.
"""

from __future__ import annotations

from datetime import date, datetime
import logging
from pathlib import Path
import re

from core.config import cfg
from core.frontmatter import build_frontmatter, normalize_stem
from core.log import log

import services.command as _pkg

TOPIC_AUTO_SAVE_THRESHOLD = 2500

_logger = logging.getLogger("vvc.command.topic_saver")


def _get_active_cfg():
    """Retrieve active config dynamically to respect test monkeypatching."""
    return getattr(_pkg, "cfg", cfg)


def _resolve_topic_title_and_slug(clean_query: str, response: str) -> tuple[str, str]:
    """Resolve human title and unique normalized slug for topic note."""
    title_match = re.search(r"^#\s+(.+)$", response, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else clean_query[:80].strip()
    slug = normalize_stem(title)
    if not slug or len(slug) < 3:
        slug = normalize_stem(clean_query)[:50]
    if not slug:
        slug = f"topic_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return title, slug


def _extract_topic_summary(response: str) -> str:
    """Extract opening 1-2 clean sentences from response body for frontmatter summary."""
    candidate_text, in_code = "", False
    for line in response.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("![[") or stripped.startswith("!["):
            continue
        if stripped in ("---", "***", "___") or re.match(r"^[-*_]{3,}$", stripped):
            continue
        if stripped.startswith("|") or stripped.startswith("<!--"):
            continue

        clean_line = re.sub(r"^>\s*", "", stripped)
        if clean_line.startswith("[!"):
            continue

        clean_line = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", clean_line)
        clean_line = re.sub(r"\[\[([^\]]+)\]\]", r"\1", clean_line)
        clean_line = re.sub(r"[*_`]", "", clean_line)

        candidate_text += (" " + clean_line if candidate_text else clean_line)
        if len(candidate_text) >= 200:
            break

    if not candidate_text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", candidate_text)
    first_two = " ".join(sentences[:2]).strip()
    return first_two[:247] + "..." if len(first_two) > 250 else first_two


def _extract_related_wikilinks(response: str, slug: str) -> list[str]:
    """Extract up to 8 unique related wikilinks [[stem]] excluding media and self."""
    text_without_code = re.sub(r"```.*?```", "", response, flags=re.DOTALL)
    raw_links = re.findall(r"(?<!\!)\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]", text_without_code)
    media_exts = (
        ".webp", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".bmp",
        ".mp3", ".mp4", ".pdf", ".excalidraw.md", ".mermaid.md",
        ".d2.svg", ".excalidraw", ".mermaid", ".d2",
        ".m4a", ".wav", ".webm", ".mkv",
    )
    related_stems: list[str] = []
    seen: set[str] = set()
    for link in raw_links:
        clean = link.strip()
        stem_lower = clean.lower()
        if any(stem_lower.endswith(ext) for ext in media_exts) or any(
            diag in stem_lower for diag in (".excalidraw", ".mermaid", ".d2")
        ):
            continue
        if stem_lower.endswith(".md"):
            clean = clean[:-3]
        if clean == slug or normalize_stem(clean) == slug:
            continue
        stem_norm = normalize_stem(clean)
        if stem_norm and stem_norm not in seen:
            seen.add(stem_norm)
            related_stems.append(f"[[{clean}]]")
            if len(related_stems) >= 8:
                break
    return related_stems


def build_topic_content(clean_query: str, response: str) -> tuple[str, str, str] | None:
    """Build frontmatter and slug for topic note without disk I/O.

    Args:
        clean_query: User query stripped of style prefixes.
        response: Full generated response.

    Returns:
        Tuple of (title, slug, full_content) or None if response < threshold.
    """
    if len(response) < TOPIC_AUTO_SAVE_THRESHOLD:
        return None

    title, slug = _resolve_topic_title_and_slug(clean_query, response)
    summary = _extract_topic_summary(response)
    related_stems = _extract_related_wikilinks(response, slug)

    today = date.today().isoformat()
    fm_data = {
        "title": title,
        "tags": ["knowledge", "type/topic"],
        "type": "topic",
        "date_created": today,
        "date_modified": today,
        "source": "Command.md",
        "summary": summary,
        "related": related_stems,
        "status": "seed",
    }
    fm = build_frontmatter(fm_data)
    full_content = fm + "\n" + response.strip() + "\n"
    return title, slug, full_content


def save_topic_file(
    title: str,
    slug: str,
    content: str,
    base_dir: Path | None = None,
) -> Path | None:
    """Persist generated topic note content to disk.

    Args:
        title: Note title.
        slug: Normalized note stem.
        content: Full note content including frontmatter.
        base_dir: Optional root vault path (defaults to active cfg.vault_root).

    Returns:
        Path of written topic note, or None on failure.
    """
    vault_root = base_dir if base_dir is not None else _get_active_cfg().vault_root
    topics_dir = vault_root / "04 - Permanent" / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    topic_path = topics_dir / f"{slug}.md"

    if topic_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        topic_path = topics_dir / f"{slug}_{timestamp}.md"

    try:
        topic_path.write_text(content, encoding="utf-8")
        _logger.info(f"Auto-saved topic article: {topic_path.name} ({len(content)} chars)")
        log("compile", f"Auto-saved topic article: {topic_path.stem}", source="Command.md")
        return topic_path
    except OSError as e:
        _logger.error(f"Failed to auto-save topic article: {e}")
        return None


def auto_save_topic(
    clean_query: str,
    response: str,
    style_name: str,
    base_dir: Path | None = None,
) -> Path | None:
    """Compatibility wrapper: build topic content and save to disk if >= threshold.

    Args:
        clean_query: User query without style prefix.
        response: Full response text.
        style_name: Writing style used.
        base_dir: Optional root vault directory.

    Returns:
        Path to saved topic note, or None.
    """
    built = build_topic_content(clean_query, response)
    if not built:
        return None
    title, slug, full_content = built
    return save_topic_file(title, slug, full_content, base_dir=base_dir)
