"""VvC Second Brain — Article Image Extractor (v8.9.7).

Downloads, filters, and compresses article images locally for Obsidian embedding.
Smart Filter heuristics exclude noise (logos, icons, trackers, navigation).
Saves to ``04 - Permanent/sources/assets/<domain>/`` as WebP.

HTML parsing & noise detection extracted to services/article_image_parser.py.
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
from services.article_image_parser import (
    _NOISE_URL_PATTERNS,
    _MIN_DIMENSION,
    _is_noise_image,
    _extract_custom_theme_images,
)

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment,misc]

try:
    import requests as _requests
except ImportError:
    _requests = None  # type: ignore[assignment]

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None  # type: ignore[assignment]

_logger = logging.getLogger("vvc.article_images")

MAX_IMAGES_PER_ARTICLE: int = 20
_MIN_IMAGE_SIZE_BYTES: int = 5_000       # 5 KB minimum download size
_MAX_ASPECT_RATIO: float = 4.5           # skip extreme aspect ratios (thin banners/dividers)
_DOWNLOAD_TIMEOUT: int = 10             # seconds per image request
_MAX_DOWNLOAD_WORKERS: int = 5
_MIN_IMAGES_THRESHOLD: int = 1           # allow single high-value diagrams


def _make_image_filename(url: str, domain_slug: str, seen: set[str]) -> str:
    """Generate a unique, normalised filename (WebP, or SVG if original was SVG)."""
    parsed = urlparse(url)
    is_svg = parsed.path.lower().endswith(".svg")
    ext = ".svg" if is_svg else ".webp"

    basename = Path(parsed.path).stem
    normalised = normalize_stem(basename)
    if len(normalised) > 40:
        normalised = normalised[:40].rsplit("_", 1)[0]

    candidate = f"{domain_slug}_{normalised}{ext}"
    if candidate in seen:
        suffix = 2
        while f"{domain_slug}_{normalised}_{suffix}{ext}" in seen:
            suffix += 1
        candidate = f"{domain_slug}_{normalised}_{suffix}{ext}"

    seen.add(candidate)
    return candidate


def _validate_and_compress_image(content: bytes, save_path: Path) -> bool:
    """Validate image dimensions and aspect ratio, then compress to WebP."""
    if len(content) < _MIN_IMAGE_SIZE_BYTES or PILImage is None:
        return False

    try:
        img = PILImage.open(BytesIO(content))
        if img.width < _MIN_DIMENSION and img.height < _MIN_DIMENSION:
            return False

        min_dim = min(img.width, img.height)
        if min_dim <= 0 or (max(img.width, img.height) / min_dim) > _MAX_ASPECT_RATIO:
            return False

        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        img.thumbnail((1536, 1536), PILImage.Resampling.LANCZOS)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(save_path, "WEBP", quality=80)
        return True
    except Exception:
        return False


def _download_and_compress(url: str, save_path: Path) -> bool:
    """Download a single image, saving SVGs directly and compressing others to WebP."""
    if _requests is None:
        return False
    try:
        resp = _requests.get(
            url, timeout=_DOWNLOAD_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()

        if save_path.suffix.lower() == ".svg":
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(resp.content)
            return True

        return _validate_and_compress_image(resp.content, save_path)
    except Exception as exc:
        _logger.debug(f"Image download/compress skipped {Path(url).name}: {exc}")
        return False


def _generate_vision_caption(save_path: Path) -> str:
    """Generate a short Vietnamese description for a raster image if alt is missing."""
    if save_path.suffix.lower() == ".svg" or not save_path.exists():
        return ""
    try:
        from core.llm.vision_client import call_vision
        prompt = (
            "Mô tả ngắn gọn (1-2 câu tiếng Việt) nội dung hình ảnh này: "
            "đây là loại sơ đồ/biểu đồ/hình minh hoạ/ảnh chụp màn hình gì, "
            "thể hiện khái niệm hoặc thông tin gì? "
            "Chỉ mô tả nội dung chính, không bình luận thêm, không bắt đầu bằng 'Hình ảnh này'."
        )
        caption = call_vision(save_path, prompt, max_pixels=768) or ""
        if len(caption) > 200:
            caption = caption[:197].rsplit(" ", 1)[0] + "..."
        return caption
    except Exception as exc:
        _logger.debug(f"[JIT caption] Skipped {save_path.name}: {exc}")
        return ""


def _find_content_area(soup: BeautifulSoup) -> BeautifulSoup:
    """Locate the main article content container using common selectors."""
    return (
        soup.find("article")
        or soup.find("div", class_=re.compile(
            r"entry-content|post-content|article-content|"
            r"post-body|blog-content|page-content",
        ))
        or soup.find("div", id=re.compile(r"content|post|article|entry"))
        or soup.body
        or soup
    )


def _collect_image_candidates(
    img_tags: list,
    custom_images: list[dict[str, str]],
    base_url: str,
    domain_slug: str,
    assets_dir: Path,
) -> list[dict]:
    """Collect candidate images surviving Smart Filter from HTML tags and custom elements."""
    candidates: list[dict] = []
    seen_urls: set[str] = set()
    seen_filenames: set[str] = set()

    for img in img_tags:
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue
        full_url = urljoin(base_url, src)
        if full_url in seen_urls or _is_noise_image(img, full_url):
            continue
        seen_urls.add(full_url)

        fn = _make_image_filename(full_url, domain_slug, seen_filenames)
        candidates.append({
            "url": full_url, "alt": (img.get("alt") or "").strip(),
            "filename": fn, "save_path": assets_dir / fn,
        })

    for cimg in custom_images:
        full_url = cimg["url"]
        if full_url in seen_urls or _NOISE_URL_PATTERNS.search(full_url):
            continue
        seen_urls.add(full_url)

        fn = _make_image_filename(full_url, domain_slug, seen_filenames)
        candidates.append({
            "url": full_url, "alt": cimg["alt"],
            "filename": fn, "save_path": assets_dir / fn,
        })

    return candidates[:MAX_IMAGES_PER_ARTICLE]


def _process_image_downloads(candidates: list[dict], assets_dir: Path) -> list[dict[str, str]]:
    """Perform concurrent downloads and generate JIT captions for candidates."""
    results: list[dict[str, str]] = []
    to_download = [c for c in candidates if not c["save_path"].exists()]
    already_cached = [c for c in candidates if c["save_path"].exists()]

    for c in already_cached:
        alt = c["alt"] or _generate_vision_caption(c["save_path"])
        results.append({"filename": c["filename"], "alt": alt, "original_url": c["url"]})

    if to_download:
        with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_DOWNLOAD_WORKERS) as executor:
            future_map = {
                executor.submit(_download_and_compress, c["url"], c["save_path"]): c
                for c in to_download
            }
            for future in concurrent.futures.as_completed(future_map):
                cand = future_map[future]
                try:
                    if future.result():
                        alt = cand["alt"] or _generate_vision_caption(cand["save_path"])
                        results.append({"filename": cand["filename"], "alt": alt, "original_url": cand["url"]})
                except Exception as exc:
                    _logger.debug(f"Image worker error: {exc}")

    _logger.info(f"Saved {len(results)}/{len(candidates)} images to {assets_dir}")
    return results


def extract_article_images(html: str, base_url: str) -> list[dict[str, str]]:
    """Extract, filter, download, and compress article images."""
    if BeautifulSoup is None or _requests is None or PILImage is None:
        _logger.warning("Missing dependencies (bs4/requests/Pillow) for image extraction")
        return []

    soup = BeautifulSoup(html, "html.parser")
    content_area = _find_content_area(soup)
    img_tags = content_area.find_all("img") if content_area else []
    custom_images = _extract_custom_theme_images(html)

    total_found = len(img_tags) + len(custom_images)
    if total_found < _MIN_IMAGES_THRESHOLD:
        _logger.info(f"Article has {total_found} image(s) — below threshold ({_MIN_IMAGES_THRESHOLD})")
        return []

    parsed = urlparse(base_url)
    domain_raw = (parsed.hostname or "unknown").replace("www.", "")
    domain_slug = re.sub(r"[^a-z0-9]", "_", domain_raw.split(".")[0].lower())
    assets_dir = cfg.assets_dir / domain_slug

    candidates = _collect_image_candidates(img_tags, custom_images, base_url, domain_slug, assets_dir)
    if not candidates:
        _logger.info("No candidate images survived Smart Filter")
        return []

    _logger.info(f"Extracting {len(candidates)} images from {domain_raw} (filtered from {total_found})")
    return _process_image_downloads(candidates, assets_dir)


def format_image_metadata(images: list[dict[str, str]]) -> str:
    """Format image metadata as structured text for LLM consumption."""
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
