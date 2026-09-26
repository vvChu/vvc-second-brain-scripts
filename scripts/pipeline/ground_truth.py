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
_SKIP_CHAPTER_WORDS = ("photo", "bibliography", "source", "copyright", "dedication", "contents", "note", "prologue", "acknowledgment")


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
        return json.loads(toc_path.read_text(encoding="utf-8"))
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
    pat = re.compile(rf"(?:^|[^a-zA-Z0-9])(?:chapter|ch)_?(?:{chapter_num}|{chapter_num:02d})(?:[^a-zA-Z0-9]|$)", re.I)
    candidates = [f for f in md_files if not any(w in f.stem.lower() for w in _SKIP_CHAPTER_WORDS)]
    for f in candidates:
        if pat.search(f.stem):
            return f
    for f in candidates:
        m = re.search(r"\d+", f.stem)
        if m and int(m.group()) == chapter_num:
            return f
    return None


def _match_chapter_epub(ch: dict, book_name: str) -> str | None:
    """Find matching chapter file in markdown corpus if missing from TOC entry."""
    md_dir = _find_md_dir(book_name)
    chapter_num = ch.get("chapter_num")
    if md_dir and chapter_num is not None:
        matched = _match_chapter_file(chapter_num, list(md_dir.glob("*.md")))
        if matched:
            ch["epub_file"] = matched.name
            return matched.name
    return None


def resolve_chapter(page: int | None, book_name: str) -> list[str]:
    """Resolve chapter file(s) from page number via _toc.json."""
    if page is None:
        return []
    chapters = _load_toc(cfg.fleeting_dir / book_name)
    if not chapters:
        return []

    def _val(x: dict) -> int:
        try: return int(x.get("page_start") or 0)
        except (ValueError, TypeError): return 0

    sorted_ch = sorted(chapters, key=_val)
    for i, ch in enumerate(sorted_ch):
        if ch.get("page_end") is None:
            n_start = _val(sorted_ch[i + 1]) if i < len(sorted_ch) - 1 else 0
            ch["page_end"] = n_start - 1 if n_start > 0 else (9999 if i == len(sorted_ch) - 1 else None)

    resolved = []
    for ch in sorted_ch:
        try: p_start = int(ch.get("page_start") or 0)
        except (ValueError, TypeError): p_start = 0
        try: p_end = int(ch.get("page_end") if ch.get("page_end") is not None else 9999)
        except (ValueError, TypeError): p_end = 9999

        if p_start <= page <= p_end:
            epub_file = ch.get("epub_file") or _match_chapter_epub(ch, book_name)
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
        try: text = md_file.read_text(encoding="utf-8")
        except OSError: continue
        for para in re.split(r"\n\n+", text):
            clean = para.strip()
            if len(clean) >= 50 and not clean.startswith("<!--") and not (clean.startswith("#") and "\n" not in clean):
                corpus.append((md_file.stem, clean))
    _logger.info(f"Corpus: {len(corpus)} paragraphs from {book_name} (filter: {chapter_filter or 'ALL'})")
    return corpus


def _bm25_search(query: str, corpus: list[tuple[str, str]], top_k: int = 5) -> list[tuple[str, str, float]]:
    """Run BM25 search over corpus paragraphs."""
    if not corpus or not _HAS_BM25:
        return []
    bm25 = _BM25Okapi([para.lower().split() for _, para in corpus])
    scores = bm25.get_scores(query.lower().split())
    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
    return [(corpus[i][0], corpus[i][1], float(s)) for i, s in indexed]


def _get_embeddings_batch(texts: list[str]) -> list[list[float]] | None:
    """Fetch batch of L2-normalized embedding vectors from AI Gateway."""
    if not cfg.gateway_url or not cfg.gateway_api_key or not texts:
        return None
    import numpy as np, requests
    url = f"{cfg.gateway_url.rstrip('/')}/embeddings"
    headers = {"Authorization": f"Bearer {cfg.gateway_api_key}", "Content-Type": "application/json"}
    payload = {"model": "gemini-embed", "input": [t[:2000] for t in texts]}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=12)
        resp.raise_for_status()
        vectors = []
        for item in resp.json()["data"]:
            emb = np.array(item["embedding"], dtype=np.float32)
            norm = np.linalg.norm(emb)
            vectors.append((emb / norm if norm > 0 else emb).tolist())
        return vectors
    except Exception as e:
        _logger.warning(f"Batch embedding request failed: {e}. Falling back to BM25.")
        return None


def _translate_query_to_english(ocr_text: str) -> str:
    """Translate Vietnamese OCR query to English using fast LLM for BM25 matching."""
    if not ocr_text.strip() or not _is_vietnamese(ocr_text):
        return ocr_text
    prompt = (
        "You are a professional search translation assistant.\n"
        "Translate the following Vietnamese book excerpt into raw English.\n"
        "Keep the meaning, names, and key terms exact. Do NOT explain, do NOT add introduction, just output the English translation directly.\n\n"
        f"Vietnamese excerpt:\n---\n{ocr_text}\n---\n\nEnglish translation:"
    )
    try:
        translated = call_llm(prompt, task="correction")
        clean_trans = translated.strip() if translated else ""
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
    return bool(re.search(r"[àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệđìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ]", text.lower())) if text else False


def _detect_corpus_is_vietnamese(book_name: str, corpus: list[tuple[str, str]]) -> bool:
    """Detect if book corpus is Vietnamese or English."""
    toc_data = _load_toc_data(cfg.fleeting_dir / book_name)
    static_lang = toc_data.get("language") if toc_data else None
    if static_lang in ("vi", "en"):
        _logger.info(f"Corpus language statically resolved as {'Vietnamese' if static_lang == 'vi' else 'English'} from _toc.json")
        return static_lang == "vi"
    is_vi = any(_is_vietnamese(p) for _, p in corpus[:10])
    _logger.info(f"Corpus language dynamically detected as {'Vietnamese' if is_vi else 'English'} via paragraph sampling")
    return is_vi


