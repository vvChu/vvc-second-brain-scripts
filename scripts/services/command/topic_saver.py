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

    title_match = re.search(r"^#\s+(.+)$", response, re.MULTILINE)
    if title_match:
        title = title_match.group(1).strip()
    else:
        title = clean_query[:80].strip()

    slug = normalize_stem(title)
    if not slug or len(slug) < 3:
        slug = normalize_stem(clean_query)[:50]
    if not slug:
        slug = f"topic_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Extract opening 1-2 sentences for summary (skipping H1, images, fences, and blank lines, up to 250 chars)
    summary = ""
    candidate_text = ""
    in_code_block = False
    for line in response.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if not stripped or stripped.startswith("#"):
            continue
        # Skip image embeds, horizontal rules, table rows, comments
        if stripped.startswith("![[") or stripped.startswith("!["):
            continue
        if stripped in ("---", "***", "___") or re.match(r"^[-*_]{3,}$", stripped):
            continue
        if stripped.startswith("|") or stripped.startswith("<!--"):
            continue

        clean_line = re.sub(r"^>\s*", "", stripped)
        if clean_line.startswith("[!"):
            continue

        # Strip bold/italic/link formatting for clean summary text
        clean_line = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", clean_line)
        clean_line = re.sub(r"\[\[([^\]]+)\]\]", r"\1", clean_line)
        clean_line = re.sub(r"[*_`]", "", clean_line)

        candidate_text += (" " + clean_line if candidate_text else clean_line)
        if len(candidate_text) >= 200:
            break

    if candidate_text:
        sentences = re.split(r"(?<=[.!?])\s+", candidate_text)
        first_two = " ".join(sentences[:2]).strip()
        if len(first_two) > 250:
            first_two = first_two[:247] + "..."
        summary = first_two

    # Extract up to 8 unique related wikilinks [[stem]] (excluding media, diagrams, and self)
    # 1. Strip fenced code blocks to prevent code syntax from polluting graph links
    text_without_code = re.sub(r"```.*?```", "", response, flags=re.DOTALL)
    # 2. Extract only real wikilinks (using negative lookbehind to ignore ![[embeds]])
    raw_links = re.findall(r"(?<!\!)\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]", text_without_code)
    media_exts = (
        ".webp", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".bmp",
        ".mp3", ".mp4", ".pdf", ".excalidraw.md", ".mermaid.md",
        ".d2.svg", ".excalidraw", ".mermaid", ".d2",
        ".m4a", ".wav", ".webm", ".mkv",
    )
    related_stems: list[str] = []
    seen_stems: set[str] = set()
    for link in raw_links:
        clean_stem = link.strip()
        stem_lower = clean_stem.lower()
        if any(stem_lower.endswith(ext) for ext in media_exts):
            continue
        if any(diag in stem_lower for diag in (".excalidraw", ".mermaid", ".d2")):
            continue
        if stem_lower.endswith(".md"):
            clean_stem = clean_stem[:-3]
        # Filter self-reference robustly across all case, diacritics, and slug formats
        if clean_stem == slug or normalize_stem(clean_stem) == slug:
            continue
        stem_norm = normalize_stem(clean_stem)
        if stem_norm and stem_norm not in seen_stems:
            seen_stems.add(stem_norm)
            related_stems.append(f"[[{clean_stem}]]")
            if len(related_stems) >= 8:
                break

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
