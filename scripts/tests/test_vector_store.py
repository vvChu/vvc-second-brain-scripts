"""Tests for core/vector_store.py and core/llm/embedding_client.py."""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import cfg
from core.vector_store import VectorStore
from core.llm.embedding_client import get_embedding, get_embedding_via_gateway


def test_vector_store_empty_init(tmp_path):
    """Test VectorStore when no index file exists."""
    index_path = tmp_path / "_embedding_index.npz"
    store = VectorStore(index_path)
    store.load()

    assert len(store) == 0
    assert store.embeddings.shape == (0, 0)
    assert store.sources == []
    assert store.texts == []
    assert store.search(np.array([1.0, 0.0])) == []


def test_vector_store_hot_insert_and_search(tmp_path):
    """Test hot_insert creates valid .npz and .npz.bak, and search works accurately."""
    index_path = tmp_path / "_embedding_index.npz"
    bak_path = index_path.with_suffix(".npz.bak")
    store = VectorStore(index_path)

    # Insert first item: [1.0, 0.0, 0.0]
    vec_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    success = store.hot_insert("concept_alpha", "Content of alpha concept", embedding=vec_a)
    assert success is True
    assert index_path.exists()
    assert bak_path.exists()
    assert len(store) == 1
    assert store.sources == ["concept_alpha"]

    # Insert second item: [0.0, 1.0, 0.0]
    vec_b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    success = store.hot_insert("concept_beta", "Content of beta concept", embedding=vec_b)
    assert success is True
    assert len(store) == 2
    assert store.sources == ["concept_alpha", "concept_beta"]

    # Search with query aligned with alpha: [1.0, 0.0, 0.0]
    results = store.search(np.array([1.0, 0.0, 0.0]), top_k=2)
    assert len(results) == 2
    assert results[0][0] == "concept_alpha"
    assert pytest.approx(results[0][1], 0.001) == 1.0
    assert results[1][0] == "concept_beta"
    assert pytest.approx(results[1][1], 0.001) == 0.0

    # Search with threshold: should only return alpha
    thresh_results = store.search(np.array([1.0, 0.0, 0.0]), threshold=0.5)
    assert len(thresh_results) == 1
    assert thresh_results[0][0] == "concept_alpha"

    # Search indices for RRF
    indices = store.search_indices(np.array([0.0, 1.0, 0.0]), top_k=1)
    assert len(indices) == 1
    assert indices[0][0] == 1  # index of concept_beta
    assert pytest.approx(indices[0][1], 0.001) == 1.0


def test_vector_store_hot_insert_update_existing(tmp_path):
    """Test hot_insert updates an existing concept without increasing count."""
    index_path = tmp_path / "_embedding_index.npz"
    store = VectorStore(index_path)

    vec1 = np.array([1.0, 0.0], dtype=np.float32)
    store.hot_insert("concept_alpha", "Initial text", embedding=vec1)
    assert len(store) == 1

    vec2 = np.array([0.0, 1.0], dtype=np.float32)
    store.hot_insert("concept_alpha", "Updated text", embedding=vec2)
    assert len(store) == 1
    assert store.sources == ["concept_alpha"]

    # Verify updated vector is active in search
    res = store.search(np.array([0.0, 1.0]), top_k=1)
    assert res[0][0] == "concept_alpha"
    assert pytest.approx(res[0][1], 0.001) == 1.0


def test_vector_store_corrupt_index_fallback(tmp_path):
    """Test VectorStore recovers from .npz.bak when main .npz is corrupted."""
    index_path = tmp_path / "_embedding_index.npz"
    bak_path = index_path.with_suffix(".npz.bak")
    store = VectorStore(index_path)

    vec = np.array([0.6, 0.8], dtype=np.float32)
    store.hot_insert("resilient_concept", "Content", embedding=vec)
    assert index_path.exists()
    assert bak_path.exists()

    # Corrupt main index file
    index_path.write_bytes(b"CORRUPTED_GARBAGE_HEADER_DATA")

    # Reload new instance
    reloaded_store = VectorStore(index_path)
    reloaded_store.load()

    assert len(reloaded_store) == 1
    assert reloaded_store.sources == ["resilient_concept"]


