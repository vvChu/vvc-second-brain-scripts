"""VvC Second Brain — Semantic Overlap BM25 Fallback Subsystem (v8.15.13).

Provides 2-tier caching (mtime/size + date_modified) and BM25 + LLM arbitrator
fallback when VectorStore embeddings are temporarily unavailable.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from core.config import cfg
from core.llm import call_llm

_logger = logging.getLogger("vvc.merger.fallback")


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase words of length > 2."""
    return [w for w in re.findall(r"\w+", text.lower()) if len(w) > 2]


def _extract_frontmatter_date_modified(p: Path) -> str | None:
    """Read first 2KB to extract frontmatter date_modified without full file read."""
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            match = re.search(r"^date_modified:\s*['\"]?([\d-]+)['\"]?", f.read(2048), re.MULTILINE)
            return match.group(1).strip() if match else None
    except Exception:
        return None


def _sync_single_concept_cache(p: Path, cached_concepts: dict) -> bool:
    """Validate and sync cache entry for a single concept file.

    Returns:
        True if cache entry was created or updated, False otherwise.
    """
    stem = p.stem
    try:
        stat = p.stat()
        current_mtime = stat.st_mtime
        current_size = stat.st_size
    except Exception:
        return False

    cached_entry = cached_concepts.get(stem)

    # Level 1 Hit: OS metadata matches exactly
    if (
        cached_entry
        and cached_entry.get("mtime") == current_mtime
        and cached_entry.get("size") == current_size
    ):
        return False

    # Level 2 Hit: date_modified matches
    current_date_modified = _extract_frontmatter_date_modified(p)
    if cached_entry and cached_entry.get("date_modified") == current_date_modified:
        cached_entry["mtime"] = current_mtime
        cached_entry["size"] = current_size
        return True

    # Cache Miss: read and re-index
    try:
        content = p.read_text(encoding="utf-8")
        is_valid = not ("confidence: low" in content or "source_type: stub" in content)
        cached_concepts[stem] = {
            "date_modified": current_date_modified,
            "tokens": _tokenize(content) if is_valid else [],
            "is_valid": is_valid,
            "mtime": current_mtime,
            "size": current_size,
        }
        return True
    except Exception as e:
        _logger.warning(f"[BM25 Cache] Cannot parse file '{p.name}': {e}")
        return False


def load_and_sync_bm25_cache(concept_files: list[Path]) -> dict:
    """Load, verify, and incrementally update BM25 token cache."""
    cache_path = cfg.state_dir / "_bm25_cache.json"
    cache = {"version": "1.0", "concepts": {}}

    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if loaded.get("version") == "1.0" and isinstance(loaded.get("concepts"), dict):
                    cache = loaded
        except Exception as e:
            _logger.warning(f"[BM25 Cache] Failed to load cache file, reinitializing: {e}")

    cached_concepts = cache["concepts"]
    active_stems = {p.stem for p in concept_files}
    cache_dirty = False

    stems_to_remove = [stem for stem in cached_concepts if stem not in active_stems]
    if stems_to_remove:
        for stem in stems_to_remove:
            del cached_concepts[stem]
        cache_dirty = True

    for p in concept_files:
        if _sync_single_concept_cache(p, cached_concepts):
            cache_dirty = True

    if cache_dirty:
        try:
            temp_path = cache_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            temp_path.replace(cache_path)
            _logger.info(f"[BM25 Cache] Updated and saved incremental cache ({len(cached_concepts)} files).")
        except Exception as e:
            _logger.error(f"[BM25 Cache] Failed to write cache file: {e}")

    return cached_concepts


