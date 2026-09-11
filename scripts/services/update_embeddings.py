"""VvC Second Brain — Auto-Embedding Synchronizer.

Synchronizes the _embedding_index.npz file with the concepts directory.
Delegates to VectorStore.sync_all for cross-process concurrency and atomic updates.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_SCRIPT_DIR.parent))

from core.config import cfg
from core.llm.embedding_client import get_embedding
from core.vector_store import VectorStore

_logger = logging.getLogger("vvc.embedding_sync")

EMBEDDING_INDEX_PATH = cfg.state_dir / "_embedding_index.npz"




def _get_document_embedding(text: str):
    """Backward-compatible wrapper delegating to core.llm.embedding_client."""
    return get_embedding(text)


def sync_embeddings(concepts: list[dict] | None = None) -> None:
    """Synchronize the embedding index with the concepts directory."""
    store = VectorStore.get_instance()
    stats = store.sync_all(concepts)
    _logger.info(f"Sync complete: {stats}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    sync_embeddings()
