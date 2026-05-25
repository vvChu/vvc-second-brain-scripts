"""VvC Second Brain — PDF → Clean Markdown Converter (v7.0).

Converts PDF books to chunked markdown files for BM25 corpus using pymupdf4llm.
Supports custom _toc.json, embedded TOC, or smart chunking fallback.
Includes automatic image resizing/compression.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from PIL import Image

_logger = logging.getLogger("vvc.pdf_convert")


def _is_vietnamese(text: str) -> bool:
    """Check if the text contains Vietnamese accented characters."""
    if not text:
        return False
    return bool(re.search(r"[àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệđìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ]", text.lower()))


def _optimize_images(output_dir: Path, max_size: int = 1024, quality: int = 85) -> None:
    """Resize and compress images to save space."""
    for img_path in output_dir.glob("*.*"):
        if img_path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue
            
        try:
            with Image.open(img_path) as img:
                # Calculate new size while preserving aspect ratio
                if img.width > max_size or img.height > max_size:
                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                
                # If PNG, try to convert to RGB to save as JPG if it doesn't have transparency
                # But to be safe and avoid black backgrounds, we'll just save as optimized PNG
                # or optimized JPG.
                if img.format == "PNG" and img.mode in ("RGBA", "LA", "P"):
                    img.save(img_path, optimize=True)
                else:
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    img.save(img_path, format="JPEG", optimize=True, quality=quality)
                    
            _logger.debug(f"Optimized image: {img_path.name}")
        except Exception as e:
            _logger.warning(f"Failed to optimize {img_path.name}: {e}")

def _load_custom_toc(toc_path: Path) -> list[dict] | None:
    """Load and parse _toc.json if it exists."""
    if not toc_path.exists():
        return None
    try:
        with open(toc_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("chapters")
    except Exception as e:
        _logger.warning(f"Failed to parse _toc.json: {e}")
        return None

def _get_embedded_toc(pdf_path: Path) -> list[dict] | None:
    """Extract embedded TOC using PyMuPDF."""
    import fitz
    try:
        doc = fitz.open(str(pdf_path))
        toc = doc.get_toc()
        if not toc:
            return None
            
        chapters = []
        for i, item in enumerate(toc):
            level, title, page_start = item
            if level > 2: # Only take top-level chapters (H1/H2)
                continue
                
            page_end = toc[i+1][2] - 1 if i + 1 < len(toc) else doc.page_count
            chapters.append({
                "chapter_num": len(chapters) + 1,
                "title_vi": title,
                "page_start": page_start,
                "page_end": page_end
            })
        return chapters if chapters else None
    except Exception as e:
        _logger.warning(f"Failed to extract embedded TOC: {e}")
        return None

def _smart_chunking(pages_text: list[str], target_size: int = 15) -> list[dict]:
    """Group pages into chunks, trying to break at H1 or H2 boundaries."""
    chapters = []
    total_pages = len(pages_text)
    
    start_idx = 0
    while start_idx < total_pages:
        end_idx = min(start_idx + target_size, total_pages)
        
        # If we are not at the very end, try to find a clean break in a window [-3, +3]
        if end_idx < total_pages:
            best_break = end_idx
            # Look at pages around the target end index
            search_start = max(start_idx + 1, end_idx - 3)
            search_end = min(total_pages, end_idx + 3)
            
            for i in range(search_start, search_end):
                text = pages_text[i].strip()
                # If page starts with H1 or H2, it's a great break point
                if re.match(r"^#{1,2}\s+", text):
                    best_break = i
                    break
            
            end_idx = best_break
            
        chapters.append({
            "chapter_num": len(chapters) + 1,
            "title_vi": f"Pages {start_idx + 1} - {end_idx}",
            "page_start": start_idx + 1,
            "page_end": end_idx
        })
        start_idx = end_idx
        
    return chapters

def convert_pdf(pdf_path: Path, output_dir: Path | None = None, workspace_dir: Path | None = None) -> bool:
    """Convert PDF to chunked markdown files with images."""
    try:
        import pymupdf4llm
    except ImportError:
        _logger.error("pymupdf4llm not installed: pip install pymupdf4llm")
        return False

    if not pdf_path.exists():
        _logger.error(f"PDF not found: {pdf_path}")
        return False

    # Setup output directory
    if output_dir is None:
        stem = re.sub(r"[^a-zA-Z0-9À-ỹ]+", "_", pdf_path.stem).strip("_")
        output_dir = pdf_path.parent / f"{stem}_MD"

    if output_dir.exists():
        shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    _logger.info(f"Converting PDF: {pdf_path.name}")
    
    try:
        # Change CWD to avoid pymupdf4llm slugifying absolute paths with spaces
        import os
        old_cwd = os.getcwd()
        os.chdir(str(output_dir))
        
        # 1. Extract markdown and images page by page
        try:
            chunks = pymupdf4llm.to_markdown(
                str(pdf_path), 
                page_chunks=True, 
                write_images=True, 
                image_path="."
            )
        finally:
            os.chdir(old_cwd)
        
        # 2. Optimize extracted images
        _optimize_images(output_dir)
        
        # 3. Determine chapters/chunking
        chapters = None
        if workspace_dir and (toc_file := workspace_dir / "_toc.json").exists():
            chapters = _load_custom_toc(toc_file)
            if chapters:
                _logger.info("Using custom _toc.json for chunking")
                
        if not chapters:
            chapters = _get_embedded_toc(pdf_path)
            if chapters:
                _logger.info("Using embedded PDF TOC for chunking")
                
        pages_text = [chunk.get('text', '') for chunk in chunks]
        
        if not chapters:
            _logger.info("No TOC found. Using smart chunking (approx 15 pages).")
            chapters = _smart_chunking(pages_text, target_size=15)
            
        # 4. Write markdown chunks
        toc_chapters = []
        text_samples = []
        for idx, chapter in enumerate(chapters):
            start_p = max(0, chapter.get("page_start", 1) - 1)
            end_p = min(len(pages_text), chapter.get("page_end", start_p + 1))
            
            if start_p >= len(pages_text):
                continue
                
            chapter_text = "\n\n".join(pages_text[start_p:end_p])
            if len(text_samples) < 5:
                text_samples.append(chapter_text[:2000])
            
            # Clean up image paths (pymupdf4llm generates absolute paths or full paths, we want relative)
            # Find ![img](path/to/image.jpg) -> ![img](image.jpg)
            chapter_text = re.sub(r'!\[(.*?)\]\([^)]*[/\\]([^/\\)]+\.(png|jpg|jpeg))\)', r'![\1](\2)', chapter_text)
            
            # Add chapter title as H1 if not already there
            title = chapter.get("title_vi", f"Chapter {idx+1}")
            if not chapter_text.strip().startswith("# "):
                chapter_text = f"# {title}\n\n{chapter_text}"
                
            file_name = f"{idx+1:02d}_{re.sub(r'[^a-zA-Z0-9À-ỹ]+', '_', title.lower()).strip('_')[:50]}.md"
            out_file = output_dir / file_name
            
            out_file.write_text(chapter_text, encoding="utf-8")
            
            # Store chapter in original TOC (canonical schema v8.0)
            toc_chapters.append({
                "chapter_num": idx + 1,
                "title_vi": title,
                "title_original": title,
                "description_vi": None,
                "epub_file": file_name,
                "page_start": chapter.get("page_start", start_p + 1),
                "page_end": chapter.get("page_end", end_p)
            })
            
        # Write _toc_original.json (canonical schema v8.0)
        if chapters:
            clean_title = pdf_path.stem.replace("_", " ")
            sample_text = "\n".join(text_samples)
            lang = "vi" if _is_vietnamese(sample_text) else "en"
            _logger.info(f"Auto-detected language for PDF: {lang}")
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
                _logger.info(f"Original TOC template saved for PDF: {toc_original_path.name}")
            except OSError as e:
                _logger.warning(f"Failed to write _toc_original.json: {e}")
            
        _logger.info(f"Successfully converted PDF into {len(chapters)} markdown chunks.")
        return True
        
    except Exception as e:
        _logger.error(f"Failed to convert PDF: {e}", exc_info=True)
        return False
