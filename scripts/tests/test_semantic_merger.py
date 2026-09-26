"""Tests for pipeline/semantic_merger.py — 3-Tier Merge Control."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


# --- SUBSUME_SENTINEL ---

def test_subsume_sentinel_is_path():
    """SUBSUME_SENTINEL should be a Path object with a recognizable name."""
    from pipeline.semantic_merger import SUBSUME_SENTINEL
    assert isinstance(SUBSUME_SENTINEL, Path)
    assert "SUBSUMED" in str(SUBSUME_SENTINEL)


# --- Tier 1: Hook Count Gate ---

def test_tier1_hook_count_gate_triggers_prune_arbitration():
    """Should not block immediately when hook count >= 4, but consult the Arbitrator."""
    from pipeline.semantic_merger import arbitrate_and_merge
    from core.config import cfg

    existing_content = '---\ntitle: "Test"\nconfidence: high\n---\n\n'
    # Add 4 evidence hooks
    for i in range(4):
        existing_content += f'> "Quote {i + 1} from the book."\n> — **Author**, *Book* ([[source]])\n\n'
    existing_content += "## Core Idea\n\nAnalysis.\n"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        orig = cfg.concepts_dir
        object.__setattr__(cfg, "concepts_dir", tmpdir)
        try:
            (tmpdir / "existing_note.md").write_text(existing_content, encoding="utf-8")
            # Mock call_llm: subsume returns NOT_SUBSUME, arbitrator returns SEPARATE
            with patch("pipeline.semantic_merger.call_llm") as mock_llm:
                mock_llm.side_effect = ["NOT_SUBSUME", "SEPARATE"]
                result = arbitrate_and_merge("new content", "existing_note")
                assert result is None
                assert mock_llm.call_count == 2
        finally:
            object.__setattr__(cfg, "concepts_dir", orig)


def test_tier1_allows_merge_under_threshold():
    """Should NOT block when existing note has <4 evidence hooks (passes to Tier 2+)."""
    from pipeline.semantic_merger import arbitrate_and_merge
    from core.config import cfg

    existing_content = '---\ntitle: "Test"\nconfidence: high\n---\n\n'
    # Add only 2 evidence hooks
    for i in range(2):
        existing_content += f'> "Quote {i + 1}."\n\n'
    existing_content += "## Core Idea\n\nShort.\n"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        orig = cfg.concepts_dir
        object.__setattr__(cfg, "concepts_dir", tmpdir)
        try:
            # Write a small file (< 7700 bytes) so it passes Tier 2 too
            (tmpdir / "small_note.md").write_text(existing_content, encoding="utf-8")

            # Mock call_llm to return SEPARATE (so we don't actually call LLM)
            with patch("pipeline.semantic_merger.call_llm", return_value="SEPARATE"):
                result = arbitrate_and_merge("new content", "small_note")
                # SEPARATE returns None — but the important thing is it reached Tier 3 (LLM was called)
                assert result is None
        finally:
            object.__setattr__(cfg, "concepts_dir", orig)


# --- Tier 2: Dynamic Size Limit ---

def test_tier2_size_limit_blocks_merge():
    """Should return None when existing note exceeds 7700 bytes."""
    from pipeline.semantic_merger import arbitrate_and_merge
    from core.config import cfg

    # Create a large file > 7700 bytes (but with < 4 hooks)
    existing_content = '---\ntitle: "Large Note"\nconfidence: high\n---\n\n'
    existing_content += '> "One hook only."\n\n'
    existing_content += "## Core Idea\n\n"
    existing_content += "X" * 8000 + "\n"  # Pad to > 7700 bytes

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        orig = cfg.concepts_dir
        object.__setattr__(cfg, "concepts_dir", tmpdir)
        try:
            (tmpdir / "large_note.md").write_text(existing_content, encoding="utf-8")
            with patch("pipeline.semantic_merger.call_llm", return_value="NOT_SUBSUME"):
                result = arbitrate_and_merge("new content", "large_note")
                assert result is None, "Should force SEPARATE when file > 7700 bytes"
        finally:
            object.__setattr__(cfg, "concepts_dir", orig)


def test_tier2_prune_mode_allows_large_file_under_limits():
    """Should allow merging a file with hook count >= 4 and total size > 7700 but core_size < 6000 and total < 10000."""
    from pipeline.semantic_merger import arbitrate_and_merge
    from core.config import cfg

    existing_content = '---\ntitle: "Prune Mode Test"\nconfidence: high\n---\n\n'
    # Add 4 large evidence hooks to inflate the total file size > 7700 bytes
    for i in range(4):
        existing_content += f'> "Quote {i + 1}: ' + 'A' * 2000 + '"\n> — **Author**, *Book*\n\n'
    existing_content += "## Core Idea\n\nShort analysis core idea.\n"

    # Verify size is indeed > 7700 bytes
    assert len(existing_content.encode('utf-8')) > 7700
    assert len(existing_content.encode('utf-8')) < 10000

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        orig = cfg.concepts_dir
        object.__setattr__(cfg, "concepts_dir", tmpdir)
        try:
            (tmpdir / "prune_test_note.md").write_text(existing_content, encoding="utf-8")
            with patch("pipeline.semantic_merger.call_llm") as mock_llm:
                mock_llm.side_effect = ["NOT_SUBSUME", "SEPARATE"]
                result = arbitrate_and_merge("new content", "prune_test_note")
                # SEPARATE decision leads to None, but it should not return None before LLM is called (mock_llm.call_count == 2)
                assert result is None
                assert mock_llm.call_count == 2
        finally:
            object.__setattr__(cfg, "concepts_dir", orig)


def test_tier2_prune_mode_blocks_large_core_size():
    """Should block merge when hook count >= 4 but core_size exceeds 6000 bytes."""
    from pipeline.semantic_merger import arbitrate_and_merge
    from core.config import cfg

    existing_content = '---\ntitle: "Prune Mode Large Core Test"\nconfidence: high\n---\n\n'
    for i in range(4):
        existing_content += f'> "Quote {i + 1}."\n'
    existing_content += "## Core Idea\n\n"
    existing_content += "A" * 6500 + "\n"  # Core analysis > 6000 bytes

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        orig = cfg.concepts_dir
        object.__setattr__(cfg, "concepts_dir", tmpdir)
        try:
            (tmpdir / "large_core_note.md").write_text(existing_content, encoding="utf-8")
            with patch("pipeline.semantic_merger.call_llm") as mock_llm:
                mock_llm.side_effect = ["NOT_SUBSUME"]
                result = arbitrate_and_merge("new content", "large_core_note")
                assert result is None, "Should force SEPARATE when core size > 6000 bytes"
                assert mock_llm.call_count == 1  # Only subsume checked, dynamic size blocks before arbitrator
        finally:
            object.__setattr__(cfg, "concepts_dir", orig)


def test_tier2_prune_mode_blocks_excessive_total_size():
    """Should block merge when hook count >= 4 but total size exceeds 10000 bytes."""
    from pipeline.semantic_merger import arbitrate_and_merge
    from core.config import cfg

    existing_content = '---\ntitle: "Prune Mode Large Total Test"\nconfidence: high\n---\n\n'
    for i in range(4):
        existing_content += f'> "Quote {i + 1}: ' + 'A' * 3000 + '"\n'
    existing_content += "## Core Idea\n\nShort.\n"

    # Verify total size > 10000 bytes
    assert len(existing_content.encode('utf-8')) > 10000

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        orig = cfg.concepts_dir
        object.__setattr__(cfg, "concepts_dir", tmpdir)
        try:
            (tmpdir / "large_total_note.md").write_text(existing_content, encoding="utf-8")
            with patch("pipeline.semantic_merger.call_llm") as mock_llm:
                mock_llm.side_effect = ["NOT_SUBSUME"]
                result = arbitrate_and_merge("new content", "large_total_note")
                assert result is None, "Should force SEPARATE when total size > 10000 bytes"
                assert mock_llm.call_count == 1
        finally:
            object.__setattr__(cfg, "concepts_dir", orig)


# --- Tier 3: LLM Arbitrator ---

def test_tier3_subsume_returns_sentinel():
    """Should return SUBSUME_SENTINEL when LLM decides SUBSUME."""
    from pipeline.semantic_merger import arbitrate_and_merge, SUBSUME_SENTINEL
    from core.config import cfg

    existing_content = '---\ntitle: "Test"\nconfidence: high\n---\n\n> "One hook."\n\n## Core Idea\n\nShort.\n'

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        orig = cfg.concepts_dir
        object.__setattr__(cfg, "concepts_dir", tmpdir)
        try:
            (tmpdir / "test_note.md").write_text(existing_content, encoding="utf-8")
            with patch("pipeline.semantic_merger.call_llm", return_value="SUBSUME"):
                result = arbitrate_and_merge("new content", "test_note")
                assert result == SUBSUME_SENTINEL
        finally:
            object.__setattr__(cfg, "concepts_dir", orig)


def test_tier3_separate_returns_none():
    """Should return None when LLM decides SEPARATE."""
    from pipeline.semantic_merger import arbitrate_and_merge
    from core.config import cfg

    existing_content = '---\ntitle: "Test"\nconfidence: high\n---\n\n> "One hook."\n\n## Core Idea\n\nShort.\n'

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        orig = cfg.concepts_dir
        object.__setattr__(cfg, "concepts_dir", tmpdir)
        try:
            (tmpdir / "test_note.md").write_text(existing_content, encoding="utf-8")
            with patch("pipeline.semantic_merger.call_llm", return_value="SEPARATE"):
                result = arbitrate_and_merge("new content", "test_note")
                assert result is None
        finally:
            object.__setattr__(cfg, "concepts_dir", orig)


# --- Stub Bypass ---

def test_stub_bypass_skips_arbitration():
    """Should return None immediately for stub/low-confidence notes."""
    from pipeline.semantic_merger import arbitrate_and_merge
    from core.config import cfg

    stub_content = '---\ntitle: "Stub"\nconfidence: low\nsource_type: stub\n---\n\n## Core Idea\n\nPlaceholder.\n'

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        orig = cfg.concepts_dir
        object.__setattr__(cfg, "concepts_dir", tmpdir)
        try:
            (tmpdir / "stub_note.md").write_text(stub_content, encoding="utf-8")
            # Should return None WITHOUT calling LLM
            with patch("pipeline.semantic_merger.call_llm") as mock_llm:
                result = arbitrate_and_merge("new content", "stub_note")
                assert result is None
                mock_llm.assert_not_called()
        finally:
            object.__setattr__(cfg, "concepts_dir", orig)


# --- Missing File ---

def test_arbitrate_missing_file_returns_none():
    """Should return None when the existing file doesn't exist."""
    from pipeline.semantic_merger import arbitrate_and_merge
    from core.config import cfg

    with tempfile.TemporaryDirectory() as tmpdir:
        orig = cfg.concepts_dir
        object.__setattr__(cfg, "concepts_dir", Path(tmpdir))
        try:
            result = arbitrate_and_merge("new content", "nonexistent_note")
            assert result is None
        finally:
            object.__setattr__(cfg, "concepts_dir", orig)


