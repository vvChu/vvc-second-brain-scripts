"""VvC Second Brain — YAML Frontmatter Utilities (v7.0).

Centralized parse/build/extract for Obsidian YAML frontmatter.
This is the SOLE owner of frontmatter manipulation — no inline regex allowed elsewhere.

Usage:
    from core.frontmatter import parse_frontmatter, build_frontmatter, extract_body
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import yaml

try:
    from yaml import CSafeLoader as _SafeLoader
except ImportError:
    from yaml import SafeLoader as _SafeLoader

# Regex to match YAML frontmatter block (supporting both LF and CRLF)
_FM_PATTERN = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?", re.DOTALL)


def parse_frontmatter(content: str) -> dict[str, Any]:
    """Extract YAML frontmatter from markdown content.

    Args:
        content: Full markdown file content.

    Returns:
        Parsed frontmatter dict, or empty dict if no frontmatter found.
    """
    content = content.lstrip("\ufeff")
    match = _FM_PATTERN.match(content)
    if not match:
        return {}
    try:
        return yaml.load(match.group(1), Loader=_SafeLoader) or {}
    except yaml.YAMLError:
        return {}


def extract_body(content: str) -> str:
    """Extract the body (everything after frontmatter) from markdown.

    Args:
        content: Full markdown file content.

    Returns:
        Body content without frontmatter.
    """
    content = content.lstrip("\ufeff")
    match = _FM_PATTERN.match(content)
    if not match:
        return content
    return content[match.end():]


def build_frontmatter(data: dict[str, Any]) -> str:
    """Build YAML frontmatter string from a dict.

    Args:
        data: Frontmatter fields.

    Returns:
        Formatted '---\\n...\\n---\\n' string.
    """
    # Use default_flow_style=False for readable YAML
    # allow_unicode=True for Vietnamese characters
    yaml_str = yaml.dump(
        data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )
    return f"---\n{yaml_str}---\n"


def build_concept_frontmatter(
    title: str,
    *,
    aliases: list[str] | None = None,
    tags: list[str] | None = None,
    source: str = "",
    source_type: str = "image",
    source_page: str = "",
    source_chapter: str = "",
    ground_truth_page: str = "",
    ground_truth_chapter: str = "",
    summary: str = "",
    people: list[str] | None = None,
    companies: list[str] | None = None,
    status: str = "seed",
    related: list[str] | None = None,
    confidence: str = "high",
) -> str:
    """Build standardized concept note frontmatter.

    Args:
        title: Concept title (Vietnamese).
        aliases: Alternative names.
        tags: Obsidian tags (should include domain/ prefix).
        source: Source note reference.
        source_type: image | pdf | epub | text | manual | compiled.
        source_page: Page number from source.
        source_chapter: Chapter reference.
        ground_truth_page: Page number from English Ground Truth.
        ground_truth_chapter: Chapter reference from English Ground Truth.
        summary: 2-3 sentence summary.
        people: Related humans (entities).
        companies: Related organizations (entities).
        status: seed | growing | evergreen.
        related: Wiki-link references.
        confidence: high | medium | low.

    Returns:
        Formatted frontmatter string.
    """
    today = date.today().isoformat()
    data = {
        "title": title,
        "aliases": aliases or [],
        "tags": ["knowledge", "type/concept"] + (tags or []),
        "type": "concept",
        "date_created": today,
        "date_modified": today,
        "source": source,
        "source_page": source_page,
        "source_chapter": source_chapter,
        "ground_truth_page": ground_truth_page,
        "ground_truth_chapter": ground_truth_chapter,
        "source_type": source_type,
        "summary": summary,
        "people": people or [],
        "companies": companies or [],
        "status": status,
        "related": related or [],
        "confidence": confidence,
    }
    return build_frontmatter(data)


def update_field(content: str, field_name: str, value: Any) -> str:
    """Update a single field in existing frontmatter.

    Args:
        content: Full markdown file content.
        field_name: YAML field to update.
        value: New value for the field.

    Returns:
        Updated markdown content.
    """
    frontmatter = parse_frontmatter(content)
    if not frontmatter:
        return content
    frontmatter[field_name] = value
    body = extract_body(content)
    return build_frontmatter(frontmatter) + body


def normalize_stem(name: str) -> str:
    """Normalize a filename stem for consistent matching.

    Strips whitespace, removes Vietnamese accents, collapses multiple underscores, lowercases.

    Args:
        name: Raw filename stem.

    Returns:
        Normalized stem string.
    """
    import unicodedata
    
    # Manually replace Vietnamese d/D because NFKD does not decompose them
    name = name.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize('NFKD', name)
    name = normalized.encode('ascii', 'ignore').decode('ascii')
    
    name = re.sub(r"[^a-zA-Z0-9]+", "_", name.lower())
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")
    return name