def test_vector_store_get_instance_caching_and_mtime(tmp_path):
    """Test get_instance singleton caching and automatic reload on mtime change."""
    index_path = tmp_path / "singleton_index.npz"

    store1 = VectorStore.get_instance(index_path)
    store2 = VectorStore.get_instance(index_path)
    assert store1 is store2

    # Insert item
    vec = np.array([1.0, 0.0], dtype=np.float32)
    store1.hot_insert("cached_concept", "Text", embedding=vec)

    # Modify file mtime artificially to test reload
    current_mtime = index_path.stat().st_mtime
    os.utime(index_path, (current_mtime + 5, current_mtime + 5))

    store3 = VectorStore.get_instance(index_path)
    assert len(store3) == 1


def test_vector_store_legacy_format_migration(tmp_path):
    """Test VectorStore.load() properly migrates legacy 'vectors' and 'stems' keys."""
    index_path = tmp_path / "legacy_index.npz"
    vecs = np.array([[0.6, 0.8], [1.0, 0.0]], dtype=np.float32)
    stems = np.array(["legacy_concept_1", "legacy_concept_2"], dtype=object)
    np.savez(index_path, vectors=vecs, stems=stems)

    store = VectorStore(index_path)
    store.load()

    assert len(store) == 2
    assert store.sources == ["legacy_concept_1", "legacy_concept_2"]
    assert store.embeddings.shape == (2, 2)
    # Cosine search works on migrated store
    res = store.search(np.array([1.0, 0.0]), top_k=1)
    assert res[0][0] == "legacy_concept_2"


def test_vector_store_hot_insert_on_legacy_format(tmp_path):
    """Test hot_insert preserves existing items when index is in legacy format."""
    index_path = tmp_path / "legacy_hot_insert.npz"
    vecs = np.array([[1.0, 0.0]], dtype=np.float32)
    stems = np.array(["pre_existing_concept"], dtype=object)
    np.savez(index_path, vectors=vecs, stems=stems)

    store = VectorStore(index_path)
    success = store.hot_insert("newly_added_concept", "content", embedding=np.array([0.0, 1.0]))
    assert success is True

    store.load()
    assert len(store) == 2
    assert "pre_existing_concept" in store.sources
    assert "newly_added_concept" in store.sources


def test_vector_store_hot_insert_missing_texts_key(tmp_path):
    """Test hot_insert preserves existing items when index has embeddings and sources but no texts."""
    index_path = tmp_path / "no_texts_index.npz"
    embs = np.array([[1.0, 0.0]], dtype=np.float32)
    sources = np.array(["concept_no_text"], dtype=object)
    np.savez(index_path, embeddings=embs, sources=sources)

    store = VectorStore(index_path)
    success = store.hot_insert("concept_with_text", "content", embedding=np.array([0.0, 1.0]))
    assert success is True

    store.load()
    assert len(store) == 2
    assert "concept_no_text" in store.sources
    assert "concept_with_text" in store.sources


def test_vector_store_hot_insert_2d_embedding(tmp_path):
    """Test hot_insert automatically flattens 2D input embedding without dimension error."""
    index_path = tmp_path / "2d_embedding_index.npz"
    store = VectorStore(index_path)

    # Pass 2D embedding (shape 1, 3)
    vec_2d = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
    success = store.hot_insert("flat_concept", "content", embedding=vec_2d)
    assert success is True

    assert store.embeddings.shape == (1, 3)
    res = store.search(np.array([1.0, 0.0, 0.0]), top_k=1)
    assert res[0][0] == "flat_concept"


def test_vector_store_to_dict(tmp_path):
    """Test to_dict produces TypedDict required by downstream services."""
    index_path = tmp_path / "dict_index.npz"
    store = VectorStore(index_path)
    store.hot_insert("concept_1", "text 1", embedding=np.array([1.0, 0.0]))

    d = store.to_dict()
    assert "embeddings" in d
    assert "texts" in d
    assert "sources" in d
    assert d["sources"] == ["concept_1"]


