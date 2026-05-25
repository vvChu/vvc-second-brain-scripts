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

_logger = logging.getLogger("vvc.epub")


def _is_vietnamese(text: str) -> bool:
    """Check if the text contains Vietnamese accented characters."""
    if not text:
        return False
    return bool(re.search(r"[àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệđìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ]", text.lower()))



def convert_epub(epub_path: Path, output_dir: Path | None = None) -> bool:
    """Convert EPUB to chunked markdown files.

    Args:
        epub_path: Path to the EPUB file.
        output_dir: Output directory. Defaults to {epub_stem}_MD in same folder.

    Returns:
        True if conversion succeeded.
    """
    try:
        import ebooklib
        from ebooklib import epub
    except ImportError:
        _logger.error("ebooklib not installed: pip install ebooklib")
        return False

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        _logger.error("beautifulsoup4 not installed")
        return False

    try:
        from markdownify import markdownify as md
    except ImportError:
        md = None
        _logger.warning("markdownify not installed, using basic conversion")

    if not epub_path.exists():
        _logger.error(f"EPUB not found: {epub_path}")
        return False

    # Setup output directory
    if output_dir is None:
        stem = re.sub(r"[^a-zA-Z0-9À-ỹ]+", "_", epub_path.stem).strip("_")
        output_dir = epub_path.parent / f"{stem}_MD"

    # Backup existing output
    if output_dir.exists():
        backup = output_dir.parent / f"{output_dir.name}_backup"
        if not backup.exists():
            import shutil
            shutil.copytree(str(output_dir), str(backup))
            _logger.info(f"Backed up existing MD to: {backup.name}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # Read EPUB
    _logger.info(f"Converting: {epub_path.name}")
    book = epub.read_epub(str(epub_path))

    # Extract images
    image_count = _extract_images(book, output_dir)
    
    toc_mapping = _get_toc_mapping(book)

    # Build chapter-to-filename mapping for wiki-links
    spine_items = _get_spine_items(book, toc_mapping)

    # Convert each document item
    seen_h1: set[str] = set()
    seen_images: set[str] = set()
    global_img_mapping: dict[str, str] = {}
    file_count = 0

    book_prefix = output_dir.name.replace("_MD", "")[:30]
    if book_prefix.endswith("_"):
        book_prefix = book_prefix[:-1]

    # Pre-process: Group items by logical chapter (base stem + toc inheritance)
    logical_chapters = []
    last_toc_base = None
    
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        name = item.get_name()
        stem = Path(name).stem
        base_name = re.sub(r'_split_\d+$', '', stem)
        
        if base_name in toc_mapping:
            last_toc_base = base_name
        effective_base = last_toc_base if last_toc_base else base_name
        
        if not logical_chapters or logical_chapters[-1]["base"] != effective_base:
            logical_chapters.append({
                "base": effective_base,
                "name": name,
                "chunks": [item.get_content()]
            })
        else:
            logical_chapters[-1]["chunks"].append(item.get_content())

    toc_chapters = []
    text_samples = []

    for idx, chap in enumerate(logical_chapters):
        item_name = chap["name"]
        toc_title = toc_mapping.get(chap["base"], "")
        
        markdown_parts = []
        for content in chap["chunks"]:
            try:
                soup = BeautifulSoup(content, "html.parser")
            except Exception:
                continue

            # Remove XML declaration artifacts
            for decl in soup.find_all(string=re.compile(r"xml version=")):
                decl.extract()

            # Fix adjacent span tags in headers sticking together
            for header in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
                spans = header.find_all("span")
                for i in range(len(spans) - 1):
                    spans[i].append(" ")

            # Convert to markdown
            if md:
                part_md = md(
                    str(soup),
                    heading_style="ATX",
                    bullets="-",
                    strip=["script", "style"],
                )
            else:
                part_md = _basic_html_to_md(soup)
                
            if part_md and len(part_md.strip()) > 10:
                markdown_parts.append(part_md)

        if not markdown_parts:
            continue
            
        markdown_text = "\n\n".join(markdown_parts)
        if not markdown_text or len(markdown_text.strip()) < 50:
            continue

        # Post-process
        markdown_text = _dedup_h1(markdown_text, seen_h1)
        markdown_text = _dedup_images(markdown_text, seen_images)
        markdown_text = _convert_links(markdown_text, spine_items)
        markdown_text = _extract_page_markers(markdown_text)
        markdown_text = _convert_image_refs(
            markdown_text, book_prefix, idx, global_img_mapping, output_dir
        )
        
        # Strip wikilinks from headers: '# [[url|Title]]' -> '# Title'
        markdown_text = re.sub(r'^(#{1,6}\s+)\[\[[^|\]]+\|([^\]]+)\]\]', r'\1\2', markdown_text, flags=re.MULTILINE)
        # Also strip if it's a direct link without |text: '# [[url]]' -> '# url'
        markdown_text = re.sub(r'^(#{1,6}\s+)\[\[([^|\]]+)\]\]', r'\1\2', markdown_text, flags=re.MULTILINE)
        # Strip purely numeric header links like '# 1'
        markdown_text = re.sub(r'^(#{1,6}\s+)\d+$', '', markdown_text, flags=re.MULTILINE)
        
        markdown_text = _clean_whitespace(markdown_text)

        # Generate output filename
        # Try to extract a meaningful name from the EPUB item
        clean_name = _item_to_filename(item_name, idx, toc_mapping.get(chap["base"], ""))
        out_path = output_dir / f"{clean_name}.md"

        try:
            out_path.write_text(markdown_text, encoding="utf-8")
            file_count += 1
            if len(text_samples) < 5:
                text_samples.append(markdown_text[:2000])
            
            # Store chapter in original TOC (canonical schema v8.0)
            epub_file = f"{clean_name}.md"
            ch_title = toc_title if toc_title else clean_name.replace(f"{idx:02d}_", "").replace("_", " ")
            toc_chapters.append({
                "chapter_num": idx + 1,
                "title_vi": ch_title,
                "title_original": ch_title,
                "description_vi": None,
                "epub_file": epub_file
            })
        except OSError as e:
            _logger.warning(f"Failed to write {out_path.name}: {e}")

    # Write _toc_original.json (canonical schema v8.0)
    if file_count > 0:
        import json
        clean_title = epub_path.stem.replace("_", " ")
        sample_text = "\n".join(text_samples)
        lang = "vi" if _is_vietnamese(sample_text) else "en"
        _logger.info(f"Auto-detected language for EPUB: {lang}")
        original_toc_data = {
            "book_title_vi": clean_title,
            "book_title_original": clean_title,
            "language": lang,
            "chapters": toc_chapters
        }
        try:
            toc_original_path = output_dir / "_toc_original.json"
            with open(toc_original_path, "w", encoding="utf-8") as f:
                json.dump(original_toc_data, f, ensure_ascii=False, indent=2)
            _logger.info(f"Original TOC template saved: {toc_original_path.name}")
        except OSError as e:
            _logger.warning(f"Failed to write _toc_original.json: {e}")

    _logger.info(
        f"Conversion complete: {file_count} chapters, "
        f"{image_count} images → {output_dir.name}"
    )
    return file_count > 0


# --- Image Extraction ---

def _extract_images(book, output_dir: Path) -> int:
    """Extract all images from EPUB to output directory."""
    import ebooklib

    count = 0
    for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
        img_name = Path(item.get_name()).name
        img_path = output_dir / img_name

        if not img_path.exists():
            try:
                img_path.write_bytes(item.get_content())
                count += 1
            except OSError:
                pass

    return count


# --- Spine / Link Mapping ---

def _get_toc_mapping(book) -> dict[str, str]:
    import ebooklib
    from ebooklib import epub
    mapping = {}
    def _parse_toc(toc_list):
        for item in toc_list:
            if isinstance(item, epub.Link):
                href = item.href.split('#')[0]
                stem = __import__('re').sub(r'_split_\d+$', '', Path(href).stem)
                if stem not in mapping:
                    mapping[stem] = item.title
            elif isinstance(item, tuple):
                if isinstance(item[0], epub.Section) and hasattr(item[0], 'href') and item[0].href:
                    href = item[0].href.split('#')[0]
                    stem = __import__('re').sub(r'_split_\d+$', '', Path(href).stem)
                    if stem not in mapping:
                        mapping[stem] = item[0].title
                elif isinstance(item[0], epub.Link):
                    href = item[0].href.split('#')[0]
                    stem = __import__('re').sub(r'_split_\d+$', '', Path(href).stem)
                    if stem not in mapping:
                        mapping[stem] = item[0].title
                _parse_toc(item[1])
    _parse_toc(book.toc)
    return mapping

def _get_spine_items(book, toc_mapping: dict[str, str] = None) -> dict[str, str]:
    """Build mapping from EPUB internal paths to clean filenames."""
    if toc_mapping is None:
        toc_mapping = {}
    mapping: dict[str, str] = {}
    import ebooklib

    logical_chapters = []
    last_toc_base = None
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        name = item.get_name()
        stem = Path(name).stem
        base_name = re.sub(r'_split_\d+$', '', stem)
        
        if base_name in toc_mapping:
            last_toc_base = base_name
        effective_base = last_toc_base if last_toc_base else base_name

        if not logical_chapters or logical_chapters[-1]["base"] != effective_base:
            logical_chapters.append({"base": effective_base, "names": [name]})
        else:
            logical_chapters[-1]["names"].append(name)
            
    for idx, chap in enumerate(logical_chapters):
        toc_title = toc_mapping.get(chap["base"], "")
        clean = _item_to_filename(chap["names"][0], idx, toc_title)
        for name in chap["names"]:
            mapping[name] = clean
            mapping[Path(name).name] = clean
            stem = Path(name).stem
            mapping[stem] = clean

    return mapping


def _item_to_filename(item_name: str, index: int, toc_title: str = "") -> str:
    """Convert EPUB item name to a clean filename."""
    stem = Path(item_name).stem

    if toc_title:
        stem = toc_title
    else:
        # Remove common prefixes like "Text/", "OEBPS/"
        stem = stem.replace("Text_", "").replace("OEBPS_", "")
        
        # Remove split suffixes
        stem = re.sub(r'_split_\d+$', '', stem)

    # Strip accents for safe filesystem naming
    import unicodedata
    stem = stem.replace('đ', 'd').replace('Đ', 'D')
    stem = unicodedata.normalize('NFKD', stem).encode('ASCII', 'ignore').decode('utf-8')

    # Clean up non-alphanumeric characters, strip whitespace and convert to underscores
    clean = re.sub(r"[^a-zA-Z0-9_\-\s]", "", stem)
    clean = re.sub(r"\s+", "_", clean.strip())

    if not clean or clean.isdigit():
        clean = f"chapter_{index:02d}"

    return f"{index:02d}_{clean}"


# --- Post-Processing ---

def _dedup_h1(text: str, seen: set[str]) -> str:
    """Remove duplicate H1 headings (from <title> + <h1> both rendering)."""
    lines = text.split("\n")
    result = []
    prev_h1 = ""

    for line in lines:
        if line.startswith("# ") and not line.startswith("## "):
            h1_text = line[2:].strip()
            if h1_text == prev_h1 or h1_text in seen:
                continue  # Skip duplicate
            prev_h1 = h1_text
            seen.add(h1_text)
        result.append(line)

    return "\n".join(result)


def _dedup_images(text: str, seen: set[str]) -> str:
    """Remove duplicate image embeds."""
    lines = text.split("\n")
    result = []

    for line in lines:
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
        display = match.group(1)
        href = match.group(2)

        # Parse href: ../Text/chapter.xhtml#anchor
        parts = href.split("#")
        file_ref = parts[0].split("/")[-1]  # Get filename
        anchor = parts[1] if len(parts) > 1 else ""

        # Remove extension
        file_stem = Path(file_ref).stem

        # Look up in spine mapping
        clean = spine.get(file_ref, spine.get(file_stem, file_stem))

        if anchor:
            return f"[[{clean}#{anchor}|{display}]]"
        return f"[[{clean}|{display}]]"

    # Match markdown links: [text](path)
    return re.sub(r"\[([^\]]+)\]\(([^)]*?\.x?html[^)]*)\)", _replace_link, text)


def _extract_page_markers(text: str) -> str:
    """Convert doc-pagebreak spans to HTML comments."""
    # Match epub:type="pagebreak" patterns
    text = re.sub(
        r'<span[^>]*epub:type="pagebreak"[^>]*(?:title|id)="(?:page)?(\d+)"[^>]*/?>(?:</span>)?',
        r"<!-- page \1 -->",
        text,
        flags=re.IGNORECASE,
    )
    # Also handle data-page attributes
    text = re.sub(
        r'<[^>]*data-page-?(?:number)?="(\d+)"[^>]*/?>',
        r"<!-- page \1 -->",
        text,
        flags=re.IGNORECASE,
    )
    return text


def _convert_image_refs(text: str, book_prefix: str, chap_idx: int, mapping: dict[str, str], output_dir: Path) -> str:
    """Convert markdown image refs to Obsidian wiki-link embeds with dynamic renaming."""
    def _to_embed(match: re.Match) -> str:
        alt = match.group(1)
        src = match.group(2)
        filename = Path(src).name
        
        if filename not in mapping:
            new_name = f"{book_prefix}_Ch{chap_idx:02d}_{filename}"
            mapping[filename] = new_name
            
            old_file = output_dir / filename
            new_file = output_dir / new_name
            if old_file.exists():
                try:
                    old_file.rename(new_file)
                except OSError:
                    pass
                    
        final_name = mapping.get(filename, filename)
        return f"![[{final_name}]]"

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _to_embed, text)


def _clean_whitespace(text: str) -> str:
    """Clean excessive whitespace while preserving structure."""
    # Collapse 3+ blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Remove trailing whitespace
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip() + "\n"


def _basic_html_to_md(soup) -> str:
    """Basic HTML to markdown fallback (no markdownify)."""
    text = soup.get_text(separator="\n", strip=True)
    return text


# --- CLI ---

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if len(sys.argv) < 2:
        print("Usage: python epub_convert.py <epub_path> [output_dir]")
        sys.exit(1)

    epub_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    success = convert_epub(epub_path, output_dir)
    sys.exit(0 if success else 1)
