"""VvC Second Brain — Semantic Knowledge Merger (v8.6).

Extracted from post_process.py to enforce Single Responsibility Principle.
Handles semantic deduplication of concept notes via:
  - Cosine similarity search (AI Gateway Embeddings)
  - 3-Tier Merge Control (Hook Count Gate → Dynamic Size Limit → LLM Arbitrator)
  - MERGE / SEPARATE / SUBSUME decisions
  - Bidirectional cross-linking for SEPARATE decisions
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
from core.log import log

_logger = logging.getLogger("vvc.merger")

# Sentinel returned by arbitrate_and_merge when existing note fully subsumes new content
SUBSUME_SENTINEL = Path("__SUBSUMED__")


def get_embedding_via_gateway(text: str) -> list[float] | None:
    """Fetch L2-normalized embedding vector from AI Gateway.

    Implements a resilient retry mechanism with exponential backoff for transient errors 
    (timeouts, network drops, HTTP 429/5xx), while aborting immediately on fatal errors (HTTP 401/403).

    Args:
        text: Input text (truncated to 2000 chars).

    Returns:
        Normalized embedding vector, or None on failure.
    """
    if not cfg.gateway_url or not cfg.gateway_api_key:
        return None
    
    import time
    import requests
    import numpy as np

    url = f"{cfg.gateway_url.rstrip('/')}/embeddings"
    headers = {
        "Authorization": f"Bearer {cfg.gateway_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gemini-embed",
        "input": [text[:2000]],
    }

    max_retries = 3
    backoff_factor = 2.0  # Delays: 2s, 4s, 8s

    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
            values = resp.json()["data"][0]["embedding"]
            emb = np.array(values, dtype=np.float32)
            norm = np.linalg.norm(emb)
            normalized = emb / norm if norm > 0 else emb
            return normalized.tolist()
        except requests.exceptions.HTTPError as he:
            status_code = he.response.status_code if he.response is not None else 500
            # Fatal authentication/authorization or bad request: do not retry
            if status_code in (401, 403, 400, 404):
                _logger.error(f"[Merger] Fatal API error {status_code} fetching embedding. Aborting. Error: {he}")
                break
            
            # Transient server error or rate limiting: retry with backoff
            if attempt < max_retries - 1:
                sleep_time = backoff_factor ** (attempt + 1)
                _logger.warning(f"[Merger] Transient HTTP {status_code} fetching embedding (attempt {attempt+1}/{max_retries}). Retrying in {sleep_time}s... Error: {he}")
                time.sleep(sleep_time)
            else:
                _logger.error(f"[Merger] Failed to fetch embedding after {max_retries} attempts due to HTTP {status_code}: {he}")
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as te:
            # Network drop or connection timeout: retry with backoff
            if attempt < max_retries - 1:
                sleep_time = backoff_factor ** (attempt + 1)
                _logger.warning(f"[Merger] Network/Timeout error fetching embedding (attempt {attempt+1}/{max_retries}). Retrying in {sleep_time}s... Error: {te}")
                time.sleep(sleep_time)
            else:
                _logger.error(f"[Merger] Failed to fetch embedding after {max_retries} attempts due to Network/Timeout error: {te}")
        except Exception as e:
            # Any other unexpected exception
            _logger.error(f"[Merger] Unexpected error fetching embedding: {e}")
            break

    return None


def load_and_sync_bm25_cache(concept_files: list[Path]) -> dict:
    """Tải, kiểm chứng và cập nhật tăng dần bộ cache tokens của BM25.
    
    Sử dụng cơ chế kiểm chứng 2 cấp độ:
      - Cấp độ 1 (Level 1): Kiểm tra OS Metadata (mtime & size) - Cực nhanh, không đọc file.
      - Cấp độ 2 (Level 2): Đọc nhanh 2KB đầu file để kiểm tra frontmatter 'date_modified'.
    Tự động dọn dẹp các ghi chú đã bị xóa và đăng ký ghi chú mới/sửa đổi.
    
    Args:
        concept_files: Danh sách các Path đối tượng của các file Concept hiện tại.
        
    Returns:
        Dict mapping từ stem của ghi chú tới thông tin cache của nó.
    """
    import os
    import json
    import re
    
    cache_path = cfg.state_dir / "_bm25_cache.json"
    cache = {"version": "1.0", "concepts": {}}
    
    # 1. Tải cache hiện tại từ đĩa
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if loaded.get("version") == "1.0" and isinstance(loaded.get("concepts"), dict):
                    cache = loaded
        except Exception as e:
            _logger.warning(f"[BM25 Cache] Không thể tải tệp cache, khởi tạo lại: {e}")

    cached_concepts = cache["concepts"]
    active_stems = {p.stem for p in concept_files}
    cache_dirty = False

    # 2. Dọn dẹp các ghi chú đã bị xóa khỏi thư mục concepts
    stems_to_remove = [stem for stem in cached_concepts if stem not in active_stems]
    if stems_to_remove:
        for stem in stems_to_remove:
            del cached_concepts[stem]
        cache_dirty = True

    # Helper tách từ đồng bộ tuyệt đối với logic của semantic_merger
    def tokenize(text: str) -> list[str]:
        return [w for w in re.findall(r'\w+', text.lower()) if len(w) > 2]

    # 3. Đồng bộ hóa và cập nhật tăng dần bộ cache
    for p in concept_files:
        stem = p.stem
        try:
            stat = p.stat()
            current_mtime = stat.st_mtime
            current_size = stat.st_size
        except Exception:
            continue

        cached_entry = cached_concepts.get(stem)
        
        # --- LEVEL 1 CACHE HIT ---
        # Siêu dữ liệu OS (mtime & size) khớp tuyệt đối. Tệp tin không bị thay đổi.
        # Bỏ qua hoàn toàn việc mở và đọc file!
        if (
            cached_entry
            and cached_entry.get("mtime") == current_mtime
            and cached_entry.get("size") == current_size
        ):
            continue

        # --- LEVEL 2 CACHE HIT ---
        # OS Metadata thay đổi (ví dụ: bị touch), nhưng date_modified trong frontmatter không đổi.
        # Đọc nhanh tối đa 2KB đầu file để kiểm tra date_modified.
        current_date_modified = None
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(2048)
            match = re.search(r"^date_modified:\s*['\"]?([\d-]+)['\"]?", head, re.MULTILINE)
            if match:
                current_date_modified = match.group(1).strip()
        except Exception:
            pass

        if cached_entry and cached_entry.get("date_modified") == current_date_modified:
            # Cập nhật lại siêu dữ liệu OS mới vào cache để lần sau ăn trọn Level 1 hit
            cached_entry["mtime"] = current_mtime
            cached_entry["size"] = current_size
            cache_dirty = True
            continue

        # --- CACHE MISS (Tệp mới hoặc thực sự bị chỉnh sửa nội dung) ---
        # Đọc toàn bộ nội dung file và phân tích lại từ đầu.
        try:
            content = p.read_text(encoding="utf-8")
            # Loại bỏ stubs và low confidence ngay trong pha lập chỉ mục
            is_valid = not ("confidence: low" in content or "source_type: stub" in content)
            
            tokens = tokenize(content) if is_valid else []
            
            cached_concepts[stem] = {
                "date_modified": current_date_modified,
                "tokens": tokens,
                "is_valid": is_valid,
                "mtime": current_mtime,
                "size": current_size
            }
            cache_dirty = True
        except Exception as e:
            _logger.warning(f"[BM25 Cache] Không thể phân tích tệp tin '{p.name}': {e}")
            continue

    # 4. Lưu cache xuống đĩa một cách an toàn (Atomic Write)
    if cache_dirty:
        try:
            temp_path = cache_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            temp_path.replace(cache_path)
            _logger.info(f"[BM25 Cache] Đã cập nhật và lưu cache tăng dần xuống đĩa ({len(cached_concepts)} tệp tin).")
        except Exception as e:
            _logger.error(f"[BM25 Cache] Thất bại khi ghi file cache tĩnh: {e}")

    return cached_concepts


def find_semantic_overlap_fallback(new_text: str) -> tuple[str, float] | None:
    """Cơ chế Fallback sử dụng BM25 tìm ứng viên trùng lặp, sau đó tham vấn LLM kiểm chứng ngữ nghĩa.
    
    Giải pháp đã được tối ưu hóa toàn diện bằng bộ cache tăng dần 2 cấp độ và nạp JIT Top 3 candidates,
    giúp giải quyết dứt điểm nút thắt cổ chai I/O đồng bộ kéo dài 19 giây đối với >2.000 files.
    """
    try:
        from rank_bm25 import BM25Okapi
        import re
        import numpy as np
        
        # 1. Quét danh sách các file Concept hiện hữu
        concept_files = list(cfg.concepts_dir.glob("*.md"))
        if not concept_files:
            return None
            
        # Helper để phân tách văn bản truy vấn
        def tokenize(text: str) -> list[str]:
            return [w for w in re.findall(r'\w+', text.lower()) if len(w) > 2]
            
        # 2. Tải và đồng bộ hóa cache tăng dần (Incremental Tokenized Cache)
        cached_concepts = load_and_sync_bm25_cache(concept_files)
        
        # 3. Xây dựng corpus đã token hóa từ bộ cache (chỉ lấy các tệp hợp lệ)
        sources = []
        tokenized_corpus = []
        
        # Sắp xếp các khóa để đảm bảo thứ tự corpus luôn nhất quán (deterministic) khi test
        for stem in sorted(cached_concepts.keys()):
            entry = cached_concepts[stem]
            if entry.get("is_valid", False):
                sources.append(stem)
                tokenized_corpus.append(entry["tokens"])
                
        if not tokenized_corpus:
            _logger.warning("[Merger Fallback] Không tìm thấy Concept hợp lệ nào để lập chỉ mục BM25.")
            return None
            
        # 4. Khởi tạo mô hình BM25Okapi và tính điểm cho ghi chú mới
        bm25 = BM25Okapi(tokenized_corpus)
        tokenized_query = tokenize(new_text)
        scores = bm25.get_scores(tokenized_query)
        
        # 5. Lọc ra tối đa Top 3 ứng viên xuất sắc nhất có điểm số > 0
        top_indices = np.argsort(scores)[::-1][:3]
        candidates = []
        for idx in top_indices:
            if scores[idx] > 0:
                stem = sources[idx]
                concept_path = cfg.concepts_dir / f"{stem}.md"
                if concept_path.exists():
                    try:
                        # Nạp nội dung đầy đủ một cách JIT (Just-In-Time) tại đây
                        content = concept_path.read_text(encoding="utf-8")
                        candidates.append((stem, content))
                    except Exception as e:
                        _logger.warning(f"[Merger Fallback] Thất bại khi nạp JIT nội dung ứng viên '{stem}': {e}")
                        continue
                        
        if not candidates:
            return None
            
        # 6. Soạn thảo prompt và tham vấn LLM Trọng tài tối cao để kiểm chứng ngữ nghĩa học thuật
        candidates_str = "\n\n".join([f"Candidate [{stem}]:\n```markdown\n{content[:1500]}...\n```" for stem, content in candidates])
        
        validate_prompt = (
            f"Bạn là Trọng tài Ngữ nghĩa tối cao của hệ thống Zettelkasten.\n"
            f"Dịch vụ Vector Embeddings đang gặp sự cố mạng tạm thời. Hãy giúp tôi so khớp ngữ nghĩa thủ công.\n\n"
            f"GHI CHÚ MỚI CHUẨN BỊ LƯU:\n"
            f"```markdown\n{new_text[:2000]}\n```\n\n"
            f"DANH SÁCH 3 ỨNG VIÊN CÓ THỂ TRÙNG LẶP (Được lọc sơ bộ bằng BM25):\n"
            f"{candidates_str}\n\n"
            f"YÊU CẦU: Hãy phân tích xem ghi chú mới có trùng khớp ngữ nghĩa học thuật cốt lõi (Semantic Equivalence) với bất kỳ ứng viên nào trong danh sách trên hay không (độ tương đồng ngữ nghĩa >= 88%, bàn về cùng một khái niệm, cùng bản chất tri thức).\n\n"
            f"- Nếu CÓ trùng khớp, hãy trả về CHÍNH XÁC tên ứng viên đó trong ngoặc vuông, ví dụ: [ngon_ngu_chung_ubiquitous_language_giua_nguoi_va_ai].\n"
            f"- Nếu KHÔNG trùng khớp với bất kỳ ứng viên nào, trả về: NONE.\n\n"
            f"Chỉ trả lời duy nhất định dạng [tên_ứng_viên] hoặc NONE, không giải thích thêm."
        )
        
        decision = call_llm(validate_prompt, task="synthesis")
        if decision:
            decision = decision.strip()
            match = re.search(r'\[(.*?)\]', decision)
            if match:
                matched_stem = match.group(1).strip()
                if matched_stem in sources:
                    _logger.info(f"[Merger Fallback] BM25+LLM matched concept overlap with '{matched_stem}'")
                    return matched_stem, 0.90  # Điểm giả lập > 0.88 để kích hoạt luồng hợp nhất (merge flow)
                    
    except Exception as e:
        _logger.error(f"[Merger Fallback] Gặp lỗi nghiêm trọng trong BM25 fallback: {e}")
        
    return None


def find_semantic_overlap(new_text: str) -> tuple[str, float] | None:
    """Find if a concept has extremely high semantic similarity with an existing one.

    Loads the pre-built embedding index and computes cosine similarity
    via fast dot product on L2-normalized vectors.

    Args:
        new_text: Full text of the new concept note.

    Returns:
        Tuple of (existing_stem, similarity_score) if score >= 0.88, else None.
    """
    import numpy as np
    index_path = cfg.state_dir / "_embedding_index.npz"
    bak_path = index_path.with_suffix(".npz.bak")

    loaded_path = None
    if index_path.exists():
        loaded_path = index_path
    elif bak_path.exists():
        loaded_path = bak_path

    if not loaded_path:
        return None

    try:
        data = np.load(loaded_path, allow_pickle=True)
        if "embeddings" not in data or "sources" not in data:
            return None

        embeddings = data["embeddings"]
        sources = data["sources"].tolist()

        # Fetch query embedding
        query_emb = get_embedding_via_gateway(new_text)
        if query_emb is None:
            _logger.info("[Merger] Embedding is unavailable. Activating BM25 + LLM fallback semantic overlap matching...")
            return find_semantic_overlap_fallback(new_text)

        # Fast dot product on pre-normalized vectors
        similarities = np.dot(embeddings, np.array(query_emb, dtype=np.float32))

        # Find best match
        best_idx = int(np.argmax(similarities))
        best_score = float(similarities[best_idx])

        if best_score >= 0.88:
            return sources[best_idx], best_score
    except Exception as e:
        _logger.warning(f"Failed to scan semantic overlap: {e}")

    return None


def arbitrate_and_merge(new_content: str, existing_stem: str) -> Path | None:
    """Arbitrate if we should merge or separate two highly similar concepts.

    Implements 3-Tier Merge Control:
      - Tier 1: Hook Count Gate (≥4 hooks → force SEPARATE)
      - Tier 2: Dynamic Size Limit (>7700 bytes → force SEPARATE)
      - Tier 3: LLM Arbitrator (MERGE / SEPARATE / SUBSUME)

    If MERGE: Synthesizes merged note, overwrites existing file.
    If SEPARATE: Returns None (caller handles cross-linking).
    If SUBSUME: Returns SUBSUME_SENTINEL.

    Args:
        new_content: Full text of the new concept note.
        existing_stem: Filename stem of the existing similar concept.

    Returns:
        Path to merged file, SUBSUME_SENTINEL, or None.
    """
    existing_path = cfg.concepts_dir / f"{existing_stem}.md"
    if not existing_path.exists():
        return None

    try:
        existing_content = existing_path.read_text(encoding="utf-8")

        # Don't arbitrate if the existing file is an empty stub (hydration will handle this directly)
        existing_fm = parse_frontmatter(existing_content)
        if existing_fm.get("confidence") == "low" or existing_fm.get("source_type") == "stub":
            return None

        # Tier 1: Check for SUBSUME First (Semantic Absorb)
        # Prioritizing SUBSUME prevents creating duplicate separate notes for 100% semantic overlap.
        # This occurs regardless of the existing note's physical size since subsuming does not expand it.
        subsume_prompt = (
            f"Bạn là Trọng tài Zettelkasten tối cao. Hãy đánh giá xem ghi chú hiện tại có bao hàm hoàn toàn (SUBSUME) ghi chú mới hay không.\n\n"
            f"GHI CHÚ HIỆN TẠI:\n"
            f"```markdown\n{existing_content}\n```\n\n"
            f"GHI CHÚ MỚI:\n"
            f"```markdown\n{new_content}\n```\n\n"
            f"QUY TẮC ĐÁNH GIÁ:\n"
            f"- Trả lời 'SUBSUME' nếu ghi chú hiện tại đã bao phủ >= 90% nội dung cốt lõi của ghi chú mới. Ghi chú mới không bổ sung thêm trích dẫn (quote) mới đáng kể từ trang khác/chương khác, và không đóng góp luận điểm học thuật mới đáng kể nào.\n"
            f"- Trả lời 'NOT_SUBSUME' nếu ghi chú mới thực sự bổ sung thêm trích dẫn mới hữu ích (ví dụ: quote mới từ trang khác, nguồn khác), hoặc giới thiệu khía cạnh tri thức mới bổ trợ mà ghi chú cũ chưa phân tích sâu.\n\n"
            f"Trả lời CHÍNH XÁC duy nhất một từ: 'SUBSUME' hoặc 'NOT_SUBSUME'."
        )

        subsume_decision = call_llm(subsume_prompt, task="synthesis", allowed_shorts=("SUBSUME", "NOT_SUBSUME"))
        if subsume_decision and "SUBSUME" in subsume_decision.upper() and "NOT_SUBSUME" not in subsume_decision.upper():
            _logger.info(f"[Merger] Priority SUBSUME Check: existing '{existing_stem}.md' fully covers new content. Absorbing without creating files.")
            return SUBSUME_SENTINEL

        # Tier 2: Physical Size Constraints
        # Since we confirmed the new concept adds novel tri thức (NOT_SUBSUME), 
        # we must now enforce physical boundaries to prevent the creation of unreadable "God Notes".
        
        # 1. Hook Count Gate (Soft threshold for quote consolidation)
        hook_count = len(re.findall(r'^> "', existing_content, re.MULTILINE))
        is_prune_mode = hook_count >= 4
        if is_prune_mode:
            _logger.info(f"[Merger] Hook Count Gate: '{existing_stem}' has {hook_count} evidence hooks. Activating Merge-with-Pruning mode to consolidate quotes.")

        # 2. Dynamic Size Limit (P95 × 1.3 ~7.7KB derived from vault-wide statistics)
        file_size = existing_path.stat().st_size
        if is_prune_mode:
            # In prune mode, calculate core_size by stripping all blockquotes (which inflate size)
            content_without_quotes = re.sub(r'^>.*$', '', existing_content, flags=re.MULTILINE)
            core_size = len(content_without_quotes.encode('utf-8'))
            
            # Enforce 6,000 bytes core size limit and 10,000 bytes absolute file size limit
            if core_size > 6000 or file_size > 10000:
                _logger.info(
                    f"[Merger] Dynamic Size Limit (Prune Mode): '{existing_stem}' core_size={core_size} bytes (limit 6,000), "
                    f"file_size={file_size} bytes (limit 10,000). Exceeds limit, forcing KEEP SEPARATE."
                )
                return None
            else:
                _logger.info(
                    f"[Merger] Dynamic Size Limit (Prune Mode) PASSED: '{existing_stem}' core_size={core_size} bytes, "
                    f"file_size={file_size} bytes. Allowed to arbitrate."
                )
        else:
            if file_size > 7700:
                _logger.info(f"[Merger] Dynamic Size Limit: '{existing_stem}' ({file_size} bytes) exceeds limit (7,700 bytes). Force KEEP SEPARATE to preserve readability.")
                return None

        # Tier 3: LLM Arbitrator (Decision between MERGE and SEPARATE)
        # Consult the LLM to merge or keep separate.
        _logger.info(f"[Merger] Overlap detected. Consulting Arbitrator to MERGE or SEPARATE with '{existing_stem}'...")

        prune_warning = ""
        if is_prune_mode:
            prune_warning = (
                f"LƯU Ý ĐẶC BIỆT: Ghi chú hiện tại đã tích lũy đủ {hook_count} Evidence Hooks (đạt ngưỡng trần).\n"
                f"Nếu bạn chọn 'MERGE', hệ thống sẽ tự động kích hoạt chế độ 'Tỉa cành củng cố' (Consolidated Pruning) để gộp và chọn lọc các trích dẫn tương đồng, chỉ giữ lại 3-4 trích dẫn tinh túy nhất.\n"
                f"Do đó, hãy tự tin chọn 'MERGE' nếu đây thực sự là cùng một khái niệm cốt lõi!\n\n"
            )

        arbitrate_prompt = (
            f"Bạn là Nhà biên soạn Zettelkasten tối cao. Hai ghi chú tri thức chất lượng cao này có độ tương đồng ngữ nghĩa rất cao và bạn đã xác định ghi chú mới CÓ tri thức bổ trợ (không bị subsume).\n\n"
            f"GHI CHÚ HIỆN CÓ ĐÃ LƯU:\n"
            f"```markdown\n{existing_content}\n```\n\n"
            f"GHI CHÚ MỚI CHUẨN BỊ LƯU:\n"
            f"```markdown\n{new_content}\n```\n\n"
            f"{prune_warning}"
            f"YÊU CẦU ĐÁNH GIÁ — Hãy phân biệt chính xác giữa hai quyết định:\n\n"
            f"'MERGE' — Cùng một khái niệm học thuật cốt lõi. Ghi chú mới BỔ SUNG trích dẫn mới, góc nhìn mới tuyệt vời hỗ trợ cho ý tưởng cũ. Việc gộp chung giúp ghi chú Evergreen tích lũy giá trị cao hơn.\n\n"
            f"'SEPARATE' — Dù chia sẻ từ khóa chung, hai ghi chú bàn về hai khía cạnh, luận điểm hoặc bối cảnh hoàn toàn độc lập. Tách biệt giúp Obsidian Graph sạch hơn và tạo liên kết chéo.\n\n"
            f"Trả lời CHÍNH XÁC duy nhất một từ: 'MERGE' hoặc 'SEPARATE'."
        )

        decision = call_llm(arbitrate_prompt, task="synthesis", allowed_shorts=("MERGE", "SEPARATE"))
        if not decision:
            decision = "SEPARATE"

        decision = decision.strip().upper()

        if "MERGE" in decision:
            _logger.info(f"[Merger] Arbitrator DECIDED to MERGE into '{existing_stem}.md'. Synthesizing...")

            prune_instruction = ""
            if is_prune_mode:
                prune_instruction = (
                    f"CẢNH BÁO HỢP NHẤT: Ghi chú 1 đã tích lũy {hook_count} Evidence Hooks. Bạn BẮT BUỘC phải thực hiện 'Tỉa cành củng cố' (Consolidated Pruning) một cách nghiêm ngặt:\n"
                    f"- So sánh và loại bỏ các trích dẫn tương đồng hoặc bị lặp ý giữa hai ghi chú.\n"
                    f"- Nếu có nhiều trích dẫn cùng chung một khía cạnh hoặc cùng từ một chương/trang, hãy kết hợp hoặc chỉ giữ lại trích dẫn sắc bén nhất.\n"
                    f"- Đảm bảo tổng số lượng Evidence Hooks sau khi gộp và tỉa cành tuyệt đối KHÔNG vượt quá 4 (ưu tiên giữ 3 trích dẫn tinh túy nhất đại diện cho các nguồn/trang khác nhau).\n"
                    f"- Ghi rõ Citation Line học thuật có kèm wiki-link đầy đủ cho từng trích dẫn được giữ lại.\n"
                )

            # 2. Synthesize Merge Prompt
            merge_prompt = (
                f"Bạn là Chuyên gia biên tập Zettelkasten v8.9.9. Hãy hợp nhất hai ghi chú tri thức này thành một ghi chú học thuật duy nhất có giá trị tích lũy cao.\n\n"
                f"GHI CHÚ 1:\n"
                f"```markdown\n{existing_content}\n```\n\n"
                f"GHI CHÚ 2:\n"
                f"```markdown\n{new_content}\n```\n\n"
                f"{prune_instruction}"
                f"QUY TẮC HỢP NHẤT BẮT BUỘC:\n"
                f"1. FRONTMATTER YAML: Phải gộp tất cả các tags, sources (thành mảng), related links. Đặt trạng thái `status: evergreen`, `confidence: high`.\n"
                f"2. EVIDENCE HOOKS (Consolidation): Hãy kiểm tra và xếp chồng các Evidence Hooks lên đầu note (standalone blockquotes độc lập ở đầu tệp tin, ghi rõ Citation Line học thuật có wiki-link). TUYÊN BỐ QUAN TRỌNG: Nếu hai trích dẫn có ý nghĩa tương đương hoặc lặp ý, hãy cô đọng lại và chỉ giữ lại tối đa 3 trích dẫn tiếng Việt sắc bén nhất đại diện cho các nguồn/trang khác nhau. Tránh xếp chồng quá nhiều blockquotes gây loãng giá trị ghi chú.\n"
                f"3. CORE IDEA: Viết lại phần Core Idea phân tích tổng hợp chiều sâu, chỉ ra điểm giao thoa tri thức, phản biện hoặc bổ trợ giữa hai góc nhìn. Tuyệt đối không lặp lại trích dẫn.\n"
                f"4. GROUND TRUTH: Gom tất cả các đoạn văn tiếng Anh nguyên bản từ phần Ground Truth của cả hai ghi chú cũ.\n"
                f"5. REFERENCES: Gom tất cả các liên kết nguồn thô.\n\n"
                f"Trả về ĐÚNG tệp tin Markdown hoàn chỉnh bắt đầu từ '---' đến hết."
            )

            merged_body = call_llm(merge_prompt, task="synthesis")
            if merged_body and len(merged_body) > 200:
                # Robustly extract from the first YAML marker
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

        # 3. SEPARATE strategy (Cross-Linking)
        _logger.info("[Merger] Arbitrator DECIDED to KEEP SEPARATE.")
        return None
    except Exception as e:
        _logger.warning(f"[Merger] Exception during arbitration: {e}")
        return None


def execute_cross_linking(path_a: Path, path_b: Path) -> None:
    """Create bidirectional links between A and B in their related YAML array and References.

    Args:
        path_a: First concept note path.
        path_b: Second concept note path.
    """
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

            # 1. Update related list
            if target_stem not in related:
                related.append(target_stem)
                fm["related"] = related

            # 2. Update References in body
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
    """Append a SUBSUME event to the weekly-reviewable journal.

    The journal file (.subsume_journal.jsonl) lives in the vault root and is
    read by sleep.py during weekly consolidation to produce a human-readable
    summary for review.

    Args:
        new_title: Title of the new concept that was subsumed.
        existing_stem: Stem of the existing concept that absorbed it.
        score: Cosine similarity score.
        image_path: Source image that triggered the concept.
    """
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