def _prepare_search_query(ocr_text: str, book_name: str, corpus: list[tuple[str, str]]) -> str:
    """Resolve and translate search query based on corpus language."""
    if _detect_corpus_is_vietnamese(book_name, corpus):
        _logger.info(f"Corpus detected as Vietnamese. Using raw query for BM25: '{ocr_text[:100]}...'")
        return ocr_text
    query = _translate_query_to_english(ocr_text)
    _logger.info(f"Corpus detected as English. Using English query for BM25: '{query[:100]}...'")
    return query


def _rerank_results(query: str, results: list[tuple[str, str, float]]) -> tuple[str, str, float]:
    """Re-rank BM25 candidate results using AI Gateway vector embeddings if available."""
    fallback_ch, fallback_para, fallback_score = results[0]
    embeddings = _get_embeddings_batch([query] + [r[1] for r in results])
    if not embeddings or len(embeddings) != len(results) + 1:
        _logger.info("Semantic re-ranking skipped — using BM25 top-1 as fallback.")
        return fallback_ch, fallback_para, fallback_score

    import numpy as np
    query_vec = np.array(embeddings[0], dtype=np.float32)
    cand_vecs = np.array(embeddings[1:], dtype=np.float32)
    similarities = np.dot(cand_vecs, query_vec)
    best_idx = int(np.argmax(similarities))
    ch, para, score = results[best_idx]
    _logger.info(
        f"Semantic re-ranking: best_idx={best_idx}, cosine={float(similarities[best_idx]):.4f}, "
        f"chapter='{ch}' (BM25 rank was #{best_idx + 1}, score={score:.1f})"
    )
    return ch, para, score


def find_ground_truth(ocr_text: str, book_name: str, *, page: int | None = None) -> GroundTruthResult:
    """Find best matching Ground Truth paragraph for OCR text."""
    chapter_filter = resolve_chapter(page, book_name)
    corpus = _load_corpus(book_name, chapter_filter or None)
    if not corpus:
        return GroundTruthResult("", 0.0, "", page)

    query = _prepare_search_query(ocr_text, book_name, corpus)
    results = _bm25_search(query, corpus, top_k=5)
    if not results:
        return GroundTruthResult("", 0.0, "", page)

    ch, para, score = _rerank_results(query, results)
    _logger.info(f"GT match: score={score:.1f}, chapter={ch}")
    if score < 15.0:
        _logger.warning(f"GT score too low ({score:.1f})")
        return GroundTruthResult("", score, ch, page)
    return GroundTruthResult(para, score, ch, page)


def _extract_gt_paragraphs(ground_truth_text: str) -> list[str]:
    """Extract clean paragraphs from ground truth text (stripping quotes, callouts, citations)."""
    paragraphs: list[str] = []
    current_para: list[str] = []
    for raw_line in ground_truth_text.splitlines():
        line = raw_line.strip()
        if line.startswith(">"):
            line = line.lstrip(">").strip()
        if re.match(r"^\[![\w\-]+\]", line) or re.match(r"^[—\-]{1,2}\s*(?:\*\*|[A-Z])", line):
            continue
        if line:
            current_para.append(line)
        elif current_para:
            paragraphs.append(" ".join(current_para))
            current_para = []
    if current_para:
        paragraphs.append(" ".join(current_para))
    return paragraphs or [ground_truth_text.strip()]


def _find_paragraph_position(chapter_text: str, para: str) -> int:
    """Find position of paragraph in chapter text using multi-tier fallback matching."""
    clean = re.sub(r"\s+", " ", para.strip().strip('"\'“”«»‘’„”')).strip()
    if not clean or len(clean) < 15:
        return -1
    for target in (clean, para.strip() if para.strip() != clean else "", clean[:80].strip()):
        if target:
            pos = chapter_text.find(target)
            if pos != -1: return pos

    words = clean.split()
    if len(words) >= 3:
        m = re.search(r"\s+".join(re.escape(w) for w in words[:min(8, len(words))]), chapter_text, re.I)
        if m: return m.start()
    if len(clean) > 80:
        if len(words) >= 8:
            mid = len(words) // 2
            m = re.search(r"\s+".join(re.escape(w) for w in words[mid : mid + min(6, len(words) - mid)]), chapter_text, re.I)
            if m: return m.start()
        return chapter_text.find(clean[len(clean) // 2 : len(clean) // 2 + 80].strip())
    return -1


def find_images_around_ground_truth(
    chapter_text: str,
    ground_truth_text: str,
    window_radius: int = 800,
) -> list[str]:
    """Scan for embedded image references within a character window around Ground Truth."""
    if not chapter_text or not ground_truth_text:
        return []

    paragraphs = _extract_gt_paragraphs(ground_truth_text)
    image_regex = re.compile(
        r'!\[\[([^\]]+\.(?:jpg|jpeg|png|webp))\]\]|!\[.*?\]\(([^\)]+\.(?:jpg|jpeg|png|webp))\)',
        re.IGNORECASE,
    )
    found_images: list[str] = []

    for para in paragraphs:
        pos = _find_paragraph_position(chapter_text, para)
        if pos != -1:
            start_win = max(0, pos - window_radius)
            end_win = min(len(chapter_text), pos + len(para) + window_radius)
            for m in image_regex.finditer(chapter_text[start_win:end_win]):
                img = (m.group(1) or m.group(2) or "").strip()
                if img and img not in found_images:
                    found_images.append(img)

    return found_images
