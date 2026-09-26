"""VvC Second Brain — Vector Store Synchronization Engine.

Coordinates full embedding synchronization across all vault concepts:
- Cross-process concurrency protection via CrossProcessFileLock
- MD5 content hash change detection (avoiding redundant embedding generation)
- Exponential backoff retry and circuit breaker protection
- Atomic index saving and store state synchronization
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from core.config import cfg
from core.file_lock import CrossProcessFileLock
from core.llm.embedding_client import get_embedding

if TYPE_CHECKING:
    from core.vector_store import VectorStore

_logger = logging.getLogger("vvc.vector_sync")


class CircuitBreaker:
    """Manages consecutive embedding API failure backoff and circuit tripping."""

    def __init__(self, max_consecutive_errors: int = 5) -> None:
        self.consecutive_errors: int = 0
        self.max_errors: int = max_consecutive_errors
        self.tripped: bool = False

    def record_success(self) -> None:
        """Reset consecutive error count on successful API call."""
        self.consecutive_errors = 0

    def record_failure(self) -> None:
        """Record an API error, apply backoff delay, and trip if threshold reached."""
        self.consecutive_errors += 1
        backoff_delay = min(3.0 * (2 ** (self.consecutive_errors - 1)), 30.0)
        _logger.warning(
            f"Embedding error {self.consecutive_errors}/{self.max_errors}. "
            f"Backing off {backoff_delay:.0f}s..."
        )
        time.sleep(backoff_delay)
        if self.consecutive_errors >= self.max_errors:
            _logger.error(
                f"Consecutive embedding errors reached {self.max_errors}. "
                "Tripping circuit breaker."
            )
            self.tripped = True


@dataclass
class SyncContext:
    """State tracking context during full embedding synchronization."""

    existing_sources: list[str]
    existing_texts: list[str]
    existing_embeddings: list[np.ndarray]
    index_map: dict[str, int]
    new_sources: list[str] = field(default_factory=list)
    new_texts: list[str] = field(default_factory=list)
    new_embeddings: list[np.ndarray] = field(default_factory=list)
    valid_sources: set[str] = field(default_factory=set)
    updated_count: int = 0
    new_count: int = 0


def _parse_concept(fm: dict) -> tuple[str, str, str] | None:
    """Extract stem, MD5 hash, and embedding text prefix from concept frontmatter."""
    raw_path = fm.get("_path") or fm.get("path")
    if raw_path is None:
        return None
    fpath = Path(raw_path)
    stem = str(fm.get("_stem") or fm.get("stem") or fpath.stem)
    try:
        full_content = fpath.read_text(encoding="utf-8")
        current_hash = f"hash:{hashlib.md5(full_content.encode('utf-8')).hexdigest()}"
        text_prefix = full_content[:2000]
        return stem, current_hash, text_prefix
    except Exception:
        return None


def _handle_new_embedding(
    ctx: SyncContext,
    stem: str,
    current_hash: str,
    text_prefix: str,
    cb: CircuitBreaker,
    in_index: bool,
) -> None:
    """Request embedding and handle success or fallback upon error."""
    _logger.info(f"Embedding: {stem}")
    emb = get_embedding(text_prefix)
    if emb is not None:
        ctx.new_sources.append(stem)
        ctx.new_texts.append(current_hash)
        ctx.new_embeddings.append(emb)
        cb.record_success()
    else:
        cb.record_failure()
        if in_index:
            idx = ctx.index_map[stem]
            ctx.new_sources.append(stem)
            ctx.new_texts.append(ctx.existing_texts[idx])
            ctx.new_embeddings.append(ctx.existing_embeddings[idx])
    time.sleep(0.2)


def _process_concept_item(
    ctx: SyncContext,
    stem: str,
    current_hash: str,
    text_prefix: str,
    cb: CircuitBreaker,
) -> None:
    """Process a single concept note against the existing index state."""
    ctx.valid_sources.add(stem)
    needs_embedding = False
    in_index = stem in ctx.index_map

    if in_index:
        idx = ctx.index_map[stem]
        old_text = ctx.existing_texts[idx]
        if isinstance(old_text, str) and old_text.startswith("hash:") and current_hash != old_text:
            if not cb.tripped:
                needs_embedding = True
                ctx.updated_count += 1
    else:
        if not cb.tripped:
            needs_embedding = True
            ctx.new_count += 1
        else:
            return

    if needs_embedding:
        _handle_new_embedding(ctx, stem, current_hash, text_prefix, cb, in_index)
    else:
        idx = ctx.index_map[stem]
        ctx.new_sources.append(stem)
        old_text = ctx.existing_texts[idx]
        preserved_text = old_text if isinstance(old_text, str) and old_text.startswith("hash:") else current_hash
        ctx.new_texts.append(preserved_text)
        ctx.new_embeddings.append(ctx.existing_embeddings[idx])


def _commit_sync_results(store: VectorStore, ctx: SyncContext, deleted_count: int) -> dict[str, int]:
    """Persist synchronized vectors to disk and update in-memory store state."""
    if not ctx.new_embeddings:
        _logger.warning("No valid embeddings to save.")
        return {"new": 0, "updated": 0, "deleted": deleted_count, "total": 0}

    if not store._atomic_save(ctx.new_embeddings, ctx.new_texts, ctx.new_sources):
        _logger.error("Failed to save embedding index.")
        return {"new": ctx.new_count, "updated": ctx.updated_count, "deleted": deleted_count, "total": 0}

    store.sources = ctx.new_sources
    store.texts = ctx.new_texts
    store.embeddings = np.array(ctx.new_embeddings, dtype=np.float32)
    store._index_map = {src: i for i, src in enumerate(store.sources)}
    try:
        store._mtime = store.index_path.stat().st_mtime
    except OSError:
        store._mtime = time.time()
    store._dirty = False
    store._pending_updates.clear()
    _logger.info(f"Embedding index saved successfully: {len(ctx.new_sources)} concepts.")
    return {"new": ctx.new_count, "updated": ctx.updated_count, "deleted": deleted_count, "total": len(ctx.new_sources)}


def sync_vector_index(store: VectorStore, concepts: list[dict] | None = None) -> dict[str, int]:
    """Đồng bộ hóa toàn bộ danh mục concept notes vào tệp chỉ mục vector."""
    from core.vault import scan_all_concepts

    _logger.info("Starting full embedding synchronization...")
    if not cfg.gateway_url or not cfg.gateway_api_key:
        _logger.error("AI Gateway config not found. Cannot sync embeddings.")
        return {"new": 0, "updated": 0, "deleted": 0, "total": 0}

    try:
        with CrossProcessFileLock(store.lock_path):
            store.load()
            ctx = SyncContext(
                existing_sources=list(store.sources),
                existing_texts=list(store.texts),
                existing_embeddings=list(store.embeddings),
                index_map={src: i for i, src in enumerate(store.sources)},
            )
            if concepts is None:
                concepts = scan_all_concepts()

            cb = CircuitBreaker()
            for fm in concepts:
                parsed = _parse_concept(fm)
                if parsed is None:
                    continue
                stem, current_hash, text_prefix = parsed
                _process_concept_item(ctx, stem, current_hash, text_prefix, cb)

            deleted_count = len(ctx.existing_sources) - len(ctx.valid_sources)
            if ctx.updated_count == 0 and ctx.new_count == 0 and deleted_count == 0:
                _logger.info("Embedding index is already up to date.")
                return {"new": 0, "updated": 0, "deleted": 0, "total": len(ctx.new_sources)}

            _logger.info(f"Processed {ctx.new_count} new, {ctx.updated_count} updated, {deleted_count} deleted.")
            return _commit_sync_results(store, ctx, deleted_count)
    except Exception as e:
        _logger.error(f"Failed in sync_vector_index: {e}")
        return {"new": 0, "updated": 0, "deleted": 0, "total": 0}
