"""VvC Second Brain — Auto-Embedding Synchronizer.

Synchronizes the _embedding_index.npz file with the concepts directory.
Detects new and modified files, fetches Gemini embeddings, and updates the index.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR.parent))

import hashlib
import numpy as np
import requests

from core.config import cfg
from core.vault import scan_all_concepts

_logger = logging.getLogger("vvc.embedding_sync")

EMBEDDING_INDEX_PATH = Path(__file__).parent.parent / "_embedding_index.npz"


def _compute_md5(text: str) -> str:
    """Compute MD5 hash of the given text."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _get_document_embedding(text: str) -> np.ndarray | None:
    """Get embedding for a document via AI Gateway (gemini-embed)."""
    if not cfg.gateway_url:
        _logger.error("AI Gateway URL is not configured.")
        return None
    try:
        url = f"{cfg.gateway_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {cfg.gateway_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "gemini-embed",
            "input": [text],
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        values = resp.json()["data"][0]["embedding"]
        return np.array(values, dtype=np.float32)
    except Exception as e:
        _logger.warning(f"Failed to embed document via AI Gateway: {e}")
        return None


def sync_embeddings(concepts: list[dict] | None = None) -> None:
    """Synchronize the embedding index with the concepts directory."""
    _logger.info("Starting embedding synchronization...")
    if not cfg.gateway_url or not cfg.gateway_api_key:
        _logger.error("AI Gateway config (URL/API Key) not found. Cannot sync embeddings.")
        return

    # Load existing index (with automatic backup restoration guard)
    existing_sources = []
    existing_texts = []
    existing_embeddings = []

    bak_path = EMBEDDING_INDEX_PATH.with_suffix(".npz.bak")
    loaded_data = None

    if EMBEDDING_INDEX_PATH.exists():
        try:
            loaded_data = np.load(EMBEDDING_INDEX_PATH, allow_pickle=True)
        except Exception as e:
            _logger.warning(f"Failed to load main index: {e}. Trying backup...")
            if bak_path.exists():
                try:
                    loaded_data = np.load(bak_path, allow_pickle=True)
                    _logger.info("Restoring from backup index...")
                except Exception as bak_err:
                    _logger.warning(f"Failed to load backup index: {bak_err}.")

    if loaded_data is not None:
        try:
            if "embeddings" in loaded_data:
                existing_embeddings = loaded_data["embeddings"].tolist()
                existing_texts = loaded_data["texts"].tolist()
                existing_sources = loaded_data["sources"].tolist()
            elif "vectors" in loaded_data and "stems" in loaded_data:
                # Migrate legacy format
                _logger.info("Migrating legacy index format...")
                legacy_vectors = loaded_data["vectors"].tolist()
                legacy_sources = loaded_data["stems"].tolist()
                for i, stem in enumerate(legacy_sources):
                    fpath = cfg.concepts_dir / f"{stem}.md"
                    text = fpath.read_text(encoding="utf-8")[:2000] if fpath.exists() else ""
                    existing_sources.append(stem)
                    existing_texts.append(text)
                    existing_embeddings.append(legacy_vectors[i])
        except Exception as parse_err:
            _logger.warning(f"Failed to parse loaded index data: {parse_err}. Starting fresh.")

    # Create maps for fast lookup
    index_map = {src: i for i, src in enumerate(existing_sources)}
    
    new_sources = []
    new_texts = []
    new_embeddings = []
    
    # Track which sources are still valid
    valid_sources = set()
    
    updated_count = 0
    new_count = 0

    # Scan concepts directory (use shared data if provided)
    if concepts is None:
        concepts = scan_all_concepts()
    
    circuit_breaker_tripped = False
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 5
    backoff_delay = 1.5  # Start with base throttle delay

    for fm in concepts:
        fpath = fm["_path"]
        stem = fm["_stem"]
        valid_sources.add(stem)
        
        try:
            full_content = fpath.read_text(encoding="utf-8")
            current_hash = f"hash:{_compute_md5(full_content)}"
            current_text_for_embedding = full_content[:2000]
        except Exception:
            continue

        needs_embedding = False
        if stem in index_map:
            idx = index_map[stem]
            old_text = existing_texts[idx]
            # Check if text changed significantly using hash guard
            if isinstance(old_text, str) and old_text.startswith("hash:"):
                if current_hash != old_text:
                    if not circuit_breaker_tripped:
                        needs_embedding = True
                        updated_count += 1
            else:
                # Migrate legacy to hash format by forcing one re-embed
                if not circuit_breaker_tripped:
                    needs_embedding = True
                    updated_count += 1
        else:
            if not circuit_breaker_tripped:
                needs_embedding = True
                new_count += 1
            else:
                # New concept but circuit breaker is tripped: we cannot get its embedding
                continue

        if needs_embedding:
            _logger.info(f"Embedding: {stem}")
            emb = _get_document_embedding(current_text_for_embedding)
            if emb is not None:
                new_sources.append(stem)
                new_texts.append(current_hash)  # Store MD5 hash prefix in index
                new_embeddings.append(emb)
                consecutive_errors = 0  # Reset on success
            else:
                consecutive_errors += 1
                # Exponential backoff: 3s → 6s → 12s → 24s → trip
                backoff_delay = min(3.0 * (2 ** (consecutive_errors - 1)), 30.0)
                _logger.warning(f"Embedding error {consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}. Backing off {backoff_delay:.0f}s...")
                time.sleep(backoff_delay)
                
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    _logger.error(
                        f"Consecutive embedding errors reached {MAX_CONSECUTIVE_ERRORS}. "
                        "Tripping embedding circuit breaker to protect API and speed up execution. "
                        "Skipping remaining new embeddings."
                    )
                    circuit_breaker_tripped = True
                
                # If we failed to get a new embedding:
                # Keep the old one if it exists to preserve index integrity
                if stem in index_map:
                    idx = index_map[stem]
                    new_sources.append(stem)
                    new_texts.append(existing_texts[idx])
                    new_embeddings.append(existing_embeddings[idx])
            
            time.sleep(0.2)  # Throttle to avoid rate limits via Gateway (reduced from 1.5s)
        else:
            # Keep existing
            idx = index_map[stem]
            new_sources.append(stem)
            old_text = existing_texts[idx]
            if isinstance(old_text, str) and old_text.startswith("hash:"):
                new_texts.append(old_text)
            else:
                # Automatically migrate to hash format for existing vectors on next pass
                new_texts.append(current_hash)
            new_embeddings.append(existing_embeddings[idx])

    if updated_count == 0 and new_count == 0 and len(valid_sources) == len(existing_sources):
        _logger.info("Embedding index is already up to date.")
        return

    _logger.info(f"Processed {new_count} new, {updated_count} updated, {len(existing_sources) - len(valid_sources)} deleted.")
    
    if not new_embeddings:
        _logger.warning("No valid embeddings to save.")
        return

    # Save updated index
    try:
        np.savez_compressed(
            EMBEDDING_INDEX_PATH,
            embeddings=np.array(new_embeddings, dtype=np.float32),
            texts=np.array(new_texts, dtype=object),
            sources=np.array(new_sources, dtype=object),
        )
        _logger.info(f"Embedding index saved successfully: {len(new_sources)} concepts.")
        
        # Automatic Backup Sync Guard
        try:
            import shutil
            shutil.copy2(EMBEDDING_INDEX_PATH, EMBEDDING_INDEX_PATH.with_suffix(".npz.bak"))
            _logger.info("Embedding index backup created successfully.")
        except Exception as bak_err:
            _logger.warning(f"Failed to create embedding index backup: {bak_err}")
    except Exception as e:
        _logger.error(f"Failed to save embedding index: {e}")

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    sync_embeddings()
