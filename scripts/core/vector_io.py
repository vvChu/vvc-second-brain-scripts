"""VvC Second Brain — Vector Store I/O & Storage Layer.

Handles low-level reading and writing for the embedding index (.npz):
- Atomic file writing with temporary file and backup synchronization (.npz.bak)
- Safe loading with np.load context management
- Legacy format migration ('vectors' & 'stems')
- Embedding L2-normalization
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import numpy as np

from core.config import cfg

_logger = logging.getLogger("vvc.vector_io")


def _extract_legacy_texts(stems: list[str]) -> list[str]:
    """Read concept text prefixes for legacy format entries."""
    texts: list[str] = []
    for stem in stems:
        fpath = cfg.concepts_dir / f"{stem}.md"
        if fpath.exists():
            try:
                texts.append(fpath.read_text(encoding="utf-8")[:2000])
            except Exception:
                texts.append("")
        else:
            texts.append("")
    return texts


def _normalize_embeddings(raw_embs: np.ndarray) -> list[np.ndarray]:
    """Normalize raw embeddings to unit L2 length."""
    if raw_embs.size == 0:
        return []
    embs_arr = np.array(raw_embs, dtype=np.float32)
    if embs_arr.ndim == 1:
        embs_arr = embs_arr.reshape(1, -1)
    norms = np.linalg.norm(embs_arr, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    embs_arr = embs_arr / norms
    return list(embs_arr)


def read_index_file(path: Path) -> tuple[list[np.ndarray], list[str], list[str]]:
    """Read index data from modern or legacy .npz schema safely."""
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
                raw_texts = _extract_legacy_texts(raw_sources)
            else:
                _logger.warning(f"Unrecognized index structure in {path}")
                return [], [], []

            sources = [str(s) for s in raw_sources]
            texts = [str(t) for t in raw_texts]
            embeddings = _normalize_embeddings(raw_embs)
            return embeddings, texts, sources
    except Exception as e:
        _logger.warning(f"Failed to read index data from {path}: {e}")
        return [], [], []


def atomic_save_index(
    index_path: Path,
    bak_path: Path,
    embeddings: np.ndarray | list[np.ndarray],
    texts: list[str],
    sources: list[str],
) -> bool:
    """Atomic write to index_path with temporary file and backup synchronization."""
    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = index_path.parent / f"{index_path.stem}_tmp.npz"
    bak_tmp = bak_path.with_suffix(".npz.bak.tmp")
    try:
        arr_embs = np.array(embeddings, dtype=np.float32)
        if arr_embs.ndim == 1 and arr_embs.size > 0:
            arr_embs = arr_embs.reshape(1, -1)
        elif arr_embs.size == 0:
            arr_embs = np.empty((0, 0), dtype=np.float32)
        np.savez_compressed(
            tmp_path,
            embeddings=arr_embs,
            texts=np.array(texts, dtype=object),
            sources=np.array(sources, dtype=object),
        )
        os.replace(tmp_path, index_path)
        try:
            shutil.copy2(index_path, bak_tmp)
            os.replace(bak_tmp, bak_path)
        except Exception as bak_err:
            _logger.warning(f"Failed to sync backup index: {bak_err}")
        return True
    except Exception as e:
        _logger.error(f"Failed to atomic save vector store: {e}")
        return False
    finally:
        for p in (tmp_path, bak_tmp):
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass


def merge_pending_updates(
    sources: list[str],
    texts: list[str],
    embs_list: list[np.ndarray],
    pending: dict[str, tuple[str, np.ndarray]],
) -> tuple[np.ndarray, list[str], list[str]]:
    """Merge pending in-memory updates into disk-loaded index arrays."""
    idx_map = {src: i for i, src in enumerate(sources)}
    for stem, (c_hash, emb_vec) in pending.items():
        if stem in idx_map:
            i = idx_map[stem]
            embs_list[i] = emb_vec
            texts[i] = c_hash
        else:
            sources.append(stem)
            texts.append(c_hash)
            embs_list.append(emb_vec)
            idx_map[stem] = len(sources) - 1
    save_embs = np.array(embs_list, dtype=np.float32) if embs_list else np.empty((0, 0), dtype=np.float32)
    return save_embs, texts, sources