def _collect_top_bm25_candidates(
    sources: list[str],
    tokenized_corpus: list[list[str]],
    tokenized_query: list[str],
) -> list[tuple[str, str]]:
    """Index via BM25Okapi and return Top 3 candidates with JIT content loading."""
    from rank_bm25 import BM25Okapi
    import numpy as np

    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(tokenized_query)
    top_indices = np.argsort(scores)[::-1][:3]

    candidates: list[tuple[str, str]] = []
    for idx in top_indices:
        if scores[idx] > 0:
            stem = sources[idx]
            concept_path = cfg.concepts_dir / f"{stem}.md"
            if concept_path.exists():
                try:
                    candidates.append((stem, concept_path.read_text(encoding="utf-8")))
                except Exception as e:
                    _logger.warning(f"[Merger Fallback] JIT read failed for '{stem}': {e}")
    return candidates


def _consult_fallback_llm(
    new_text: str,
    candidates: list[tuple[str, str]],
    sources: list[str],
) -> tuple[str, float] | None:
    """Consult LLM to arbitrate semantic match among candidates."""
    candidates_str = "\n\n".join([f"Candidate [{stem}]:\n```markdown\n{c[:1500]}...\n```" for stem, c in candidates])
    validate_prompt = (
        f"Bạn là Trọng tài Ngữ nghĩa tối cao của hệ thống Zettelkasten.\n"
        f"Dịch vụ Vector Embeddings đang gặp sự cố mạng tạm thời. Hãy giúp tôi so khớp ngữ nghĩa thủ công.\n\n"
        f"GHI CHÚ MỚI CHUẨN BỊ LƯU:\n```markdown\n{new_text[:2000]}\n```\n\n"
        f"DANH SÁCH 3 ỨNG VIÊN CÓ THỂ TRÙNG LẶP (Được lọc sơ bộ bằng BM25):\n{candidates_str}\n\n"
        f"YÊU CẦU: Hãy phân tích xem ghi chú mới có trùng khớp ngữ nghĩa học thuật cốt lõi (Semantic Equivalence) "
        f"với bất kỳ ứng viên nào trong danh sách trên hay không (độ tương đồng ngữ nghĩa >= 88%, bàn về cùng một khái niệm, cùng bản chất tri thức).\n\n"
        f"- Nếu CÓ trùng khớp, hãy trả về CHÍNH XÁC tên ứng viên đó trong ngoặc vuông, ví dụ: [ngon_ngu_chung_ubiquitous_language_giua_nguoi_va_ai].\n"
        f"- Nếu KHÔNG trùng khớp với bất kỳ ứng viên nào, trả về: NONE.\n\n"
        f"Chỉ trả lời duy nhất định dạng [tên_ứng_viên] hoặc NONE, không giải thích thêm."
    )
    decision = call_llm(validate_prompt, task="synthesis")
    if decision:
        match = re.search(r"\[(.*?)\]", decision.strip())
        if match:
            matched_stem = match.group(1).strip()
            if matched_stem in sources:
                _logger.info(f"[Merger Fallback] BM25+LLM matched concept overlap with '{matched_stem}'")
                return matched_stem, 0.90
    return None


def find_semantic_overlap_fallback(new_text: str) -> tuple[str, float] | None:
    """Fallback mechanism using BM25 to find candidates, then consulting LLM for semantic verification."""
    try:
        concept_files = list(cfg.concepts_dir.glob("*.md"))
        if not concept_files:
            return None

        cached_concepts = load_and_sync_bm25_cache(concept_files)
        sources = []
        tokenized_corpus = []

        for stem in sorted(cached_concepts.keys()):
            entry = cached_concepts[stem]
            if entry.get("is_valid", False):
                sources.append(stem)
                tokenized_corpus.append(entry["tokens"])

        if not tokenized_corpus:
            _logger.warning("[Merger Fallback] No valid concepts found for BM25 indexing.")
            return None

        tokenized_query = _tokenize(new_text)
        candidates = _collect_top_bm25_candidates(sources, tokenized_corpus, tokenized_query)
        if not candidates:
            return None

        return _consult_fallback_llm(new_text, candidates, sources)
    except Exception as e:
        _logger.error(f"[Merger Fallback] Critical error during BM25 fallback: {e}")
        return None