def test_vector_store_sync_all_workflow(tmp_path):
    """Test VectorStore.sync_all() full lifecycle: new concepts, hash caching, updates, deletions."""
    orig_url = cfg.gateway_url
    orig_key = cfg.gateway_api_key
    object.__setattr__(cfg, "gateway_url", "http://test-gateway:8090")
    object.__setattr__(cfg, "gateway_api_key", "test-key")

    index_path = tmp_path / "sync_index.npz"
    store = VectorStore(index_path)

    # Create dummy concepts on disk
    note1 = tmp_path / "concept_one.md"
    note1.write_text("Original content for note one", encoding="utf-8")
    note2 = tmp_path / "concept_two.md"
    note2.write_text("Original content for note two", encoding="utf-8")

    concepts = [
        {"path": note1, "stem": "concept_one"},
        {"path": note2, "stem": "concept_two"},
    ]

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"data": [{"embedding": [1.0, 0.0]}]}

    try:
        with patch("core.llm.embedding_client.http_session.post", return_value=mock_resp):
            # 1. First sync: inserts 2 new concepts
            stats1 = store.sync_all(concepts)
            assert stats1["new"] == 2
            assert stats1["total"] == 2
            assert len(store) == 2

            # 2. Second sync with unchanged files: 0 updates, all cached by hash
            stats2 = store.sync_all(concepts)
            assert stats2["new"] == 0
            assert stats2["updated"] == 0
            assert stats2["total"] == 2

            # 3. Modify note1: 1 updated
            note1.write_text("Modified content for note one with extra tri thức", encoding="utf-8")
            stats3 = store.sync_all(concepts)
            assert stats3["updated"] == 1

            # 4. Remove note2 from concepts list: 1 deleted
            stats4 = store.sync_all([{"path": note1, "stem": "concept_one"}])
            assert stats4["deleted"] == 1
            assert stats4["total"] == 1
            assert store.sources == ["concept_one"]
    finally:
        object.__setattr__(cfg, "gateway_url", orig_url)
        object.__setattr__(cfg, "gateway_api_key", orig_key)


def test_vector_store_multiprocess_concurrent_hot_insert(tmp_path):
    """Test concurrent hot_insert from separate Python processes writes safely without corruption."""
    import subprocess
    index_file = tmp_path / "concurrent_index.npz"
    worker_script = tmp_path / "worker.py"
    worker_script.write_text("""
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from core.vector_store import VectorStore

stem = sys.argv[2]
index_path = sys.argv[3]
vec = [float(x) for x in sys.argv[4].split(',')]

store = VectorStore(index_path)
success = store.hot_insert(stem, f"Content of {stem}", embedding=vec)
print(f"{stem}:{success}", flush=True)
""")

    scripts_dir = str(Path(__file__).parent.parent)

    p1 = subprocess.Popen(
        [sys.executable, str(worker_script), scripts_dir, "stem_p1", str(index_file), "1.0,0.0"],
        stdout=subprocess.PIPE,
        text=True,
    )
    p2 = subprocess.Popen(
        [sys.executable, str(worker_script), scripts_dir, "stem_p2", str(index_file), "0.0,1.0"],
        stdout=subprocess.PIPE,
        text=True,
    )

    out1, _ = p1.communicate()
    out2, _ = p2.communicate()

    assert p1.returncode == 0
    assert p2.returncode == 0
    assert "stem_p1:True" in out1
    assert "stem_p2:True" in out2

    final_store = VectorStore(index_file)
    final_store.load()
    assert len(final_store) == 2
    assert "stem_p1" in final_store.sources
    assert "stem_p2" in final_store.sources


# --- Embedding Client Tests ---

def test_get_embedding_no_config():
    """Test get_embedding returns None when gateway is unconfigured."""
    orig_url = cfg.gateway_url
    orig_key = cfg.gateway_api_key
    object.__setattr__(cfg, "gateway_url", "")
    object.__setattr__(cfg, "gateway_api_key", "")
    try:
        assert get_embedding("test query") is None
        assert get_embedding_via_gateway("test query") is None
    finally:
        object.__setattr__(cfg, "gateway_url", orig_url)
        object.__setattr__(cfg, "gateway_api_key", orig_key)