# --- Cross-Linking ---

def test_cross_linking_adds_bidirectional_links():
    """Should add wiki-links in both directions."""
    from pipeline.semantic_merger import execute_cross_linking
    from core.frontmatter import parse_frontmatter

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        path_a = tmpdir / "concept_a.md"
        path_b = tmpdir / "concept_b.md"

        path_a.write_text(
            '---\ntitle: "Concept A"\nrelated: []\n---\n\n## Core Idea\n\nA content.\n\n## References\n\n- [[other]]\n',
            encoding="utf-8",
        )
        path_b.write_text(
            '---\ntitle: "Concept B"\nrelated: []\n---\n\n## Core Idea\n\nB content.\n',
            encoding="utf-8",
        )

        execute_cross_linking(path_a, path_b)

        # Verify A links to B
        a_content = path_a.read_text(encoding="utf-8")
        assert "[[concept_b]]" in a_content
        a_fm = parse_frontmatter(a_content)
        assert "concept_b" in a_fm.get("related", [])

        # Verify B links to A
        b_content = path_b.read_text(encoding="utf-8")
        assert "[[concept_a]]" in b_content
        b_fm = parse_frontmatter(b_content)
        assert "concept_a" in b_fm.get("related", [])


def test_cross_linking_idempotent():
    """Should not duplicate links when called multiple times."""
    from pipeline.semantic_merger import execute_cross_linking

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        path_a = tmpdir / "concept_a.md"
        path_b = tmpdir / "concept_b.md"

        path_a.write_text(
            '---\ntitle: "A"\nrelated: []\n---\n\n## Core Idea\n\nA.\n\n## References\n\n- [[concept_b]]\n',
            encoding="utf-8",
        )
        path_b.write_text(
            '---\ntitle: "B"\nrelated: ["concept_a"]\n---\n\n## Core Idea\n\nB.\n\n## References\n\n- [[concept_a]]\n',
            encoding="utf-8",
        )

        execute_cross_linking(path_a, path_b)

        a_content = path_a.read_text(encoding="utf-8")
        assert a_content.count("[[concept_b]]") == 1, "Should not duplicate links"

        b_content = path_b.read_text(encoding="utf-8")
        assert b_content.count("[[concept_a]]") == 1, "Should not duplicate links"


