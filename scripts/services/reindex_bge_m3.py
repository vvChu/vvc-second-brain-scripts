"""VvC Second Brain — Batch Re-indexer for Local BAAI/bge-m3 (1024-d).

Performs full vault vector re-indexing with checkpointing, sanity checks,
and atomic cutover from Gemini (3072-d) to local BGE-M3 (1024-d).
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from core.config import cfg
from core.llm.embedding_client import get_embeddings_batch
from core.vector_io import atomic_save_index, read_index_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_logger = logging.getLogger("vvc.reindex_bge_m3")

STAGING_INDEX_PATH = cfg.state_dir / "_embedding_index.bge_m3.npz"
PROD_INDEX_PATH = cfg.state_dir / "_embedding_index.npz"
BACKUP_INDEX_PATH = cfg.state_dir / "_embedding_index.gemini_3072.bak.npz"


def _load_existing_checkpoint(path: Path) -> tuple[dict[str, np.ndarray], dict[str, str]]:
    """Load existing vectors and hash texts from staging checkpoint if present."""
    if not path.exists():
        return {}, {}
    try:
        embs, texts, sources = read_index_file(path)
        emb_map = {s: e for s, e in zip(sources, embs)}
        text_map = {s: t for s, t in zip(sources, texts)}
        _logger.info(f"Loaded existing checkpoint: {len(emb_map)} vectors from {path.name}")
        return emb_map, text_map
    except Exception as e:
        _logger.warning(f"Failed to read staging checkpoint ({e}). Starting fresh.")
        return {}, {}


def _collect_concept_files(concepts_dir: Path) -> list[tuple[str, str, str]]:
    """Scan and sort all concept markdown files deterministically."""
    items: list[tuple[str, str, str]] = []
    for p in sorted(concepts_dir.glob("*.md"), key=lambda x: x.stem):
        try:
            content = p.read_text(encoding="utf-8")
        except OSError:
            continue
        md5_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
        items.append((p.stem, content[:2000], f"hash:{md5_hash}"))
    return items


def _save_checkpoint(path: Path, sources: list[str], embs: list[np.ndarray], texts: list[str]) -> bool:
    """Save staging index checkpoint."""
    matrix = np.array(embs, dtype=np.float32)
    bak_path = path.with_suffix(".npz.bak")
    return atomic_save_index(path, bak_path, matrix, texts, sources)


def _process_batches(
    items: list[tuple[str, str, str]],
    emb_map: dict[str, np.ndarray],
    text_map: dict[str, str],
    batch_size: int = 16,
) -> None:
    """Process concept note embeddings in batches with progressive checkpointing."""
    to_embed = [it for it in items if it[0] not in emb_map]
    total = len(to_embed)
    _logger.info(f"Total concepts: {len(items)} | Already cached: {len(emb_map)} | To embed: {total}")

    processed = 0
    t0 = time.time()
    for i in range(0, total, batch_size):
        batch = to_embed[i : i + batch_size]
        stems = [it[0] for it in batch]
        texts = [it[1] for it in batch]
        hashes = [it[2] for it in batch]

        vectors = get_embeddings_batch(texts, timeout=30.0)
        for s, vec, h in zip(stems, vectors, hashes):
            if vec is not None and vec.shape[0] == 1024:
                emb_map[s] = vec
                text_map[s] = h
            else:
                _logger.error(f"Failed to embed concept: {s}")

        processed += len(batch)
        if (i // batch_size) % 10 == 0 or processed == total:
            sources_now = [it[0] for it in items if it[0] in emb_map]
            embs_now = [emb_map[s] for s in sources_now]
            texts_now = [text_map[s] for s in sources_now]
            _save_checkpoint(STAGING_INDEX_PATH, sources_now, embs_now, texts_now)
            elapsed = time.time() - t0
            rate = processed / elapsed if elapsed > 0 else 0
            _logger.info(f"Progress: {processed}/{total} ({processed*100//total}%) — {rate:.1f} notes/s")


def verify_sanity_gate(index_path: Path, items: list[tuple[str, str, str]]) -> bool:
    """Perform Gate 2 Sanity Verification on generated staging index."""
    _logger.info(f"Verifying Sanity Gate on {index_path.name}...")
    if not index_path.exists():
        _logger.error("Index file does not exist.")
        return False

    embs, texts, sources = read_index_file(index_path)
    if len(sources) != len(items):
        _logger.error(f"Count mismatch: index has {len(sources)}, vault has {len(items)}")
        return False

    matrix = np.array(embs, dtype=np.float32)
    if matrix.shape != (len(items), 1024):
        _logger.error(f"Shape mismatch: expected ({len(items)}, 1024), got {matrix.shape}")
        return False

    if np.isnan(matrix).any() or np.isinf(matrix).any():
        _logger.error("Matrix contains NaN or Inf values.")
        return False

    norms = np.linalg.norm(matrix, axis=1)
    if np.max(np.abs(norms - 1.0)) > 1e-3:
        _logger.error("L2 normalization error exceeds tolerance 1e-3.")
        return False

    # Check top-1 self-hit query
    test_idx = len(items) // 2
    test_stem, test_text, _ = items[test_idx]
    scores = np.dot(matrix, matrix[test_idx])
    top_idx = int(np.argmax(scores))
    if sources[top_idx] != test_stem:
        _logger.error(f"Top-1 self-hit failed: expected {test_stem}, got {sources[top_idx]}")
        return False

    _logger.info(f"Sanity Gate PASSED: {len(sources)} notes, 1024-d, Top-1 score: {scores[top_idx]:.4f}")
    return True


def perform_atomic_cutover() -> bool:
    """Safely cut over staging index to production with daemon lifecycle guard."""
    _logger.info("Executing Phase 3: Atomic Cutover to BGE-M3 (1024-d)...")
    try:
        subprocess.run(["systemctl", "--user", "stop", "vvc-daemon.service"], check=True)
        _logger.info("Stopped vvc-daemon.service.")
    except Exception as e:
        _logger.warning(f"Could not stop vvc-daemon via systemctl: {e}")

    try:
        if PROD_INDEX_PATH.exists():
            shutil.copy2(PROD_INDEX_PATH, BACKUP_INDEX_PATH)
            _logger.info(f"Backed up old index to {BACKUP_INDEX_PATH.name}")

        os.replace(STAGING_INDEX_PATH, PROD_INDEX_PATH)
        _logger.info(f"Atomically replaced {PROD_INDEX_PATH.name} with 1024-d BGE-M3 index.")
    except Exception as e:
        _logger.error(f"Cutover failed: {e}")
        return False
    finally:
        try:
            subprocess.run(["systemctl", "--user", "start", "vvc-daemon.service"], check=True)
            _logger.info("Restarted vvc-daemon.service.")
        except Exception as e:
            _logger.warning(f"Could not start vvc-daemon via systemctl: {e}")

    return True


def main() -> None:
    """CLI entrypoint for batch re-indexing."""
    parser = argparse.ArgumentParser(description="Batch re-index vault concepts with local BGE-M3.")
    parser.add_argument("--cutover", action="store_true", help="Perform atomic cutover if sanity gate passes.")
    parser.add_argument("--batch-size", type=int, default=16, help="Batch size for embedding API (default: 16).")
    args = parser.parse_args()

    items = _collect_concept_files(cfg.concepts_dir)
    emb_map, text_map = _load_existing_checkpoint(STAGING_INDEX_PATH)

    _process_batches(items, emb_map, text_map, batch_size=args.batch_size)

    if not verify_sanity_gate(STAGING_INDEX_PATH, items):
        _logger.error("Sanity gate verification failed. Cutover aborted.")
        sys.exit(1)

    if args.cutover:
        if not perform_atomic_cutover():
            sys.exit(1)
        _logger.info("Cutover completed successfully!")


if __name__ == "__main__":
    main()
