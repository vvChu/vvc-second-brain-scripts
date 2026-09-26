"""VvC Second Brain — EPUB → Clean Markdown Converter (v7.0).

Converts EPUB books to chunked markdown files for BM25 corpus.
Based on v3.4 spec: dedup images, wiki-links, page markers, dedup H1.

Usage:
    python epub_convert.py <epub_path> [output_dir]
    from epub_convert import convert_epub
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any

_logger = logging.getLogger("vvc.epub")


def _is_vietnamese(text: str) -> bool:
    """Check if the text contains Vietnamese accented characters."""
    if not text:
        return False
    return bool(re.search(r"[àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệđìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ]", text.lower()))


def _prepare_output_dir(epub_path: Path, output_dir: Path | None) -> Path:
    """Resolve and prepare output directory with backup if exists."""
    if output_dir is None:
        stem = re.sub(r"[^a-zA-Z0-9À-ỹ]+", "_", epub_path.stem).strip("_")
        output_dir = epub_path.parent / f"{stem}_MD"
    if output_dir.exists():
        backup = output_dir.parent / f"{output_dir.name}_backup"
        if not backup.exists():
            import shutil
            shutil.copytree(str(output_dir), str(backup))
            _logger.info(f"Backed up existing MD to: {backup.name}")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _extract_images(book, output_dir: Path) -> int:
    """Extract all images from EPUB to output directory."""
    import ebooklib

    count = 0
    for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
        img_path = output_dir / Path(item.get_name()).name
        if not img_path.exists():
            try:
                img_path.write_bytes(item.get_content())
                count += 1
            except OSError:
                pass
    return count


def _get_toc_mapping(book) -> dict[str, str]:
    """Extract TOC href stem to title mapping."""
    from ebooklib import epub

    mapping: dict[str, str] = {}

    def _parse_toc(toc_list: list[Any]) -> None:
        for item in toc_list:
            if isinstance(item, epub.Link):
                stem = re.sub(r'_split_\d+$', '', Path(item.href.split('#')[0]).stem)
                mapping.setdefault(stem, item.title)
            elif isinstance(item, tuple) and len(item) == 2:
                header, children = item
                if hasattr(header, 'href') and header.href:
                    stem = re.sub(r'_split_\d+$', '', Path(header.href.split('#')[0]).stem)
                    mapping.setdefault(stem, getattr(header, 'title', ''))
                _parse_toc(children)

    _parse_toc(book.toc)
    return mapping


def _group_logical_chapters(book, toc_mapping: dict[str, str]) -> list[dict[str, Any]]:
    """Group EPUB document items by logical chapter (base stem + toc inheritance)."""
    import ebooklib

    chapters: list[dict[str, Any]] = []
    last_base = None
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        name = item.get_name()
        base = re.sub(r'_split_\d+$', '', Path(name).stem)
        if base in toc_mapping:
            last_base = base
        eff_base = last_base or base
        if not chapters or chapters[-1]["base"] != eff_base:
            chapters.append({"base": eff_base, "name": name, "names": [name], "chunks": [item.get_content()]})
        else:
            chapters[-1]["names"].append(name)
            chapters[-1]["chunks"].append(item.get_content())
    return chapters


def _item_to_filename(item_name: str, index: int, toc_title: str = "") -> str:
    """Convert EPUB item name to a clean filename."""
    import unicodedata

    stem = toc_title if toc_title else Path(item_name).stem.replace("Text_", "").replace("OEBPS_", "")
    stem = re.sub(r'_split_\d+$', '', stem).replace('đ', 'd').replace('Đ', 'D')
    stem = unicodedata.normalize('NFKD', stem).encode('ASCII', 'ignore').decode('utf-8')
    clean = re.sub(r"\s+", "_", re.sub(r"[^a-zA-Z0-9_\-\s]", "", stem).strip())
    if not clean or clean.isdigit():
        clean = f"chapter_{index:02d}"
    return f"{index:02d}_{clean}"


def _get_spine_items(logical_chapters: list[dict[str, Any]], toc_mapping: dict[str, str]) -> dict[str, str]:
    """Build mapping from EPUB internal paths to clean filenames."""
    mapping: dict[str, str] = {}
    for idx, chap in enumerate(logical_chapters):
        clean = _item_to_filename(chap["name"], idx, toc_mapping.get(chap["base"], ""))
        for name in chap["names"]:
            mapping[name] = clean
            mapping[Path(name).name] = clean
            mapping[Path(name).stem] = clean
    return mapping


def _render_chapter_markdown(chunks: list[bytes], md_converter: Any) -> str:
    """Parse HTML chunks and convert to single markdown string."""
    from bs4 import BeautifulSoup

    parts: list[str] = []
    for content in chunks:
        try:
            soup = BeautifulSoup(content, "html.parser")
        except Exception:
            continue
        for decl in soup.find_all(string=re.compile(r"xml version=")):
            decl.extract()
        for header in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            spans = header.find_all("span")
            for i in range(len(spans) - 1):
                spans[i].append(" ")
        part_md = (
            md_converter(str(soup), heading_style="ATX", bullets="-", strip=["script", "style"])
            if md_converter
            else soup.get_text(separator="\n", strip=True)
        )
        if part_md and len(part_md.strip()) > 10:
            parts.append(part_md)
    return "\n\n".join(parts)


def _dedup_h1(text: str, seen: set[str]) -> str:
    """Remove duplicate H1 headings (from <title> + <h1> both rendering)."""
    lines, result, prev_h1 = text.split("\n"), [], ""
    for line in lines:
        if line.startswith("# ") and not line.startswith("## "):
            h1_text = line[2:].strip()
            if h1_text == prev_h1 or h1_text in seen:
                continue
            prev_h1 = h1_text
            seen.add(h1_text)
        result.append(line)
    return "\n".join(result)


def _dedup_images(text: str, seen: set[str]) -> str:
    """Remove duplicate image embeds."""
    result = []
    for line in text.split("\n"):
        img_match = re.search(r"!\[.*?\]\((.*?)\)", line)
        if img_match:
            src = img_match.group(1)
            if src in seen:
                continue
            seen.add(src)
        result.append(line)
    return "\n".join(result)


def _convert_links(text: str, spine: dict[str, str]) -> str:
    """Convert internal EPUB links to Obsidian wiki-links."""
    def _replace_link(match: re.Match) -> str:
        display, href = match.group(1), match.group(2)
        parts = href.split("#")
        file_ref = parts[0].split("/")[-1]
        anchor = parts[1] if len(parts) > 1 else ""
        clean = spine.get(file_ref, spine.get(Path(file_ref).stem, Path(file_ref).stem))
        return f"[[{clean}#{anchor}|{display}]]" if anchor else f"[[{clean}|{display}]]"

    return re.sub(r"\[([^\]]+)\]\(([^)]*?\.x?html[^)]*)\)", _replace_link, text)


def _extract_page_markers(text: str) -> str:
    """Convert doc-pagebreak spans to HTML comments."""
    text = re.sub(
        r'<span[^>]*epub:type="pagebreak"[^>]*(?:title|id)="(?:page)?(\d+)"[^>]*/?>(?:</span>)?',
        r"<!-- page \1 -->", text, flags=re.IGNORECASE,
    )
    return re.sub(r'<[^>]*data-page-?(?:number)?="(\d+)"[^>]*/?>', r"<!-- page \1 -->", text, flags=re.IGNORECASE)


def _convert_image_refs(text: str, book_prefix: str, chap_idx: int, mapping: dict[str, str], output_dir: Path) -> str:
    """Convert markdown image refs to Obsidian wiki-link embeds with dynamic renaming."""
    def _to_embed(match: re.Match) -> str:
        filename = Path(match.group(2)).name
        if filename not in mapping:
            new_name = f"{book_prefix}_Ch{chap_idx:02d}_{filename}"
            mapping[filename] = new_name
            old_file, new_file = output_dir / filename, output_dir / new_name
            if old_file.exists():
                try: old_file.rename(new_file)
                except OSError: pass
        return f"![[{mapping.get(filename, filename)}]]"

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _to_embed, text)


def _post_process_markdown(
    text: str, seen_h1: set[str], seen_images: set[str],
    spine_items: dict[str, str], book_prefix: str, idx: int,
    global_img_mapping: dict[str, str], output_dir: Path,
) -> str:
    """Clean up and convert links/images/headers for a markdown chapter."""
    text = _dedup_h1(text, seen_h1)
    text = _dedup_images(text, seen_images)
    text = _convert_links(text, spine_items)
    text = _extract_page_markers(text)
    text = _convert_image_refs(text, book_prefix, idx, global_img_mapping, output_dir)
    text = re.sub(r'^(#{1,6}\s+)\[\[[^|\]]+\|([^\]]+)\]\]', r'\1\2', text, flags=re.MULTILINE)
    text = re.sub(r'^(#{1,6}\s+)\[\[([^|\]]+)\]\]', r'\1\2', text, flags=re.MULTILINE)
    text = re.sub(r'^(#{1,6}\s+)\d+$', '', text, flags=re.MULTILINE)
    lines = [line.rstrip() for line in re.sub(r"\n{3,}", "\n\n", text).split("\n")]
    return "\n".join(lines).strip() + "\n"


def _write_toc_original(output_dir: Path, book_title: str, toc_chapters: list[dict], text_samples: list[str]) -> None:
    """Write _toc_original.json with auto-detected language."""
    import json

    lang = "vi" if _is_vietnamese("\n".join(text_samples)) else "en"
    _logger.info(f"Auto-detected language for EPUB: {lang}")
    data = {
        "book_title_vi": book_title,
        "book_title_original": book_title,
        "language": lang,
        "chapters": toc_chapters,
    }
    try:
        path = output_dir / "_toc_original.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _logger.info(f"Original TOC template saved: {path.name}")
    except OSError as e:
        _logger.warning(f"Failed to write _toc_original.json: {e}")


def _process_chapter(
    chap: dict[str, Any], idx: int, md_converter: Any,
    seen_h1: set[str], seen_images: set[str], spine_items: dict[str, str],
    book_prefix: str, global_img_mapping: dict[str, str], out_dir: Path,
    toc_mapping: dict[str, str],
) -> tuple[str, str, str] | None:
    """Render, post-process, and save a single logical chapter."""
    raw_md = _render_chapter_markdown(chap["chunks"], md_converter)
    if not raw_md or len(raw_md.strip()) < 50:
        return None

    clean_md = _post_process_markdown(
        raw_md, seen_h1, seen_images, spine_items,
        book_prefix, idx, global_img_mapping, out_dir,
    )
    clean_name = _item_to_filename(chap["name"], idx, toc_mapping.get(chap["base"], ""))
    out_path = out_dir / f"{clean_name}.md"
    try:
        out_path.write_text(clean_md, encoding="utf-8")
        title = toc_mapping.get(chap["base"]) or clean_name.replace(f"{idx:02d}_", "").replace("_", " ")
        return clean_md, clean_name, title
    except OSError as e:
        _logger.warning(f"Failed to write {out_path.name}: {e}")
        return None


def convert_epub(epub_path: Path, output_dir: Path | None = None) -> bool:
    """Convert EPUB to chunked markdown files."""
    try: from ebooklib import epub
    except ImportError:
        _logger.error("ebooklib not installed: pip install ebooklib")
        return False
    try: from markdownify import markdownify as md
    except ImportError: md = None

    if not epub_path.exists():
        _logger.error(f"EPUB not found: {epub_path}")
        return False

    out_dir = _prepare_output_dir(epub_path, output_dir)
    _logger.info(f"Converting: {epub_path.name}")
    book = epub.read_epub(str(epub_path))
    image_count = _extract_images(book, out_dir)
    toc_mapping = _get_toc_mapping(book)
    logical_chapters = _group_logical_chapters(book, toc_mapping)
    spine_items = _get_spine_items(logical_chapters, toc_mapping)

    seen_h1, seen_images = set(), set()
    global_img_mapping: dict[str, str] = {}
    book_prefix = out_dir.name.replace("_MD", "")[:30].rstrip("_")
    toc_chapters, text_samples = [], []
    file_count = 0

    for idx, chap in enumerate(logical_chapters):
        res = _process_chapter(
            chap, idx, md, seen_h1, seen_images, spine_items,
            book_prefix, global_img_mapping, out_dir, toc_mapping,
        )
        if res:
            clean_md, clean_name, title = res
            file_count += 1
            if len(text_samples) < 5:
                text_samples.append(clean_md[:2000])
            toc_chapters.append({
                "chapter_num": idx + 1, "title_vi": title, "title_original": title,
                "description_vi": None, "epub_file": f"{clean_name}.md",
            })

    if file_count > 0:
        _write_toc_original(out_dir, epub_path.stem.replace("_", " "), toc_chapters, text_samples)

    _logger.info(f"Conversion complete: {file_count} chapters, {image_count} images → {out_dir.name}")
    return file_count > 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) < 2:
        print("Usage: python epub_convert.py <epub_path> [output_dir]")
        sys.exit(1)

    target_epub = Path(sys.argv[1])
    target_out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    sys.exit(0 if convert_epub(target_epub, target_out) else 1)