def test_get_embedding_successful_normalization():
    """Test get_embedding properly normalizes vector to unit L2 length."""
    orig_url = cfg.gateway_url
    orig_key = cfg.gateway_api_key
    object.__setattr__(cfg, "gateway_url", "http://test-gateway:8090")
    object.__setattr__(cfg, "gateway_api_key", "test-key")

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "data": [{"embedding": [3.0, 4.0]}]  # norm = 5.0 -> [0.6, 0.8]
    }

    try:
        with patch("core.llm.embedding_client.http_session.post", return_value=mock_resp):
            emb = get_embedding("test normalization")
            assert emb is not None
            assert isinstance(emb, np.ndarray)
            assert pytest.approx(float(np.linalg.norm(emb)), 0.001) == 1.0
            assert pytest.approx(float(emb[0]), 0.001) == 0.6
            assert pytest.approx(float(emb[1]), 0.001) == 0.8

            emb_list = get_embedding_via_gateway("test normalization")
            assert isinstance(emb_list, list)
            assert pytest.approx(emb_list[0], 0.001) == 0.6
    finally:
        object.__setattr__(cfg, "gateway_url", orig_url)
        object.__setattr__(cfg, "gateway_api_key", orig_key)


# --- Context-Managed Batch Flush Tests ---

def test_batch_context_single_flush(tmp_path):
    """Test that inserting multiple items in a batch context triggers _atomic_save exactly once."""
    index_path = tmp_path / "_embedding_index.npz"
    store = VectorStore(index_path)

    with patch.object(store, "_atomic_save", wraps=store._atomic_save) as spy_save:
        with store.batch():
            for i in range(10):
                vec = np.array([float(i), 1.0], dtype=np.float32)
                res = store.hot_insert(f"concept_{i}", f"Content {i}", embedding=vec)
                assert res is True
            # Inside batch: not yet flushed to disk
            assert spy_save.call_count == 0
            assert store._dirty is True
            assert len(store._pending_updates) == 10

        # After exiting batch: single flush triggered
        assert spy_save.call_count == 1
        assert store._dirty is False
        assert len(store._pending_updates) == 0

    # Verify disk persistence
    reloaded = VectorStore(index_path).load()
    assert len(reloaded) == 10
    assert reloaded.sources[0] == "concept_0"
    assert reloaded.sources[9] == "concept_9"


def test_batch_in_flight_search(tmp_path):
    """Test that newly inserted items are immediately searchable in memory before flush."""
    index_path = tmp_path / "_embedding_index.npz"
    store = VectorStore(index_path)

    with store.batch():
        vec = np.array([1.0, 0.0], dtype=np.float32)
        store.hot_insert("concept_in_flight", "Immediate content", embedding=vec)

        # In-flight search must find the concept before the context manager exits
        results = store.search(np.array([1.0, 0.0]), top_k=1)
        assert len(results) == 1
        assert results[0][0] == "concept_in_flight"
        assert pytest.approx(results[0][1], 0.001) == 1.0


def test_batch_uninitialized_store_safety(tmp_path):
    """Test that entering batch on an uninitialized store auto-loads existing disk data without data loss."""
    index_path = tmp_path / "_embedding_index.npz"
    store1 = VectorStore(index_path)
    store1.hot_insert("concept_initial", "Initial note", embedding=np.array([1.0, 0.0]))
    assert len(store1) == 1

    # Initialize a new store instance WITHOUT calling .load()
    store2 = VectorStore(index_path)
    assert store2._loaded is False

    with store2.batch():
        assert store2._loaded is True
        assert len(store2) == 1
        store2.hot_insert("concept_appended", "Appended note", embedding=np.array([0.0, 1.0]))

    reloaded = VectorStore(index_path).load()
    assert len(reloaded) == 2
    assert "concept_initial" in reloaded.sources
    assert "concept_appended" in reloaded.sources


def test_batch_resilience_on_save_error(tmp_path):
    """Test that failed _atomic_save preserves _dirty flag and pending updates for later retry."""
    index_path = tmp_path / "_embedding_index.npz"
    store = VectorStore(index_path)

    with patch.object(store, "_atomic_save", return_value=False):
        with store.batch():
            store.hot_insert("concept_fail", "Content", embedding=np.array([1.0, 0.0]))
        # Save failed on exit: dirty flag and pending updates remain intact
        assert store._dirty is True
        assert "concept_fail" in store._pending_updates

    # Manual retry flush with working _atomic_save
    assert store.flush() is True
    assert store._dirty is False
    assert len(store._pending_updates) == 0

    reloaded = VectorStore(index_path).load()
    assert len(reloaded) == 1
    assert "concept_fail" in reloaded.sources


