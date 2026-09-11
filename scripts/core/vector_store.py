"""VvC Second Brain — Vector Store & Embedding Index Manager.

Centralized Deep Module managing the _embedding_index.npz lifecycle:
- Safe file handle context management (with np.load(...) as data) preventing Windows PermissionErrors
- Concurrency protection via CrossProcessFileLock (multi-process and multi-thread safe)
- Atomic disk updates via tmp_file + os.replace with automatic .npz.bak backup
- Cosine similarity search via fast dot product on L2-normalized vectors
- Hot insertion and full batch synchronization
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
from pathlib import Path
from typing import TypedDict

import numpy as np

from core.config import cfg
from core.file_lock import CrossProcessFileLock
from core.llm.embedding_client import get_embedding

_logger = logging.getLogger("vvc.vector_store")


class IndexDict(TypedDict):
    embeddings: np.ndarray
    texts: list[str]
    sources: list[str]


class VectorStore:
    """Quản lý vòng đời tệp tin chỉ mục vector _embedding_index.npz."""

    _instances: dict[str, VectorStore] = {}

    def __init__(self, index_path: Path | str | None = None):
        if index_path is None:
            self.index_path = (cfg.state_dir / "_embedding_index.npz").resolve()
        else:
            self.index_path = Path(index_path).resolve()

        self.bak_path = self.index_path.with_suffix(".npz.bak")
        self.lock_path = self.index_path.with_suffix(".npz.lock")

        self.embeddings: np.ndarray = np.empty((0, 0), dtype=np.float32)
        self.texts: list[str] = []
        self.sources: list[str] = []
        self._index_map: dict[str, int] = {}
        self._mtime: float = 0.0
        self._loaded: bool = False

    @classmethod
    def get_instance(cls, index_path: Path | str | None = None) -> VectorStore:
        """Lấy singleton instance của VectorStore cho đường dẫn index_path.
        
        Tự động nạp lại dữ liệu nếu tệp tin trên đĩa bị thay đổi bởi tiến trình khác.
        """
        path = (Path(index_path).resolve() if index_path is not None 
                else (cfg.state_dir / "_embedding_index.npz").resolve())
        key = str(path)

        if key not in cls._instances:
            store = cls(path)
            store.load()
            cls._instances[key] = store
            return store

        store = cls._instances[key]
        current_mtime = 0.0
        if path.exists():
            try:
                current_mtime = path.stat().st_mtime
            except OSError:
                pass

        # Nếu tệp trên đĩa mới hơn bản ghi nhớ trong RAM, nạp lại
        if current_mtime > store._mtime:
            store.load()

        return store

    def __len__(self) -> int:
        return len(self.sources)

    @staticmethod
    def _read_index_data(path: Path) -> tuple[list[np.ndarray], list[str], list[str]]:
        """Read index data from a .npz file safely.
        
        Supports both modern schema ('embeddings', 'sources', optional 'texts')
        and legacy schema ('vectors', 'stems').
        """
        try:
            with np.load(path, allow_pickle=True) as data:
                if "embeddings" in data and "sources" in data:
                    raw_embs = data["embeddings"]
                    raw_sources = data["sources"].tolist()
                    raw_texts = data["texts"].tolist() if "texts" in data else [""] * len(raw_sources)
                elif "vectors" in data and "stems" in data:
                    _logger.info(f"Migrating legacy embedding index format from {path.name}...")
                    raw_embs = data["vectors"]
                    raw_sources = data["stems"].tolist()
                    raw_texts = []
                    for stem in raw_sources:
                        fpath = cfg.concepts_dir / f"{stem}.md"
                        if fpath.exists():
                            try:
                                raw_texts.append(fpath.read_text(encoding="utf-8")[:2000])
                            except Exception:
                                raw_texts.append("")
                        else:
                            raw_texts.append("")
                else:
                    _logger.warning(f"Unrecognized index structure in {path}")
                    return [], [], []

                sources = [str(s) for s in raw_sources]
                texts = [str(t) for t in raw_texts]

                if raw_embs.size > 0:
                    embs_arr = np.array(raw_embs, dtype=np.float32)
                    if embs_arr.ndim == 1:
                        embs_arr = embs_arr.reshape(1, -1)
                    norms = np.linalg.norm(embs_arr, axis=1, keepdims=True)
                    norms = np.where(norms == 0, 1.0, norms)
                    embs_arr = embs_arr / norms
                    embeddings = list(embs_arr)
                else:
                    embeddings = []

                return embeddings, texts, sources
        except Exception as e:
            _logger.warning(f"Failed to read index data from {path}: {e}")
            return [], [], []

    def _reset_empty(self) -> None:
        self.embeddings = np.empty((0, 0), dtype=np.float32)
        self.texts = []
        self.sources = []
        self._index_map = {}
        self._mtime = 0.0
        self._loaded = True

    def load(self) -> VectorStore:
        """Nạp chỉ mục vector từ tệp .npz hoặc .npz.bak.
        
        Luôn sử dụng context manager `with np.load(...)` để giải phóng file descriptor
        ngay sau khi đọc xong, tránh rò rỉ tài nguyên trên Windows.
        """
        loaded_path = None
        if self.index_path.exists():
            loaded_path = self.index_path
        elif self.bak_path.exists():
            loaded_path = self.bak_path
            _logger.info(f"Main index not found, falling back to backup: {self.bak_path}")

        if not loaded_path:
            self._reset_empty()
            return self

        embs_list, texts, sources = self._read_index_data(loaded_path)
        if not sources and loaded_path == self.index_path and self.bak_path.exists():
            _logger.info("Retrying with backup index...")
            embs_list, texts, sources = self._read_index_data(self.bak_path)
            loaded_path = self.bak_path

        if sources and embs_list:
            self.sources = sources
            self.texts = texts
            self.embeddings = np.array(embs_list, dtype=np.float32)
            self._index_map = {src: i for i, src in enumerate(self.sources)}
            try:
                self._mtime = loaded_path.stat().st_mtime
            except OSError:
                self._mtime = time.time()
            self._loaded = True
            _logger.info(f"Vector store loaded successfully: {len(self.sources)} entries from {loaded_path.name}")
        else:
            self._reset_empty()

        return self

    def to_dict(self) -> IndexDict:
        """Xuất dữ liệu index theo format TypedDict dùng bởi rag_search."""
        return {
            "embeddings": self.embeddings,
            "texts": self.texts,
            "sources": self.sources,
        }

    def search(
        self,
        query_vec: np.ndarray | list[float],
        top_k: int = 10,
        threshold: float = 0.0,
    ) -> list[tuple[str, float]]:
        """Tìm kiếm cosine similarity trả về danh sách (stem, score) sắp xếp giảm dần.
        
        Args:
            query_vec: Vector truy vấn (1D).
            top_k: Số lượng kết quả tối đa cần lấy.
            threshold: Ngưỡng điểm similarity tối thiểu (từ 0.0 đến 1.0).
            
        Returns:
            Danh sách các cặp (stem, similarity_score).
        """
        if self.embeddings.size == 0 or len(self.sources) == 0 or query_vec is None:
            return []

        q = np.array(query_vec, dtype=np.float32)
        if q.ndim > 1:
            q = q.flatten()
        norm = np.linalg.norm(q)
        if norm > 0:
            q = q / norm

        # Tính dot product cực nhanh trên L2-normalized vectors
        try:
            similarities = np.dot(self.embeddings, q)
        except ValueError as e:
            _logger.error(f"Dimension mismatch in vector search: {e}")
            return []

        # Lọc theo ngưỡng và sắp xếp
        results: list[tuple[str, float]] = []
        if top_k == 1:
            best_idx = int(np.argmax(similarities))
            best_score = float(similarities[best_idx])
            if best_score >= threshold:
                return [(self.sources[best_idx], best_score)]
            return []

        sorted_indices = np.argsort(-similarities)
        for idx in sorted_indices:
            score = float(similarities[idx])
            if score < threshold:
                break
            results.append((self.sources[idx], score))
            if len(results) >= top_k:
                break

        return results

    def search_indices(
        self,
        query_vec: np.ndarray | list[float],
        top_k: int = 10,
        threshold: float = 0.0,
    ) -> list[tuple[int, float]]:
        """Tìm kiếm cosine similarity trả về danh sách (index, score) cho thuật toán RRF."""
        if self.embeddings.size == 0 or len(self.sources) == 0 or query_vec is None:
            return []

        q = np.array(query_vec, dtype=np.float32)
        if q.ndim > 1:
            q = q.flatten()
        norm = np.linalg.norm(q)
        if norm > 0:
            q = q / norm

        try:
            similarities = np.dot(self.embeddings, q)
        except ValueError as e:
            _logger.error(f"Dimension mismatch in vector search: {e}")
            return []

        indexed = sorted(enumerate(similarities), key=lambda x: x[1], reverse=True)
        return [(i, float(s)) for i, s in indexed[:top_k] if s >= threshold]

    def hot_insert(
        self,
        stem: str,
        content: str,
        embedding: np.ndarray | list[float] | None = None,
    ) -> bool:
        """Hot-insert hoặc update vector embedding của một ghi chú vào _embedding_index.npz.
        
        Đảm bảo:
            - Lấy vector embedding trước khi chiếm khóa tệp (tránh nghẽn IO do HTTP latency).
            - Đồng bộ hóa đa tiến trình an toàn bằng CrossProcessFileLock.
            - Ghi đĩa nguyên tử (Atomic Write) qua tệp tạm + os.replace.
            - Đóng tệp tức thời bằng context manager `with np.load(...)`.
            - Tự động đồng bộ hóa tệp dự phòng .npz.bak.
        """
        stem = stem.replace(".md", "").strip()
        if not stem:
            return False

        # 1. Fetch embedding trước khi lấy khóa
        if embedding is None:
            emb_vec = get_embedding(content)
            if emb_vec is None:
                _logger.warning(f"Could not fetch embedding for hot-insert of '{stem}'")
                return False
        else:
            emb_vec = np.array(embedding, dtype=np.float32)
            if emb_vec.ndim > 1:
                emb_vec = emb_vec.flatten()
            norm = np.linalg.norm(emb_vec)
            if norm > 0:
                emb_vec = emb_vec / norm

        content_hash = f"hash:{hashlib.md5(content.encode('utf-8')).hexdigest()}"

        # 2. Chiếm khóa và thực hiện nạp/ghi nguyên tử
        try:
            with CrossProcessFileLock(self.lock_path):
                existing_embeddings: list[np.ndarray] = []
                existing_texts: list[str] = []
                existing_sources: list[str] = []

                loaded_path = None
                if self.index_path.exists():
                    loaded_path = self.index_path
                elif self.bak_path.exists():
                    loaded_path = self.bak_path

                if loaded_path:
                    existing_embeddings, existing_texts, existing_sources = self._read_index_data(loaded_path)

                # Cập nhật hoặc chèn mới
                if stem in existing_sources:
                    idx = existing_sources.index(stem)
                    existing_embeddings[idx] = emb_vec
                    existing_texts[idx] = content_hash
                    _logger.info(f"Updated existing entry in index for '{stem}'")
                else:
                    existing_embeddings.append(emb_vec)
                    existing_texts.append(content_hash)
                    existing_sources.append(stem)
                    _logger.info(f"Appended new entry to index for '{stem}'")

                # Ghi đĩa nguyên tử
                tmp_path = self.index_path.parent / f"{self.index_path.stem}_tmp.npz"
                try:
                    save_embeddings = np.array(existing_embeddings, dtype=np.float32)
                    np.savez_compressed(
                        tmp_path,
                        embeddings=save_embeddings,
                        texts=np.array(existing_texts, dtype=object),
                        sources=np.array(existing_sources, dtype=object),
                    )
                    os.replace(tmp_path, self.index_path)
                    _logger.info(f"Hot-insert successful: Index size is now {len(existing_sources)}")
                except Exception as save_err:
                    _logger.error(f"Failed to save hot-inserted embedding index: {save_err}")
                    return False
                finally:
                    if tmp_path.exists():
                        try:
                            tmp_path.unlink()
                        except OSError:
                            pass

                # Đồng bộ backup nguyên tử
                bak_tmp = self.bak_path.with_suffix(".npz.bak.tmp")
                try:
                    shutil.copy2(self.index_path, bak_tmp)
                    os.replace(bak_tmp, self.bak_path)
                except Exception as bak_err:
                    _logger.warning(f"Failed to sync backup index during hot-insert: {bak_err}")
                finally:
                    if bak_tmp.exists():
                        try:
                            bak_tmp.unlink()
                        except OSError:
                            pass

                # Cập nhật state in-memory
                self.sources = existing_sources
                self.texts = existing_texts
                self.embeddings = np.array(existing_embeddings, dtype=np.float32)
                self._index_map = {src: i for i, src in enumerate(self.sources)}
                try:
                    self._mtime = self.index_path.stat().st_mtime
                except OSError:
                    self._mtime = time.time()

                return True

        except TimeoutError as te:
            _logger.error(f"Lock timeout during hot-insert for '{stem}': {te}")
            return False
        except Exception as e:
            _logger.error(f"Unexpected error during hot-insert for '{stem}': {e}")
            return False

    def sync_all(self, concepts: list[dict] | None = None) -> dict[str, int]:
        """Đồng bộ hóa toàn bộ danh mục concept notes vào tệp chỉ mục vector."""
        from core.vault import scan_all_concepts

        _logger.info("Starting full embedding synchronization...")
        if not cfg.gateway_url or not cfg.gateway_api_key:
            _logger.error("AI Gateway config not found. Cannot sync embeddings.")
            return {"new": 0, "updated": 0, "deleted": 0, "total": 0}

        try:
            with CrossProcessFileLock(self.lock_path):
                self.load()
                existing_sources = list(self.sources)
                existing_texts = list(self.texts)
                existing_embeddings = list(self.embeddings)
                index_map = {src: i for i, src in enumerate(existing_sources)}

                new_sources: list[str] = []
                new_texts: list[str] = []
                new_embeddings: list[np.ndarray] = []
                valid_sources: set[str] = set()

                updated_count = 0
                new_count = 0

                if concepts is None:
                    concepts = scan_all_concepts()

                circuit_breaker_tripped = False
                consecutive_errors = 0
                max_consecutive_errors = 5

                for fm in concepts:
                    raw_path = fm.get("_path") or fm.get("path")
                    if raw_path is None:
                        continue
                    fpath = Path(raw_path)
                    stem = str(fm.get("_stem") or fm.get("stem") or fpath.stem)
                    valid_sources.add(stem)

                    try:
                        full_content = fpath.read_text(encoding="utf-8")
                        current_hash = f"hash:{hashlib.md5(full_content.encode('utf-8')).hexdigest()}"
                        current_text_for_embedding = full_content[:2000]
                    except Exception:
                        continue

                    needs_embedding = False
                    if stem in index_map:
                        idx = index_map[stem]
                        old_text = existing_texts[idx]
                        if isinstance(old_text, str) and old_text.startswith("hash:"):
                            if current_hash != old_text:
                                if not circuit_breaker_tripped:
                                    needs_embedding = True
                                    updated_count += 1
                        else:
                            pass
                    else:
                        if not circuit_breaker_tripped:
                            needs_embedding = True
                            new_count += 1
                        else:
                            continue

                    if needs_embedding:
                        _logger.info(f"Embedding: {stem}")
                        emb = get_embedding(current_text_for_embedding)
                        if emb is not None:
                            new_sources.append(stem)
                            new_texts.append(current_hash)
                            new_embeddings.append(emb)
                            consecutive_errors = 0
                        else:
                            consecutive_errors += 1
                            backoff_delay = min(3.0 * (2 ** (consecutive_errors - 1)), 30.0)
                            _logger.warning(
                                f"Embedding error {consecutive_errors}/{max_consecutive_errors}. "
                                f"Backing off {backoff_delay:.0f}s..."
                            )
                            time.sleep(backoff_delay)
                            if consecutive_errors >= max_consecutive_errors:
                                _logger.error(
                                    f"Consecutive embedding errors reached {max_consecutive_errors}. "
                                    "Tripping circuit breaker."
                                )
                                circuit_breaker_tripped = True

                            if stem in index_map:
                                idx = index_map[stem]
                                new_sources.append(stem)
                                new_texts.append(existing_texts[idx])
                                new_embeddings.append(existing_embeddings[idx])

                        time.sleep(0.2)
                    else:
                        idx = index_map[stem]
                        new_sources.append(stem)
                        old_text = existing_texts[idx]
                        if isinstance(old_text, str) and old_text.startswith("hash:"):
                            new_texts.append(old_text)
                        else:
                            new_texts.append(current_hash)
                        new_embeddings.append(existing_embeddings[idx])

                deleted_count = len(existing_sources) - len(valid_sources)
                if updated_count == 0 and new_count == 0 and deleted_count == 0:
                    _logger.info("Embedding index is already up to date.")
                    return {"new": 0, "updated": 0, "deleted": 0, "total": len(new_sources)}

                _logger.info(f"Processed {new_count} new, {updated_count} updated, {deleted_count} deleted.")
                if not new_embeddings:
                    _logger.warning("No valid embeddings to save.")
                    return {"new": 0, "updated": 0, "deleted": deleted_count, "total": 0}

                # Lưu đĩa nguyên tử
                tmp_path = self.index_path.parent / f"{self.index_path.stem}_tmp.npz"
                try:
                    np.savez_compressed(
                        tmp_path,
                        embeddings=np.array(new_embeddings, dtype=np.float32),
                        texts=np.array(new_texts, dtype=object),
                        sources=np.array(new_sources, dtype=object),
                    )
                    os.replace(tmp_path, self.index_path)
                    _logger.info(f"Embedding index saved successfully: {len(new_sources)} concepts.")

                    bak_tmp = self.bak_path.with_suffix(".npz.bak.tmp")
                    try:
                        shutil.copy2(self.index_path, bak_tmp)
                        os.replace(bak_tmp, self.bak_path)
                        _logger.info("Embedding index backup created successfully.")
                    except Exception as bak_err:
                        _logger.warning(f"Failed to create embedding index backup: {bak_err}")
                    finally:
                        if bak_tmp.exists():
                            try:
                                bak_tmp.unlink()
                            except OSError:
                                pass

                    self.sources = new_sources
                    self.texts = new_texts
                    self.embeddings = np.array(new_embeddings, dtype=np.float32)
                    self._index_map = {src: i for i, src in enumerate(self.sources)}
                    self._mtime = self.index_path.stat().st_mtime
                    return {"new": new_count, "updated": updated_count, "deleted": deleted_count, "total": len(new_sources)}

                except Exception as save_err:
                    _logger.error(f"Failed to save embedding index: {save_err}")
                    return {"new": new_count, "updated": updated_count, "deleted": deleted_count, "total": 0}
                finally:
                    if tmp_path.exists():
                        try:
                            tmp_path.unlink()
                        except OSError:
                            pass

        except Exception as e:
            _logger.error(f"Failed in sync_all: {e}")
            return {"new": 0, "updated": 0, "deleted": 0, "total": 0}
