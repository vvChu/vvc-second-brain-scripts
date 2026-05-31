"""VvC Second Brain — Brain Dump Orchestrator Tests (v1.0)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from core.config import cfg
from services.brain_dump.orchestrator import (
    _is_recently_processed,
    _register_processed_hash,
    _is_meaningful_dump,
    handle_brain_dump,
)


@pytest.fixture
def mock_state_file(tmp_path):
    state_file = tmp_path / ".dump_state.json"
    with patch("services.brain_dump.orchestrator._STATE_FILE", state_file):
        yield state_file


def test_is_recently_processed_and_register(mock_state_file):
    content_hash = hashlib.md5(b"test content").hexdigest()
    
    # Initially not processed
    assert _is_recently_processed(content_hash) is False
    
    # Register hash
    _register_processed_hash(content_hash)
    
    # Now it is processed
    assert _is_recently_processed(content_hash) is True


@patch("services.brain_dump.orchestrator.call_llm")
def test_is_meaningful_dump(mock_call):
    # Too short -> False (without calling LLM)
    # Actually "short" has length 5, which is < 2000, so it will call LLM.
    # If LLM returns NO:
    mock_call.return_value = "NO"
    assert _is_meaningful_dump("short") is False
    
    # Very long -> True (without calling LLM)
    long_text = "A" * 2005
    assert _is_meaningful_dump(long_text) is True
    
    # Normal text, LLM says YES -> True
    mock_call.return_value = "YES"
    assert _is_meaningful_dump("This is normal length academic text.") is True


@patch("services.brain_dump.orchestrator._find_pending_dump")
@patch("services.brain_dump.orchestrator._clear_inbox_only")
def test_handle_brain_dump_resurrection(mock_clear, mock_find, mock_state_file, tmp_path):
    dump_file = tmp_path / "Brain_Dump.md"
    dump_file.write_text("Hello pending", encoding="utf-8")
    
    content_hash = hashlib.md5(b"Hello pending").hexdigest()
    
    # Save recently processed state
    mock_state_file.write_text(json.dumps({"processed_hashes": [content_hash]}))
    
    mock_cfg = dataclasses.replace(cfg, dump_file=dump_file)
    mock_find.return_value = "Hello pending"
    
    with patch("services.brain_dump.orchestrator.cfg", mock_cfg):
        handle_brain_dump()
        
    mock_clear.assert_called_once_with("Hello pending")


@patch("services.brain_dump.orchestrator._find_pending_dump")
@patch("services.brain_dump.orchestrator._load_url_registry")
@patch("services.brain_dump.orchestrator._commit_inbox_changes")
@patch("services.brain_dump.orchestrator._register_processed_hash")
def test_handle_brain_dump_deduplication(mock_register, mock_commit, mock_load_registry, mock_find, mock_state_file, tmp_path):
    dump_file = tmp_path / "Brain_Dump.md"
    dump_file.write_text("https://duplicate.com", encoding="utf-8")
    
    mock_cfg = dataclasses.replace(cfg, dump_file=dump_file)
    mock_find.return_value = "https://duplicate.com"
    
    # Mock registry containing this URL
    mock_load_registry.return_value = {
        "duplicate.com": {
            "source_note": "old_transcript",
            "concepts": [{"stem": "concept_1", "title": "Concept One"}]
        }
    }
    
    with patch("services.brain_dump.orchestrator.cfg", mock_cfg):
        handle_brain_dump()
        
    mock_commit.assert_called_once()
    args, kwargs = mock_commit.call_args
    assert args[0] == "https://duplicate.com"
    assert args[1] == ""
    assert any("old_transcript" in item for item in args[2])
    assert any("Concept One" in item for item in args[2])
    mock_register.assert_called_once()


@patch("services.brain_dump.orchestrator._find_pending_dump")
@patch("services.brain_dump.orchestrator._load_url_registry")
@patch("services.brain_dump.orchestrator._process_urls")
@patch("services.brain_dump.orchestrator._is_meaningful_dump")
@patch("services.brain_dump.orchestrator.orthographic_preprocess")
@patch("services.brain_dump.orchestrator._save_transcript")
@patch("services.brain_dump.orchestrator._synthesize_and_save_concepts")
@patch("services.brain_dump.orchestrator._commit_inbox_changes")
@patch("services.brain_dump.orchestrator._save_url_registry")
def test_handle_brain_dump_happy_path(
    mock_save_url_reg, mock_commit, mock_synth, mock_save_transcript,
    mock_preprocess, mock_meaningful, mock_process_urls, mock_load_registry, mock_find, mock_state_file, tmp_path
):
    dump_file = tmp_path / "Brain_Dump.md"
    dump_file.write_text("https://new-url.com and some handwriting text.", encoding="utf-8")
    
    mock_cfg = dataclasses.replace(cfg, dump_file=dump_file)
    mock_find.return_value = "https://new-url.com and some handwriting text."
    mock_load_registry.return_value = {} # Empty registry
    mock_process_urls.return_value = "Scraped web text"
    mock_meaningful.return_value = True
    mock_preprocess.side_effect = lambda x: x
    mock_save_transcript.return_value = "source_stem"
    mock_synth.return_value = [("concept_stem", "Concept Title")]
    
    with patch("services.brain_dump.orchestrator.cfg", mock_cfg):
        handle_brain_dump()
        
    mock_process_urls.assert_called_once()
    mock_save_transcript.assert_called_once_with("Scraped web text", "https://new-url.com")
    mock_synth.assert_called_once_with("https://new-url.com and some handwriting text.", "Scraped web text", "source_stem")
    mock_commit.assert_called_once()
    mock_save_url_reg.assert_called_once()