def test_batch_nested_reentrant(tmp_path):
    """Test that nested batch contexts only flush upon exiting the outermost context."""
    index_path = tmp_path / "_embedding_index.npz"
    store = VectorStore(index_path)

    with patch.object(store, "_atomic_save", wraps=store._atomic_save) as spy_save:
        with store.batch():
            store.hot_insert("c1", "content 1", embedding=np.array([1.0, 0.0]))
            assert store._batch_depth == 1

            with store.batch():
                store.hot_insert("c2", "content 2", embedding=np.array([0.0, 1.0]))
                assert store._batch_depth == 2
                assert spy_save.call_count == 0

            # Exited inner batch: depth is 1, no flush yet
            assert store._batch_depth == 1
            assert spy_save.call_count == 0

        # Exited outer batch: depth is 0, exactly 1 flush
        assert store._batch_depth == 0
        assert spy_save.call_count == 1

    reloaded = VectorStore(index_path).load()
    assert len(reloaded) == 2


def test_hot_insert_auto_save_false(tmp_path):
    """Test hot_insert with auto_save=False marks dirty without immediate disk write."""
    index_path = tmp_path / "_embedding_index.npz"
    store = VectorStore(index_path)

    success = store.hot_insert("c_manual", "manual content", embedding=np.array([1.0, 0.0]), auto_save=False)
    assert success is True
    assert store._dirty is True
    assert not index_path.exists()

    # Explicit flush writes to disk
    assert store.flush() is True
    assert store._dirty is False
    assert index_path.exists()


def test_batch_concurrent_mtime_merge(tmp_path):
    """Test that flush safely merges pending updates when disk was modified concurrently."""
    index_path = tmp_path / "_embedding_index.npz"
    store1 = VectorStore(index_path)
    store1.hot_insert("concept_base", "base", embedding=np.array([1.0, 0.0]))

    with store1.batch():
        store1.hot_insert("concept_from_batch", "batch note", embedding=np.array([0.0, 1.0]))

        # Simulate concurrent process updating disk index during batch
        store2 = VectorStore(index_path)
        store2.load()
        # Ensure mtime will be strictly greater
        import time
        time.sleep(0.01)
        store2.hot_insert("concept_concurrent", "concurrent note", embedding=np.array([0.5, 0.5]))
        assert len(store2) == 2

    # When store1 batch exits, flush notices current_mtime > store1._mtime and merges pending updates
    final_store = VectorStore(index_path).load()
    assert len(final_store) == 3
    assert set(final_store.sources) == {"concept_base", "concept_concurrent", "concept_from_batch"}


def test_batch_guard_in_load_and_get_instance(tmp_path):
    """Test that load() and get_instance() do not reload while batch is active."""
    index_path = tmp_path / "_embedding_index.npz"
    store = VectorStore.get_instance(index_path)
    store.hot_insert("initial", "content", embedding=np.array([1.0, 0.0]))

    with store.batch():
        store.hot_insert("in_batch", "content", embedding=np.array([0.0, 1.0]))
        # Calling load() during batch should be a no-op
        res = store.load()
        assert res is store
        assert len(store) == 2

        # Calling get_instance() during batch should return existing store without reload
        inst = VectorStore.get_instance(index_path)
        assert inst is store
        assert len(inst) == 2


def test_hot_insert_empty_or_invalid_embedding_rejected(tmp_path):
    """Test that empty or 0-length embedding vector is rejected and does not corrupt store."""
    index_path = tmp_path / "_embedding_index.npz"
    store = VectorStore(index_path)

    assert store.hot_insert("c_empty_list", "content", embedding=[]) is False
    assert store.hot_insert("c_empty_arr", "content", embedding=np.empty((0,))) is False
    assert len(store) == 0
    assert store.embeddings.shape == (0, 0)
    assert not store._dirty


def test_hot_insert_dimension_mismatch_protection(tmp_path):
    """Test that embedding dimension mismatch is rejected without corrupting in-memory state."""
    index_path = tmp_path / "_embedding_index.npz"
    store = VectorStore(index_path)
    store.hot_insert("c_base", "base content", embedding=np.array([1.0, 0.0]))
    assert len(store) == 1
    assert store.embeddings.shape == (1, 2)

    # 1. Reject new insert with different dimension
    res = store.hot_insert("c_mismatch", "mismatched content", embedding=np.array([1.0, 0.0, 0.5]))
    assert res is False
    assert len(store) == 1
    assert store.embeddings.shape == (1, 2)
    assert "c_mismatch" not in store.sources

    # 2. Reject update to existing item with different dimension
    res_update = store.hot_insert("c_base", "updated content", embedding=np.array([1.0, 0.0, 0.5]))
    assert res_update is False
    assert len(store) == 1
    assert store.embeddings.shape == (1, 2)
    assert np.allclose(store.embeddings[0], [1.0, 0.0])


