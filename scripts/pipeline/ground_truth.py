"""VvC Second Brain — Ground Truth Matching & OCR Correction (v8.0).

BM25 chapter-scoped search + Semantic Re-ranking (AI Gateway Embeddings)
against book corpus + LLM-based OCR correction.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import NamedTuple

from core.config import cfg
from core.llm import call_llm
from core.prompts.pipeline import OCR_CORRECTION as _CORRECTION_PROMPT
from pipeline.book_assets import find_book_md_dir

try:
    from rank_bm25 import BM25Okapi as _BM25Okapi
    _HAS_BM25 = True
except ImportError:
    _BM25Okapi = None  # type: ignore[assignment,misc]
    _HAS_BM25 = False

_logger = logging.getLogger("vvc.gt")


class GroundTruthResult(NamedTuple):
    """Result from Ground Truth matching."""
    paragraph: str
    score: float
    chapter: str
    page: int | None


def _load_toc_data(book_dir: Path) -> dict | None:
    """Load the full _toc.json dictionary from a book workspace."""
    toc_path = book_dir / "_toc.json"
    if not toc_path.exists():
        return None
    try:
        with open(toc_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _load_toc(book_dir: Path) -> list[dict] | None:
    """Load _toc.json from a book workspace."""
    data = _load_toc_data(book_dir)
    return data.get("chapters", []) if data else None



def _find_md_dir(book_name: str) -> Path | None:
    return find_book_md_dir(book_name, books_dir=cfg.resources_books_dir)


def _match_chapter_file(chapter_num: int, md_files: list[Path]) -> Path | None:
    """Match a chapter number to a file in the markdown corpus using fuzzy regex."""
    for f in md_files:
        stem = f.stem.lower()
        if any(word in stem for word in ["photo", "bibliography", "source", "copyright", "dedication", "contents", "note", "prologue", "acknowledgment"]):
            continue
        patterns = [
            rf"(?:^|[^a-zA-Z0-9])chapter_{chapter_num}(?:[^a-zA-Z0-9]|$)",
            rf"(?:^|[^a-zA-Z0-9])chapter_{chapter_num:02d}(?:[^a-zA-Z0-9]|$)",
            rf"(?:^|[^a-zA-Z0-9])ch_{chapter_num}(?:[^a-zA-Z0-9]|$)",
            rf"(?:^|[^a-zA-Z0-9])ch_{chapter_num:02d}(?:[^a-zA-Z0-9]|$)",
            rf"(?:^|[^a-zA-Z0-9])ch{chapter_num}(?:[^a-zA-Z0-9]|$)",
            rf"(?:^|[^a-zA-Z0-9])ch{chapter_num:02d}(?:[^a-zA-Z0-9]|$)",
            rf"(?:^|[^a-zA-Z0-9])chapter{chapter_num}(?:[^a-zA-Z0-9]|$)",
            rf"(?:^|[^a-zA-Z0-9])chapter{chapter_num:02d}(?:[^a-zA-Z0-9]|$)",
        ]
        for pat in patterns:
            if re.search(pat, stem):
                return f
    # Fallback to independent integer matching
    for f in md_files:
        stem = f.stem.lower()
        if any(word in stem for word in ["photo", "bibliography", "source", "copyright", "dedication", "contents", "note", "prologue", "acknowledgment"]):
            continue
        match = re.search(r"\d+", stem)
        if match and int(match.group()) == chapter_num:
            return f
    return None


def resolve_chapter(page: int | None, book_name: str) -> list[str]:
    """Resolve chapter file(s) from page number via _toc.json."""
    if page is None:
        return []
    chapters = _load_toc(cfg.fleeting_dir / book_name)
    if not chapters:
        return []
    
    def _get_page_start(x):
        val = x.get("page_start")
        if val is None:
            return 0
        try:
            return int(val)
        except (ValueError, TypeError):
            return 0

    # Calculate page_end dynamically if missing or None
    sorted_chapters = sorted(chapters, key=_get_page_start)
    for i in range(len(sorted_chapters)):
        ch = sorted_chapters[i]
        if "page_end" not in ch or ch["page_end"] is None:
            if i < len(sorted_chapters) - 1:
                next_start = _get_page_start(sorted_chapters[i + 1])
                ch["page_end"] = next_start - 1 if next_start > 0 else None
            else:
                ch["page_end"] = 9999

    resolved = []
    for ch in sorted_chapters:
        page_start = ch.get("page_start", 0)
        page_end = ch.get("page_end", 9999)
        # Handle string type conversion safely if needed
        try:
            page_start = int(page_start)
        except (ValueError, TypeError):
            page_start = 0
        try:
            page_end = int(page_end)
        except (ValueError, TypeError):
            page_end = 9999

        if page_start <= page <= page_end:
            epub_file = ch.get("epub_file")
            if not epub_file:
                # Try to map english chapter file automatically
                md_dir = _find_md_dir(book_name)
                if md_dir:
                    chapter_num = ch.get("chapter_num")
                    if chapter_num is not None:
                        md_files = list(md_dir.glob("*.md"))
                        matched_file = _match_chapter_file(chapter_num, md_files)
                        if matched_file:
                            epub_file = matched_file.name
                            ch["epub_file"] = epub_file # cache it
            if epub_file:
                resolved.append(epub_file)
                
    if resolved:
        _logger.info(f"Resolved page {page} directly to chapter files via pre-generated aligned TOC: {resolved}")
    return resolved


def _load_corpus(book_name: str, chapter_filter: list[str] | None = None) -> list[tuple[str, str]]:
    """Load markdown paragraphs from book's extracted MD corpus."""
    md_dir = _find_md_dir(book_name)
    if not md_dir:
        return []

    corpus: list[tuple[str, str]] = []
    for md_file in sorted(md_dir.glob("*.md")):
        if chapter_filter and not any(cf.lower() in md_file.name.lower() for cf in chapter_filter):
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for para in re.split(r"\n\n+", text):
            clean = para.strip()
            if len(clean) < 50 or clean.startswith("<!--") or (clean.startswith("#") and "\n" not in clean):
                continue
            corpus.append((md_file.stem, clean))

    _logger.info(f"Corpus: {len(corpus)} paragraphs from {book_name} (filter: {chapter_filter or 'ALL'})")
    return corpus