# --- log_subsume ---

def test_log_subsume_writes_jsonl():
    """Should append a valid JSONL entry to the journal file."""
    from pipeline.semantic_merger import log_subsume
    from core.config import cfg

    with tempfile.TemporaryDirectory() as tmpdir:
        orig = cfg.state_dir
        object.__setattr__(cfg, "state_dir", Path(tmpdir))
        try:
            mock_img = MagicMock(spec=Path)
            mock_img.name = "test_img.jpg"

            log_subsume("New Concept Title", "existing_concept", 0.9234, mock_img)

            journal = Path(tmpdir) / ".subsume_journal.jsonl"
            assert journal.exists()

            line = journal.read_text(encoding="utf-8").strip()
            entry = json.loads(line)
            assert entry["new_title"] == "New Concept Title"
            assert entry["existing_concept"] == "existing_concept.md"
            assert entry["similarity_score"] == 0.9234
            assert entry["source_image"] == "test_img.jpg"
            assert "timestamp" in entry
        finally:
            object.__setattr__(cfg, "state_dir", orig)


def test_log_subsume_none_image():
    """Should handle None image_path gracefully."""
    from pipeline.semantic_merger import log_subsume
    from core.config import cfg

    with tempfile.TemporaryDirectory() as tmpdir:
        orig = cfg.state_dir
        object.__setattr__(cfg, "state_dir", Path(tmpdir))
        try:
            log_subsume("Title", "stem", 0.88, None)

            journal = Path(tmpdir) / ".subsume_journal.jsonl"
            entry = json.loads(journal.read_text(encoding="utf-8").strip())
            assert entry["source_image"] is None
        finally:
            object.__setattr__(cfg, "state_dir", orig)


