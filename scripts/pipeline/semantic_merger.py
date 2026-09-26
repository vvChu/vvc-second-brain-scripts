"""VvC Second Brain — Semantic Knowledge Merger (v8.6).

Extracted from post_process.py to enforce Single Responsibility Principle.
Handles semantic deduplication of concept notes via:
  - Cosine similarity search (AI Gateway Embeddings)
  - 3-Tier Merge Control (Hook Count Gate → Dynamic Size Limit → LLM Arbitrator)
  - MERGE / SEPARATE / SUBSUME decisions
  - Bidirectional cross-linking for SEPARATE decisions
BM25 fallback and token caching extracted to pipeline/semantic_fallback.py.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from core.config import cfg
from core.frontmatter import parse_frontmatter, extract_body, build_frontmatter
from core.llm import call_llm
from core.llm.embedding_client import get_embedding, get_embedding_via_gateway  # noqa: F401
from core.log import log
from core.vector_store import VectorStore
from pipeline.semantic_fallback import (
    load_and_sync_bm25_cache,
    find_semantic_overlap_fallback,
)

_logger = logging.getLogger("vvc.merger")

# Sentinel returned by arbitrate_and_merge when existing note fully subsumes new content
SUBSUME_SENTINEL = Path("__SUBSUMED__")


def find_semantic_overlap(new_text: str) -> tuple[str, float] | None:
    """Find if a concept has extremely high semantic similarity with an existing one.

    Loads the pre-built embedding index and computes cosine similarity
    via fast dot product on L2-normalized vectors.

    Args:
        new_text: Full text of the new concept note.

    Returns:
        Tuple of (existing_stem, similarity_score) if score >= 0.88, else None.
    """
    store = VectorStore.get_instance()
    if store is None or len(store) == 0:
        return None

    query_emb = get_embedding(new_text)
    if query_emb is None:
        _logger.info("[Merger] Embedding is unavailable. Activating BM25 + LLM fallback semantic overlap matching...")
        return find_semantic_overlap_fallback(new_text)

    matches = store.search(query_emb, top_k=1, threshold=0.88)
    if matches:
        return matches[0]

    return None


def _check_subsume(existing_content: str, new_content: str, existing_stem: str) -> bool:
    """Evaluate whether existing note already fully subsumes (absorbs) new content."""
    subsume_prompt = (
        f"Bạn là Trọng tài Zettelkasten tối cao. Hãy đánh giá xem ghi chú hiện tại có bao hàm hoàn toàn (SUBSUME) ghi chú mới hay không.\n\n"
        f"GHI CHÚ HIỆN TẠI:\n```markdown\n{existing_content}\n```\n\n"
        f"GHI CHÚ MỚI:\n```markdown\n{new_content}\n```\n\n"
        f"QUY TẮC ĐÁNH GIÁ:\n"
        f"- Trả lời 'SUBSUME' nếu ghi chú hiện tại đã bao phủ >= 90% nội dung cốt lõi của ghi chú mới. "
        f"Ghi chú mới không bổ sung thêm trích dẫn (quote) mới đáng kể từ trang khác/chương khác, và không đóng góp luận điểm học thuật mới đáng kể nào.\n"
        f"- Trả lời 'NOT_SUBSUME' nếu ghi chú mới thực sự bổ sung thêm trích dẫn mới hữu ích (ví dụ: quote mới từ trang khác, nguồn khác), "
        f"hoặc giới thiệu khía cạnh tri thức mới bổ trợ mà ghi chú cũ chưa phân tích sâu.\n\n"
        f"Trả lời CHÍNH XÁC duy nhất một từ: 'SUBSUME' hoặc 'NOT_SUBSUME'."
    )
    decision = call_llm(subsume_prompt, task="synthesis", allowed_shorts=("SUBSUME", "NOT_SUBSUME"))
    if decision and "SUBSUME" in decision.upper() and "NOT_SUBSUME" not in decision.upper():
        _logger.info(f"[Merger] Priority SUBSUME Check: existing '{existing_stem}.md' fully covers new content. Absorbing without creating files.")
        return True
    return False


def _check_dynamic_size_limit(
    existing_content: str,
    existing_path: Path,
    existing_stem: str,
    is_prune_mode: bool,
) -> bool:
    """Enforce physical boundaries to prevent creating oversized unreadable notes.

    Returns:
        True if allowed to arbitrate, False if size limit is exceeded (force SEPARATE).
    """
    file_size = existing_path.stat().st_size
    if is_prune_mode:
        content_without_quotes = re.sub(r"^>.*$", "", existing_content, flags=re.MULTILINE)
        core_size = len(content_without_quotes.encode("utf-8"))
        if core_size > 6000 or file_size > 10000:
            _logger.info(
                f"[Merger] Dynamic Size Limit (Prune Mode): '{existing_stem}' core_size={core_size} bytes (limit 6,000), "
                f"file_size={file_size} bytes (limit 10,000). Exceeds limit, forcing KEEP SEPARATE."
            )
            return False
        _logger.info(
            f"[Merger] Dynamic Size Limit (Prune Mode) PASSED: '{existing_stem}' core_size={core_size} bytes, "
            f"file_size={file_size} bytes. Allowed to arbitrate."
        )
        return True

    if file_size > 7700:
        _logger.info(
            f"[Merger] Dynamic Size Limit: '{existing_stem}' ({file_size} bytes) exceeds limit (7,700 bytes). "
            f"Force KEEP SEPARATE to preserve readability."
        )
        return False
    return True


def _build_merge_prompt(
    existing_content: str,
    new_content: str,
    hook_count: int,
    is_prune_mode: bool,
) -> str:
    """Construct synthesis prompt for merging two concept notes."""
    prune_instruction = ""
    if is_prune_mode:
        prune_instruction = (
            f"CẢNH BÁO HỢP NHẤT: Ghi chú 1 đã tích lũy {hook_count} Evidence Hooks. Bạn BẮT BUỘC phải thực hiện 'Tỉa cành củng cố' (Consolidated Pruning) một cách nghiêm ngặt:\n"
            f"- So sánh và loại bỏ các trích dẫn tương đồng hoặc bị lặp ý giữa hai ghi chú.\n"
            f"- Nếu có nhiều trích dẫn cùng chung một khía cạnh hoặc cùng từ một chương/trang, hãy kết hợp hoặc chỉ giữ lại trích dẫn sắc bén nhất.\n"
            f"- Đảm bảo tổng số lượng Evidence Hooks sau khi gộp và tỉa cành tuyệt đối KHÔNG vượt quá 4 (ưu tiên giữ 3 trích dẫn tinh túy nhất đại diện cho các nguồn/trang khác nhau).\n"
            f"- Ghi rõ Citation Line học thuật có kèm wiki-link đầy đủ cho từng trích dẫn được giữ lại.\n"
        )

    return (
        f"Bạn là Chuyên gia biên tập Zettelkasten v8.9.9. Hãy hợp nhất hai ghi chú tri thức này thành một ghi chú học thuật duy nhất có giá trị tích lũy cao.\n\n"
        f"GHI CHÚ 1:\n```markdown\n{existing_content}\n```\n\n"
        f"GHI CHÚ 2:\n```markdown\n{new_content}\n```\n\n"
        f"{prune_instruction}"
        f"QUY TẮC HỢP NHẤT BẮT BUỘC:\n"
        f"1. FRONTMATTER YAML: Phải gộp tất cả các tags, sources (thành mảng), related links. Đặt trạng thái `status: evergreen`, `confidence: high`.\n"
        f"2. EVIDENCE HOOKS (Consolidation): Hãy kiểm tra và xếp chồng các Evidence Hooks lên đầu note (standalone blockquotes độc lập ở đầu tệp tin, ghi rõ Citation Line học thuật có wiki-link). "
        f"TUYÊN BỐ QUAN TRỌNG: Nếu hai trích dẫn có ý nghĩa tương đương hoặc lặp ý, hãy cô đọng lại và chỉ giữ lại tối đa 3 trích dẫn tiếng Việt sắc bén nhất đại diện cho các nguồn/trang khác nhau. Tránh xếp chồng quá nhiều blockquotes gây loãng giá trị ghi chú.\n"
        f"3. CORE IDEA: Viết lại phần Core Idea phân tích tổng hợp chiều sâu, chỉ ra điểm giao thoa tri thức, phản biện hoặc bổ trợ giữa hai góc nhìn. Tuyệt đối không lặp lại trích dẫn.\n"
        f"4. GROUND TRUTH: Gom tất cả các đoạn văn tiếng Anh nguyên bản từ phần Ground Truth của cả hai ghi chú cũ.\n"
        f"5. REFERENCES: Gom tất cả các liên kết nguồn thô.\n\n"
        f"Trả về ĐÚNG tệp tin Markdown hoàn chỉnh bắt đầu từ '---' đến hết."
    )


def _synthesize_merged_note(
    existing_path: Path,
    existing_content: str,
    new_content: str,
    hook_count: int,
    is_prune_mode: bool,
) -> Path | None:
    """Synthesize merged note content via LLM and write to existing_path."""
    merge_prompt = _build_merge_prompt(existing_content, new_content, hook_count, is_prune_mode)
    merged_body = call_llm(merge_prompt, task="synthesis")
    if merged_body and len(merged_body) > 200:
        match = re.search(r"(---\n.*)", merged_body, re.DOTALL)
        if match:
            merged_clean = match.group(1)
            merged_clean = re.sub(r"\n```\s*$", "", merged_clean)

            from pipeline.synthesize import fix_section_ordering
            merged_clean = fix_section_ordering(merged_clean)

            existing_path.write_text(merged_clean, encoding="utf-8")
            _logger.info(f"[Merger] Synthesized merge saved successfully to '{existing_path.name}'.")
            log("merge", f"Merged new concept into: {existing_path.name}")
            return existing_path

    _logger.warning("[Merger] Merge synthesis failed. Falling back to SEPARATE.")
    return None


def _consult_arbitrator(
    existing_content: str,
    new_content: str,
    hook_count: int,
    is_prune_mode: bool,
) -> bool:
    """Consult LLM to decide between MERGE (True) and SEPARATE (False)."""
    prune_warning = ""
    if is_prune_mode:
        prune_warning = (
            f"LƯU Ý ĐẶC BIỆT: Ghi chú hiện tại đã tích lũy đủ {hook_count} Evidence Hooks (đạt ngưỡng trần).\n"
            f"Nếu bạn chọn 'MERGE', hệ thống sẽ tự động kích hoạt chế độ 'Tỉa cành củng cố' (Consolidated Pruning) để gộp và chọn lọc các trích dẫn tương đồng, chỉ giữ lại 3-4 trích dẫn tinh túy nhất.\n"
            f"Do đó, hãy tự tin chọn 'MERGE' nếu đây thực sự là cùng một khái niệm cốt lõi!\n\n"
        )

    arbitrate_prompt = (
        f"Bạn là Nhà biên soạn Zettelkasten tối cao. Hai ghi chú tri thức chất lượng cao này có độ tương đồng ngữ nghĩa rất cao và bạn đã xác định ghi chú mới CÓ tri thức bổ trợ (không bị subsume).\n\n"
        f"GHI CHÚ HIỆN CÓ ĐÃ LƯU:\n```markdown\n{existing_content}\n```\n\n"
        f"GHI CHÚ MỚI CHUẨN BỊ LƯU:\n```markdown\n{new_content}\n```\n\n"
        f"{prune_warning}"
        f"YÊU CẦU ĐÁNH GIÁ — Hãy phân biệt chính xác giữa hai quyết định:\n\n"
        f"'MERGE' — Cùng một khái niệm học thuật cốt lõi. Ghi chú mới BỔ SUNG trích dẫn mới, góc nhìn mới tuyệt vời hỗ trợ cho ý tưởng cũ. Việc gộp chung giúp ghi chú Evergreen tích lũy giá trị cao hơn.\n\n"
        f"'SEPARATE' — Dù chia sẻ từ khóa chung, hai ghi chú bàn về hai khía cạnh, luận điểm hoặc bối cảnh hoàn toàn độc lập. Tách biệt giúp Obsidian Graph sạch hơn và tạo liên kết chéo.\n\n"
        f"Trả lời CHÍNH XÁC duy nhất một từ: 'MERGE' hoặc 'SEPARATE'."
    )
    decision = call_llm(arbitrate_prompt, task="synthesis", allowed_shorts=("MERGE", "SEPARATE"))
    return bool(decision and "MERGE" in decision.strip().upper())


def arbitrate_and_merge(new_content: str, existing_stem: str) -> Path | None:
    """Arbitrate if we should merge or separate two highly similar concepts.

    Implements 3-Tier Merge Control:
      - Tier 1: Priority SUBSUME Check
      - Tier 2: Physical Size Constraints & Hook Count Gate
      - Tier 3: LLM Arbitrator (MERGE / SEPARATE)
    """
    existing_path = cfg.concepts_dir / f"{existing_stem}.md"
    if not existing_path.exists():
        return None

    try:
        existing_content = existing_path.read_text(encoding="utf-8")
        existing_fm = parse_frontmatter(existing_content)
        if existing_fm.get("confidence") == "low" or existing_fm.get("source_type") == "stub":
            return None

        # Tier 1: Check for SUBSUME First
        if _check_subsume(existing_content, new_content, existing_stem):
            return SUBSUME_SENTINEL

        # Tier 2: Hook Count Gate & Dynamic Size Limit
        hook_count = len(re.findall(r'^> "', existing_content, re.MULTILINE))
        is_prune_mode = hook_count >= 4
        if is_prune_mode:
            _logger.info(f"[Merger] Hook Count Gate: '{existing_stem}' has {hook_count} evidence hooks. Activating Merge-with-Pruning mode.")

        if not _check_dynamic_size_limit(existing_content, existing_path, existing_stem, is_prune_mode):
            return None

        # Tier 3: LLM Arbitrator
        if _consult_arbitrator(existing_content, new_content, hook_count, is_prune_mode):
            _logger.info(f"[Merger] Arbitrator DECIDED to MERGE into '{existing_stem}.md'. Synthesizing...")
            return _synthesize_merged_note(existing_path, existing_content, new_content, hook_count, is_prune_mode)

        _logger.info("[Merger] Arbitrator DECIDED to KEEP SEPARATE.")
        return None
    except Exception as e:
        _logger.warning(f"[Merger] Exception during arbitration: {e}")
        return None


def execute_cross_linking(path_a: Path, path_b: Path) -> None:
    """Create bidirectional links between A and B in their related YAML array and References."""
    for current_path, target_path in [(path_a, path_b), (path_b, path_a)]:
        if not current_path.exists() or not target_path.exists():
            continue
        try:
            content = current_path.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)
            body = extract_body(content)

            related = fm.get("related", [])
            target_stem = target_path.stem
            target_link = f"[[{target_stem}]]"

            if target_stem not in related:
                related.append(target_stem)
                fm["related"] = related

            if target_link not in body:
                if "## References" in body:
                    body = body.replace("## References", f"## References\n- {target_link}")
                else:
                    body = f"{body.rstrip()}\n\n## References\n- {target_link}\n"

            current_path.write_text(build_frontmatter(fm) + body, encoding="utf-8")
            _logger.info(f"[Merger] Cross-linked [[{target_stem}]] in {current_path.name}")
        except Exception as e:
            _logger.warning(f"Failed to cross-link {current_path.name} to {target_path.name}: {e}")


def log_subsume(
    new_title: str,
    existing_stem: str,
    score: float,
    image_path: Path | None,
) -> None:
    """Append a SUBSUME event to the weekly-reviewable journal."""
    journal_path = cfg.state_dir / ".subsume_journal.jsonl"
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "new_title": new_title,
        "existing_concept": f"{existing_stem}.md",
        "similarity_score": round(score, 4),
        "source_image": str(image_path.name) if image_path else None,
    }
    try:
        with open(journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        _logger.warning(f"Failed to write subsume journal: {e}")