def _bm25_search(query: str, corpus: list[tuple[str, str]], top_k: int = 5) -> list[tuple[str, str, float]]:
    """Run BM25 search over corpus paragraphs."""
    if not corpus or not _HAS_BM25:
        return []

    tokenized = [para.lower().split() for _, para in corpus]
    bm25 = _BM25Okapi(tokenized)
    scores = bm25.get_scores(query.lower().split())
    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
    return [(corpus[i][0], corpus[i][1], float(s)) for i, s in indexed]


def _get_embeddings_batch(texts: list[str]) -> list[list[float]] | None:
    """Fetch batch of L2-normalized embedding vectors from AI Gateway.

    Args:
        texts: List of text strings to embed (query + candidates).

    Returns:
        List of normalized embedding vectors, or None on failure.
    """
    if not cfg.gateway_url or not cfg.gateway_api_key or not texts:
        return None

    import requests
    import numpy as np

    url = f"{cfg.gateway_url.rstrip('/')}/embeddings"
    headers = {
        "Authorization": f"Bearer {cfg.gateway_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gemini-embed",
        "input": [t[:2000] for t in texts],
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=12)
        resp.raise_for_status()
        data = resp.json()["data"]

        vectors = []
        for item in data:
            emb = np.array(item["embedding"], dtype=np.float32)
            norm = np.linalg.norm(emb)
            normalized = emb / norm if norm > 0 else emb
            vectors.append(normalized.tolist())
        return vectors
    except Exception as e:
        _logger.warning(f"Batch embedding request failed: {e}. Falling back to BM25.")
        return None


def _translate_query_to_english(ocr_text: str) -> str:
    """Translate Vietnamese OCR query to English using fast LLM for BM25 matching."""
    if not ocr_text.strip():
        return ""
    
    # Check if the text actually contains Vietnamese accented characters
    has_vietnamese = bool(re.search(r"[àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệđìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ]", ocr_text.lower()))
    if not has_vietnamese:
        return ocr_text

    prompt = f"""You are a professional search translation assistant. 
Translate the following Vietnamese book excerpt into raw English. 
Keep the meaning, names, and key terms exact. Do NOT explain, do NOT add introduction, just output the English translation directly.

Vietnamese excerpt:
---
{ocr_text}
---

English translation:"""
    
    try:
        translated = call_llm(prompt, task="correction")
        clean_trans = translated.strip()
        if clean_trans:
            _logger.info(f"Query JIT Translated successfully. Length: {len(clean_trans)} chars")
            return clean_trans
    except Exception as e:
        _logger.warning(f"Failed to translate query to English: {e}. Using raw OCR text.")
    
    return ocr_text


