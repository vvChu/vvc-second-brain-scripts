"""VvC Second Brain — Article Image Extractor (v8.9.6).

Downloads, filters, and compresses article images locally for Obsidian embedding.
Smart Filter heuristics exclude noise (logos, icons, trackers, navigation).
Saves to ``04 - Permanent/sources/assets/<domain>/`` as WebP.

Usage::

    from services.article_images import extract_article_images, format_image_metadata
    images = extract_article_images(html, "https://example.com/article")
    metadata_text = format_image_metadata(images)
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlparse

from core.config import cfg
from core.frontmatter import normalize_stem

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment,misc]
    Tag = None  # type: ignore[assignment,misc]

try:
    import requests as _requests
except ImportError:
    _requests = None  # type: ignore[assignment]

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None  # type: ignore[assignment]

_logger = logging.getLogger("vvc.article_images")

# ---------------------------------------------------------------------------
# Smart Filter Constants
# ---------------------------------------------------------------------------

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

MAX_IMAGES_PER_ARTICLE: int = 20
_MIN_IMAGE_SIZE_BYTES: int = 5_000       # 5 KB minimum download size
_MIN_DIMENSION: int = 200                # pixels — skip tiny images (avatars/icons)
_DOWNLOAD_TIMEOUT: int = 10             # seconds per image request
_MAX_DOWNLOAD_WORKERS: int = 5
_MIN_IMAGES_THRESHOLD: int = 1           # allow single high-value diagrams


# ---------------------------------------------------------------------------
# Smart Filter
# ---------------------------------------------------------------------------

def _extract_custom_theme_images(html: str) -> list[dict[str, str]]:
    """Extract custom Next.js/React <ThemeImage> components using regex.

    Supports both raw HTML/JSX tags and escaped JSX strings in JS/JSON payloads.
    Returns a list of dicts with 'url' and 'alt'.
    """
    results = []
    # Pattern matches <ThemeImage or \u003cThemeImage or \\u003cThemeImage and goes until > or \u003e or \\u003e
    matches = re.finditer(
        r'(?:<|\\u003[cC]|\\\\u003[cC])ThemeImage.*?(?:/?>|\\u003[eE]|\\\\u003[eE])',
        html,
        re.IGNORECASE | re.DOTALL
    )
    for match in matches:
        tag_content = match.group(0)
        
        # Extract all http/https URLs inside this tag content
        urls = re.findall(r'https?://[a-zA-Z0-9_./%-]+', tag_content)
        if not urls:
            continue
            
        # Prioritise the dark mode URL for dark mode vault compatibility
        target_url = None
        for u in urls:
            if "dark" in u.lower():
                target_url = u
                break
        
        if not target_url:
            # Fallback: search for any URL that doesn't contain "light" or just pick the first one
            for u in urls:
                if "light" not in u.lower():
                    target_url = u
                    break
            if not target_url:
                target_url = urls[0]
                
        # Alt extraction: match alt="something" or alt=\"something\"
        alt_match = re.search(
            r'alt\s*=\s*\\?["\'](.*?)(?:\\?["\']\s*\}|\\?["\']\s*/|\\?["\']\s*width|\\?["\']\s*height|\\?["\']\s*alt|\\?["\']\s*$|\\?["\']\s*\\u003[eE]|\\?["\']\s*>)',
            tag_content,
            re.IGNORECASE | re.DOTALL
        )
        alt = alt_match.group(1) if alt_match else ""
        alt = alt.replace('\\"', '"').replace('\\\\', '\\').strip()
        
        results.append({
            "url": target_url,
            "alt": alt,
        })
        
    return results


def _is_noise_image(img_tag: Tag, img_url: str) -> bool:
    """Determine if an ``<img>`` tag is noise (logo, icon, tracker, etc.).

    Args:
        img_tag: BeautifulSoup Tag object.
        img_url: Fully resolved image URL.

    Returns:
        True if the image should be excluded.
    """
    # 1. URL pattern check
    if _NOISE_URL_PATTERNS.search(img_url):
        return True

    # 2. CSS class check
    classes = set(img_tag.get("class", []))
    if classes & _NOISE_CSS_CLASSES:
        return True

    # 3. Dimension check from HTML attributes
    for attr in ("width", "height"):
        val = img_tag.get(attr, "")
        try:
            if val and int(val) < _MIN_DIMENSION:
                return True
        except (ValueError, TypeError):
            pass

    # 4. Structural parent check (nav, header, footer, sidebar)
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


# ---------------------------------------------------------------------------
# Filename generation
# ---------------------------------------------------------------------------

def _make_image_filename(url: str, domain_slug: str, seen: set[str]) -> str:
    """Generate a unique, normalised filename (WebP, or SVG if original was SVG).

    Args:
        url: Original image URL.
        domain_slug: Sanitised domain prefix (e.g. ``waitbutwhy``).
        seen: Set of filenames already generated (mutated in-place for dedup).

    Returns:
        Unique filename like ``waitbutwhy_software_want_box.webp`` or ``.svg``.
    """
    parsed = urlparse(url)
    is_svg = parsed.path.lower().endswith(".svg")
    ext = ".svg" if is_svg else ".webp"
    
    basename = Path(parsed.path).stem
    normalised = normalize_stem(basename)
    if len(normalised) > 40:
        normalised = normalised[:40].rsplit("_", 1)[0]

    candidate = f"{domain_slug}_{normalised}{ext}"

    # Collision prevention
    if candidate in seen:
        suffix = 2
        while f"{domain_slug}_{normalised}_{suffix}{ext}" in seen:
            suffix += 1
        candidate = f"{domain_slug}_{normalised}_{suffix}{ext}"

    seen.add(candidate)
    return candidate


# ---------------------------------------------------------------------------
# Download & compress
# ---------------------------------------------------------------------------

def _download_and_compress(url: str, save_path: Path) -> bool:
    """Download a single image, saving SVGs directly and compressing others to WebP.

    Args:
        url: Image URL.
        save_path: Local path to write the file (WebP or SVG).

    Returns:
        True on success.
    """
    if _requests is None:
        return False
    try:
        resp = _requests.get(
            url, timeout=_DOWNLOAD_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()

        is_svg = save_path.suffix.lower() == ".svg"

        # Bypass size checks and Pillow for SVGs
        if is_svg:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(resp.content)
            return True

        # Check size limit for standard images
        if len(resp.content) < _MIN_IMAGE_SIZE_BYTES:
            return False

        if PILImage is None:
            return False

        img = PILImage.open(BytesIO(resp.content))

        # Reject tiny images that passed the HTML attribute check
        if img.width < _MIN_DIMENSION and img.height < _MIN_DIMENSION:
            return False

        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        # Consistent with archive pipeline max dimension
        img.thumbnail((1536, 1536), PILImage.Resampling.LANCZOS)

        save_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(save_path, "WEBP", quality=80)
        return True
    except Exception as exc:
        _logger.debug(f"Image download/compress skipped {Path(url).name}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_article_images(
    html: str,
    base_url: str,
) -> list[dict[str, str]]:
    """Extract, filter, download, and compress article images.

    The function parses HTML to find ``<img>`` tags within the article content
    area, applies Smart Filter heuristics to exclude noise images, downloads
    candidates concurrently, compresses them to WebP, and saves to
    ``04 - Permanent/sources/assets/<domain>/``.

    Args:
        html: Raw HTML string of the article page.
        base_url: Article URL for resolving relative ``src`` attributes.

    Returns:
        List of dicts with keys ``filename``, ``alt``, ``original_url``.
        Empty list if extraction is skipped or fails.
    """
    if BeautifulSoup is None or _requests is None or PILImage is None:
        _logger.warning("Missing dependencies (bs4/requests/Pillow) for image extraction")
        return []

    soup = BeautifulSoup(html, "html.parser")

    # Locate the main content area using common selectors
    content_area = (
        soup.find("article")
        or soup.find("div", class_=re.compile(
            r"entry-content|post-content|article-content|"
            r"post-body|blog-content|page-content",
        ))
        or soup.find("div", id=re.compile(r"content|post|article|entry"))
        or soup.body
        or soup
    )

    img_tags = content_area.find_all("img") if content_area else []
    custom_images = _extract_custom_theme_images(html)
    
    total_found = len(img_tags) + len(custom_images)

    if total_found < _MIN_IMAGES_THRESHOLD:
        _logger.info(
            f"Article has only {total_found} image(s) — below threshold "
            f"({_MIN_IMAGES_THRESHOLD}), skipping extraction",
        )
        return []

    # Domain slug for filename prefix & subfolder
    parsed = urlparse(base_url)
    domain_raw = (parsed.hostname or "unknown").replace("www.", "")
    domain_slug = re.sub(r"[^a-z0-9]", "_", domain_raw.split(".")[0].lower())

    assets_dir = cfg.sources_dir / "assets" / domain_slug

    # Collect candidate images -------------------------------------------------
    candidates: list[dict] = []
    seen_urls: set[str] = set()
    seen_filenames: set[str] = set()

    # 1. Process standard BeautifulSoup <img> tags
    for img in img_tags:
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue

        full_url = urljoin(base_url, src)

        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        if _is_noise_image(img, full_url):
            continue

        alt_text = (img.get("alt") or "").strip()
        filename = _make_image_filename(full_url, domain_slug, seen_filenames)

        candidates.append({
            "url": full_url,
            "alt": alt_text,
            "filename": filename,
            "save_path": assets_dir / filename,
        })

    # 2. Process custom React/Next.js ThemeImage elements (high-value diagrams)
    for cimg in custom_images:
        full_url = cimg["url"]
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Simple URL pattern noise check for safety
        if _NOISE_URL_PATTERNS.search(full_url):
            continue

        alt_text = cimg["alt"]
        filename = _make_image_filename(full_url, domain_slug, seen_filenames)

        candidates.append({
            "url": full_url,
            "alt": alt_text,
            "filename": filename,
            "save_path": assets_dir / filename,
        })

    if not candidates:
        _logger.info("No candidate images survived Smart Filter")
        return []

    # Cap at maximum
    candidates = candidates[:MAX_IMAGES_PER_ARTICLE]

    _logger.info(
        f"Extracting {len(candidates)} images from {domain_raw} "
        f"(filtered from {total_found} total images found)",
    )

    # Concurrent download & compress -------------------------------------------
    results: list[dict[str, str]] = []

    # Separate already-downloaded from new
    to_download = [c for c in candidates if not c["save_path"].exists()]
    already_cached = [c for c in candidates if c["save_path"].exists()]

    for c in already_cached:
        results.append({
            "filename": c["filename"],
            "alt": c["alt"],
            "original_url": c["url"],
        })

    if to_download:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=_MAX_DOWNLOAD_WORKERS,
        ) as executor:
            future_map = {
                executor.submit(_download_and_compress, c["url"], c["save_path"]): c
                for c in to_download
            }
            for future in concurrent.futures.as_completed(future_map):
                cand = future_map[future]
                try:
                    if future.result():
                        results.append({
                            "filename": cand["filename"],
                            "alt": cand["alt"],
                            "original_url": cand["url"],
                        })
                except Exception as exc:
                    _logger.debug(f"Image worker error: {exc}")

    _logger.info(f"Saved {len(results)}/{len(candidates)} images to {assets_dir}")
    return results


def format_image_metadata(images: list[dict[str, str]]) -> str:
    """Format image metadata as structured text for LLM consumption.

    The LLM is instructed (via ``_REDUCE_PROMPT``) to embed relevant images
    using Obsidian ``![[filename]]`` syntax inside ``## Core Idea``.

    Args:
        images: Output of :func:`extract_article_images`.

    Returns:
        Formatted metadata block, or empty string if no images.
    """
    if not images:
        return ""

    lines = [
        "\n\n## 🖼️ Hình ảnh bài viết (Đã tải cục bộ)",
        "> [!info]- 🖼️ Danh mục hình ảnh bài viết (Metadata bối cảnh cho AI & RAG)",
    ]
    for img in images:
        alt = img.get("alt") or "No description"
        lines.append(f"> - [IMG:{img['filename']}|alt={alt}]")

    return "\n".join(lines)