def test_batch_flush_sets_loaded_flag(tmp_path):
    """Test that batch flush sets _loaded=True so subsequent operations avoid redundant disk loads."""
    index_path = tmp_path / "_embedding_index.npz"
    store = VectorStore(index_path)
    assert store._loaded is False

    with store.batch():
        store.hot_insert("c1", "content 1", embedding=np.array([1.0, 0.0]))

    assert store._loaded is True
    assert store._dirty is False

    # Next hot_insert should not call load()
    with patch.object(store, "load", wraps=store.load) as spy_load:
        store.hot_insert("c2", "content 2", embedding=np.array([0.0, 1.0]))
        assert spy_load.call_count == 0


def test_flush_concurrent_mtime_backup_recovery(tmp_path):
    """Test flush recovers from backup index if main index is empty or corrupted during concurrent merge."""
    index_path = tmp_path / "_embedding_index.npz"
    bak_path = tmp_path / "_embedding_index.npz.bak"

    # Setup valid backup with base concepts
    store_init = VectorStore(index_path)
    store_init.hot_insert("c_bak_1", "content 1", embedding=np.array([1.0, 0.0]))
    store_init.hot_insert("c_bak_2", "content 2", embedding=np.array([0.0, 1.0]))
    assert bak_path.exists()

    # Corrupt main index file
    index_path.write_text("corrupted content", encoding="utf-8")
    import time
    time.sleep(0.01)

    store = VectorStore(index_path)
    # Set store._mtime older than corrupted file
    store._mtime = 0.0
    with store.batch():
        store.hot_insert("c_from_batch", "batch content", embedding=np.array([0.5, 0.5]))

    final = VectorStore(index_path).load()
    assert "c_from_batch" in final.sources
    assert "c_bak_1" in final.sources
    assert "c_bak_2" in final.sources


def test_atomic_save_creates_parent_directory(tmp_path):
    """Test that _atomic_save automatically creates parent directory if missing."""
    deep_path = tmp_path / "deep" / "nested" / "_embedding_index.npz"
    store = VectorStore(deep_path)
    assert not deep_path.parent.exists()

    success = store.hot_insert("c1", "content", embedding=np.array([1.0, 0.0]))
    assert success is True
    assert deep_path.exists()


def test_vector_store_multiprocess_concurrent_batch_flush(tmp_path):
    """Test concurrent batch flushes from multiple processes write safely without corruption or data loss."""
    import subprocess
    index_file = tmp_path / "concurrent_batch_index.npz"
    worker_script = tmp_path / "batch_worker.py"
    worker_script.write_text("""
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from core.vector_store import VectorStore

prefix = sys.argv[2]
index_path = sys.argv[3]
count = int(sys.argv[4])

store = VectorStore(index_path)
with store.batch():
    for i in range(count):
        store.hot_insert(f"{prefix}_{i}", f"Content {prefix} {i}", embedding=[float(i), 1.0])
print(f"{prefix}:done", flush=True)
""")

    scripts_dir = str(Path(__file__).parent.parent)

    p1 = subprocess.Popen(
        [sys.executable, str(worker_script), scripts_dir, "batch_p1", str(index_file), "5"],
        stdout=subprocess.PIPE,
        text=True,
    )
    p2 = subprocess.Popen(
        [sys.executable, str(worker_script), scripts_dir, "batch_p2", str(index_file), "5"],
        stdout=subprocess.PIPE,
        text=True,
    )
    out1, _ = p1.communicate(timeout=15)
    out2, _ = p2.communicate(timeout=15)

    assert p1.returncode == 0, f"Worker 1 failed: {out1}"
    assert p2.returncode == 0, f"Worker 2 failed: {out2}"

    final_store = VectorStore(index_file).load()
    assert len(final_store) == 10
    for i in range(5):
        assert f"batch_p1_{i}" in final_store.sources
        assert f"batch_p2_{i}" in final_store.sources