def correct_ocr(ocr_text: str, ground_truth: str) -> str:
    """Auto-correct OCR text using Ground Truth reference."""
    if not ground_truth or not ocr_text:
        return ocr_text
    corrected = call_llm(
        _CORRECTION_PROMPT.format(ocr_text=ocr_text, ground_truth=ground_truth),
        task="correction",
    )
    if not corrected or len(corrected) < max(20, len(ocr_text) * 0.3):
        return ocr_text
    return corrected


def _is_vietnamese(text: str) -> bool:
    """Check if the text contains Vietnamese accented characters."""
    if not text:
        return False
    return bool(re.search(r"[àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệđìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ]", text.lower()))


def find_ground_truth(ocr_text: str, book_name: str, *, page: int | None = None) -> GroundTruthResult:
    """Find best matching Ground Truth paragraph for OCR text."""
    chapter_filter = resolve_chapter(page, book_name)
    corpus = _load_corpus(book_name, chapter_filter or None)
    if not corpus:
        return GroundTruthResult("", 0.0, "", page)

    # Detect corpus language
    corpus_has_vietnamese = False
    
    # Try loading from static language first
    toc_data = _load_toc_data(cfg.fleeting_dir / book_name)
    static_lang = toc_data.get("language") if toc_data else None
    
    if static_lang == "vi":
        corpus_has_vietnamese = True
        _logger.info("Corpus language statically resolved as Vietnamese from _toc.json")
    elif static_lang == "en":
        corpus_has_vietnamese = False
        _logger.info("Corpus language statically resolved as English from _toc.json")
    else:
        # Dynamic fallback: Check first 10 paragraphs for Vietnamese
        sample_paras = [para for _, para in corpus[:10]]
        if any(_is_vietnamese(p) for p in sample_paras):
            corpus_has_vietnamese = True
            _logger.info("Corpus language dynamically detected as Vietnamese via paragraph sampling")
        else:
            _logger.info("Corpus language dynamically detected as English via paragraph sampling")

    if corpus_has_vietnamese:
        query = ocr_text
        _logger.info(f"Corpus detected as Vietnamese. Using raw query for BM25: '{query[:100]}...'")
    else:
        # JIT Query Translation for cross-language matching
        query = _translate_query_to_english(ocr_text)
        _logger.info(f"Corpus detected as English. Using English query for BM25: '{query[:100]}...'")

    results = _bm25_search(query, corpus, top_k=5)
    if not results:
        return GroundTruthResult("", 0.0, "", page)

    # BM25 fallback: always use top-1 as the safe default
    fallback_ch, fallback_para, fallback_score = results[0]

    # --- Semantic Re-ranking ---
    ch, para, score = fallback_ch, fallback_para, fallback_score
    embeddings = _get_embeddings_batch([query] + [r[1] for r in results])
    if embeddings and len(embeddings) == len(results) + 1:
        import numpy as np
        query_vector = np.array(embeddings[0], dtype=np.float32)
        candidate_vectors = np.array(embeddings[1:], dtype=np.float32)

        similarities = np.dot(candidate_vectors, query_vector)
        best_idx = int(np.argmax(similarities))
        best_similarity = float(similarities[best_idx])

        ch, para, score = results[best_idx][0], results[best_idx][1], results[best_idx][2]
        _logger.info(
            f"Semantic re-ranking: best_idx={best_idx}, "
            f"cosine={best_similarity:.4f}, chapter='{ch}' "
            f"(BM25 rank was #{best_idx + 1}, score={score:.1f})"
        )
    else:
        _logger.info("Semantic re-ranking skipped — using BM25 top-1 as fallback.")

    _logger.info(f"GT match: score={score:.1f}, chapter={ch}")
    if score < 15.0:
        _logger.warning(f"GT score too low ({score:.1f})")
        return GroundTruthResult("", score, ch, page)

    return GroundTruthResult(para, score, ch, page)


