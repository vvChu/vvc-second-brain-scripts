"""VvC Second Brain — Article Image HTML & Noise Parser (v8.15.13).

Provides Smart Filter heuristics and custom React/Next.js <ThemeImage> parsing
for web article diagrams.
"""

from __future__ import annotations

import re
from typing import Any

try:
    from bs4 import Tag
except ImportError:
    Tag = Any  # type: ignore[assignment,misc]

_NOISE_URL_PATTERNS = re.compile(
    r"logo|icon|avatar|emoji|button|ad[-_]|banner|tracking|pixel|"
    r"gravatar|badge|spinner|loader|social|share|comment[-_]?avatar|"
    r"widget|wp-smiley|favicon|sprite|sharer|feed|rss",
    re.IGNORECASE,
)

_NOISE_CSS_CLASSES: frozenset[str] = frozenset({
    "wp-smiley", "emoji", "avatar", "logo", "icon", "social-icon",
    "share-icon", "comment-avatar", "widget-image", "site-logo",
})

_STRUCTURAL_PARENTS: frozenset[str] = frozenset({
    "nav", "header", "footer", "aside",
})

_STRUCTURAL_KEYWORDS: frozenset[str] = frozenset({
    "sidebar", "footer", "header", "nav", "menu", "comment",
    "widget", "social", "share", "related-posts", "author-bio",
})

_MIN_DIMENSION: int = 200  # pixels — skip tiny images (avatars/icons)


def _is_noise_image(img_tag: Tag, img_url: str) -> bool:
    """Determine if an <img> tag is noise (logo, icon, tracker, etc.)."""
    if _NOISE_URL_PATTERNS.search(img_url):
        return True

    classes = set(img_tag.get("class", []))
    if classes & _NOISE_CSS_CLASSES:
        return True

    for attr in ("width", "height"):
        val = img_tag.get(attr, "")
        try:
            if val and int(val) < _MIN_DIMENSION:
                return True
        except (ValueError, TypeError):
            pass

    for parent in img_tag.parents:
        if not hasattr(parent, "name"):
            continue
        if parent.name in _STRUCTURAL_PARENTS:
            return True
        parent_id = (parent.get("id") or "").lower()
        parent_cls = " ".join(parent.get("class") or []).lower()
        combined = f"{parent_id} {parent_cls}"
        if any(kw in combined for kw in _STRUCTURAL_KEYWORDS):
            return True

    return False


def _extract_single_theme_tag(tag_content: str) -> dict[str, str] | None:
    """Extract preferred URL and alt text from a single <ThemeImage> tag."""
    urls = re.findall(r"https?://[a-zA-Z0-9_./%-]+", tag_content)
    if not urls:
        return None

    target_url = None
    for u in urls:
        if "dark" in u.lower():
            target_url = u
            break
    if not target_url:
        for u in urls:
            if "light" not in u.lower():
                target_url = u
                break
        target_url = target_url or urls[0]

    alt_match = re.search(
        r'alt\s*=\s*\\?["\'](.*?)(?:\\?["\']\s*\}|\\?["\']\s*/|\\?["\']\s*width|\\?["\']\s*height|\\?["\']\s*alt|\\?["\']\s*$|\\?["\']\s*\\u003[eE]|\\?["\']\s*>)',
        tag_content,
        re.IGNORECASE | re.DOTALL,
    )
    alt = alt_match.group(1) if alt_match else ""
    alt = alt.replace('\\"', '"').replace("\\\\", "\\").strip()

    return {"url": target_url, "alt": alt}


def _extract_custom_theme_images(html: str) -> list[dict[str, str]]:
    """Extract custom Next.js/React <ThemeImage> components using regex."""
    results: list[dict[str, str]] = []
    pattern = r"(?:<|\\u003[cC]|\\\\u003[cC])ThemeImage.*?(?:/?>|\\u003[eE]|\\\\u003[eE])"
    for match in re.finditer(pattern, html, re.IGNORECASE | re.DOTALL):
        parsed = _extract_single_theme_tag(match.group(0))
        if parsed:
            results.append(parsed)
    return results
