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
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import TypedDict

import numpy as np

from core.config import cfg
from core.file_lock import CrossProcessFileLock
from core.llm.embedding_client import get_embedding
from core.vector_io import atomic_save_index, merge_pending_updates, read_index_file

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
        self._dirty: bool = False
        self._batch_depth: int = 0
        self._pending_updates: dict[str, tuple[str, np.ndarray]] = {}

    @classmethod
    def get_instance(cls, index_path: Path | str | None = None) -> VectorStore:
        """Lấy singleton instance của VectorStore cho đường dẫn index_path."""
        path = (Path(index_path).resolve() if index_path is not None 
                else (cfg.state_dir / "_embedding_index.npz").resolve())
        key = str(path)

        if key not in cls._instances:
            store = cls(path)
            store.load()
            cls._instances[key] = store
            return store

        store = cls._instances[key]
        if store._batch_depth > 0:
            return store

        current_mtime = 0.0
        if path.exists():
            try:
                current_mtime = path.stat().st_mtime
            except OSError:
                pass

        if current_mtime > store._mtime:
            store.load()

        return store

    def __len__(self) -> int:
        return len(self.sources)

    @staticmethod
    def _read_index_data(path: Path) -> tuple[list[np.ndarray], list[str], list[str]]:
        """Read index data from modern or legacy .npz schema safely."""
        return read_index_file(path)

    def _reset_empty(self) -> None:
        self.embeddings = np.empty((0, 0), dtype=np.float32)
        self.texts = []
        self.sources = []
        self._index_map = {}
        self._mtime = 0.0
        self._loaded = True
        self._dirty = False
        self._pending_updates.clear()

    def load(self) -> VectorStore:
        """Nạp chỉ mục vector từ tệp .npz hoặc .npz.bak."""
        if self._batch_depth > 0:
            return self

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
            self._dirty = False
            self._pending_updates.clear()
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
        """Tìm kiếm cosine similarity trả về danh sách (stem, score) sắp xếp giảm dần."""
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

    def _atomic_save(self, embeddings: np.ndarray | list[np.ndarray], texts: list[str], sources: list[str]) -> bool:
        """Atomic write to index_path with temporary file and backup synchronization."""
        return atomic_save_index(self.index_path, self.bak_path, embeddings, texts, sources)

    def flush(self) -> bool:
        """Ghi các cập nhật đang chờ trong RAM xuống tệp chỉ mục trên đĩa."""
        if not self._dirty:
            return True
        try:
            with CrossProcessFileLock(self.lock_path):
                current_mtime = self.index_path.stat().st_mtime if self.index_path.exists() else 0.0
                if current_mtime > self._mtime:
                    embs_list, texts, sources = self._read_index_data(self.index_path)
                    if not sources and self.bak_path.exists():
                        embs_list, texts, sources = self._read_index_data(self.bak_path)
                    if not sources and self.sources:
                        save_embs, save_texts, save_sources = self.embeddings, self.texts, self.sources
                    else:
                        save_embs, save_texts, save_sources = merge_pending_updates(
                            sources, texts, embs_list, self._pending_updates
                        )
                else:
                    save_embs, save_texts, save_sources = self.embeddings, self.texts, self.sources

                if not self._atomic_save(save_embs, save_texts, save_sources):
                    return False

                self.sources = list(save_sources)
                self.texts = list(save_texts)
                self.embeddings = np.array(save_embs, dtype=np.float32) if self.sources else np.empty((0, 0), dtype=np.float32)
                self._index_map = {src: i for i, src in enumerate(self.sources)}
                try:
                    self._mtime = self.index_path.stat().st_mtime
                except OSError:
                    self._mtime = time.time()
                self._dirty = False
                self._loaded = True
                self._pending_updates.clear()
                return True
        except Exception as e:
            _logger.error(f"Failed to flush vector store: {e}")
            return False

    @contextmanager
    def batch(self) -> Generator[VectorStore, None, None]:
        """Context manager gộp các thao tác hot_insert thành một lần flush duy nhất."""
        if not self._loaded and (self.index_path.exists() or self.bak_path.exists()):
            self.load()
        self._batch_depth += 1
        try:
            yield self
        finally:
            self._batch_depth = max(0, self._batch_depth - 1)
            if self._batch_depth == 0 and self._dirty:
                self.flush()

    def hot_insert(
        self,
        stem: str,
        content: str,
        embedding: np.ndarray | list[float] | None = None,
        auto_save: bool = True,
    ) -> bool:
        """Hot-insert or update embedding vector in memory and conditionally flush."""
        stem = stem.replace(".md", "").strip()
        if not stem:
            return False
        try:
            if not self._loaded and (self.index_path.exists() or self.bak_path.exists()):
                self.load()
            if embedding is None:
                emb_vec = get_embedding(content)
            else:
                emb_vec = np.array(embedding, dtype=np.float32).flatten()
                norm = np.linalg.norm(emb_vec)
                emb_vec = emb_vec / norm if norm > 0 else emb_vec
            if emb_vec is None or emb_vec.size == 0:
                _logger.warning(f"Invalid embedding for hot-insert of '{stem}'")
                return False
            if self.embeddings.size > 0 and emb_vec.shape[0] != self.embeddings.shape[1]:
                _logger.error(f"Dimension mismatch for '{stem}': {self.embeddings.shape[1]} vs {emb_vec.shape[0]}")
                return False
            content_hash = f"hash:{hashlib.md5(content.encode('utf-8')).hexdigest()}"
            if stem in self._index_map:
                idx = self._index_map[stem]
                self.embeddings[idx] = emb_vec
                self.texts[idx] = content_hash
            else:
                new_embs = emb_vec.reshape(1, -1) if self.embeddings.size == 0 else np.vstack([self.embeddings, emb_vec.reshape(1, -1)])
                self.embeddings = new_embs
                self.sources.append(stem)
                self.texts.append(content_hash)
                self._index_map[stem] = len(self.sources) - 1
            self._pending_updates[stem] = (content_hash, emb_vec)
            self._dirty = True
            self._loaded = True
            if self._batch_depth == 0 and auto_save:
                return self.flush()
            return True
        except Exception as e:
            _logger.error(f"Unexpected error in hot_insert for '{stem}': {e}")
            return False

    def sync_all(self, concepts: list[dict] | None = None) -> dict[str, int]:
        """Đồng bộ hóa toàn bộ danh mục concept notes vào tệp chỉ mục vector."""
        from core.vector_sync import sync_vector_index

        return sync_vector_index(self, concepts=concepts)