def find_images_around_ground_truth(
    chapter_text: str,
    ground_truth_text: str,
    window_radius: int = 800,
) -> list[str]:
    """Scan for embedded image references within a character window around Ground Truth.

    Parses ground_truth_text into paragraphs, finds their locations in chapter_text,
    and collects unique image filenames referenced via Obsidian wiki-links (![[image.ext]])
    or Markdown images (![alt](image.ext)) within ±window_radius chars around each match.

    Args:
        chapter_text: Full markdown content of the chapter.
        ground_truth_text: Ground truth quote/text (can be raw text, blockquote formatted,
            or enclosed in quotation marks).
        window_radius: Character radius to expand search before and after match (default 800).

    Returns:
        List of unique image filenames found within the search windows, in order of discovery.
    """
    if not chapter_text or not ground_truth_text:
        return []

    # Extract clean paragraphs (handling raw text, blockquote formatting, callouts, and citations)
    paragraphs: list[str] = []
    current_para: list[str] = []
    for raw_line in ground_truth_text.splitlines():
        line = raw_line.strip()
        if line.startswith(">"):
            line = line.lstrip(">").strip()

        # Skip Obsidian callout headers (e.g. [!quote], [!info])
        if re.match(r"^\[![\w\-]+\]", line):
            continue

        # Skip citation lines (e.g. — **Author**, *Book*...)
        if re.match(r"^[—\-]{1,2}\s*(?:\*\*|[A-Z])", line):
            continue

        if line:
            current_para.append(line)
        else:
            if current_para:
                paragraphs.append(" ".join(current_para))
                current_para = []
    if current_para:
        paragraphs.append(" ".join(current_para))

    if not paragraphs:
        paragraphs = [ground_truth_text.strip()]

    image_regex = re.compile(
        r'!\[\[([^\]]+\.(?:jpg|jpeg|png|webp))\]\]|!\[.*?\]\(([^\)]+\.(?:jpg|jpeg|png|webp))\)',
        re.IGNORECASE,
    )
    found_images: list[str] = []
    quote_chars = '"\'“”«»‘’„”'

    for para in paragraphs:
        # Strip surrounding quotes and normalize internal whitespace
        para_clean = re.sub(r"\s+", " ", para.strip().strip(quote_chars)).strip()
        if not para_clean or len(para_clean) < 15:
            continue

        # 1. Exact search
        pos = chapter_text.find(para_clean)
        if pos == -1 and para != para_clean:
            pos = chapter_text.find(para.strip())

        # 2. Prefix search fallback
        if pos == -1:
            prefix = para_clean[:80].strip()
            pos = chapter_text.find(prefix)

        # 3. Regex search fallback across linebreaks / whitespace differences
        if pos == -1:
            words = para_clean.split()
            if len(words) >= 3:
                first_words = [re.escape(w) for w in words[:min(8, len(words))]]
                pattern = re.compile(r"\s+".join(first_words), re.IGNORECASE)
                m = pattern.search(chapter_text)
                if m:
                    pos = m.start()

        # 4. Middle search fallback for longer paragraphs
        if pos == -1 and len(para_clean) > 80:
            words = para_clean.split()
            if len(words) >= 8:
                mid = len(words) // 2
                mid_words = [re.escape(w) for w in words[mid : mid + min(6, len(words) - mid)]]
                pattern = re.compile(r"\s+".join(mid_words), re.IGNORECASE)
                m = pattern.search(chapter_text)
                if m:
                    pos = m.start()
            if pos == -1:
                middle = para_clean[len(para_clean) // 2 : len(para_clean) // 2 + 80].strip()
                pos = chapter_text.find(middle)

        if pos != -1:
            # Scan ±window_radius chars around the matched position
            start_win = max(0, pos - window_radius)
            end_win = min(len(chapter_text), pos + len(para_clean) + window_radius)
            window = chapter_text[start_win:end_win]

            for m in image_regex.finditer(window):
                img_name = m.group(1) or m.group(2)
                if img_name:
                    img_name = img_name.strip()
                    if img_name not in found_images:
                        found_images.append(img_name)

    return found_images