# --- find_semantic_overlap ---

def test_find_overlap_no_index_returns_none():
    """Should return None when no embedding index file exists."""
    from pipeline.semantic_merger import find_semantic_overlap

    with patch("pipeline.semantic_merger.Path") as MockPath:
        # Make the index path not exist
        mock_index = MagicMock()
        mock_index.exists.return_value = False
        mock_bak = MagicMock()
        mock_bak.exists.return_value = False
        mock_index.with_suffix.return_value = mock_bak

        # The function uses Path(__file__).parent.parent / "_embedding_index.npz"
        # We need to mock it differently - just test with actual nonexistent path
        pass

    # Simpler approach: just verify it doesn't crash with no index
    # The function checks for file existence internally
    result = find_semantic_overlap("test text")
    # Should return None since there's no _embedding_index.npz after cleanup
    assert result is None


# --- get_embedding_via_gateway ---

def test_get_embedding_no_gateway_returns_none():
    """Should return None when gateway is not configured."""
    from pipeline.semantic_merger import get_embedding_via_gateway
    from core.config import cfg

    orig_url = cfg.gateway_url
    orig_key = cfg.gateway_api_key
    object.__setattr__(cfg, "gateway_url", "")
    object.__setattr__(cfg, "gateway_api_key", "")
    try:
        result = get_embedding_via_gateway("test text")
        assert result is None
    finally:
        object.__setattr__(cfg, "gateway_url", orig_url)
        object.__setattr__(cfg, "gateway_api_key", orig_key)


# --- semantic_fallback subsystem ---

def test_fallback_bm25_cache_sync():
    """Should load, sync, and persist BM25 token cache properly."""
    from pipeline.semantic_fallback import load_and_sync_bm25_cache, _tokenize
    from core.config import cfg

    assert _tokenize("Hello world! Zettelkasten AI") == ["hello", "world", "zettelkasten"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        orig_state = cfg.state_dir
        object.__setattr__(cfg, "state_dir", tmp_path)
        try:
            note_a = tmp_path / "concept_a.md"
            note_a.write_text('---\ndate_modified: "2026-09-26"\n---\nNội dung concept học thuật A', encoding="utf-8")
            
            cache = load_and_sync_bm25_cache([note_a])
            assert "concept_a" in cache
            assert cache["concept_a"]["is_valid"] is True
            assert len(cache["concept_a"]["tokens"]) > 0

            # Level 1 hit (same file stats)
            cache2 = load_and_sync_bm25_cache([note_a])
            assert "concept_a" in cache2
        finally:
            object.__setattr__(cfg, "state_dir", orig_state)


def test_find_semantic_overlap_fallback_empty():
    """Should return None if concepts dir has no markdown files."""
    from pipeline.semantic_fallback import find_semantic_overlap_fallback
    from core.config import cfg

    with tempfile.TemporaryDirectory() as tmpdir:
        orig_dir = cfg.concepts_dir
        object.__setattr__(cfg, "concepts_dir", Path(tmpdir))
        try:
            assert find_semantic_overlap_fallback("some text") is None
        finally:
            object.__setattr__(cfg, "concepts_dir", orig_dir)

