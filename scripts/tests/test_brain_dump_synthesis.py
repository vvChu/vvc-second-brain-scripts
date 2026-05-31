"""VvC Second Brain — Brain Dump Concept Synthesis Tests (v1.0)."""

from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from core.config import cfg
from services.brain_dump.concept_synthesis import (
    _weave_images_into_transcript,
    _save_transcript,
    _enrich_concept_references,
    _synthesize_and_save_concepts,
)


def test_weave_images_into_transcript():
    transcript = (
        "Giới thiệu bài giảng.\n"
        "[01:30] Ở phân đoạn này chúng ta nói về Transformer.\n"
        "Cơ chế self-attention hoạt động song song.\n"
        "[02:45] Đây là phân đoạn về BERT.\n"
    )
    img_markers = (
        "## 🎬 Hình ảnh trực quan từ video\n"
        "[IMG:yt_123_frame_001_ts100.webp|alt=Slide Transformer]\n"
        "[IMG:yt_123_frame_002_ts170.webp|alt=Slide BERT]\n"
    )
    
    res = _weave_images_into_transcript(transcript, img_markers)
    
    # Check that images are woven at the right spots (ts100 -> 1:40 -> placed after [01:30] segment start)
    # [01:30] is 90s. ts100 (100s) is placed at 01:30 newline start or resolved properly
    # Also check that raw timestamps like [01:30] are stripped
    assert "[01:30]" not in res
    assert "[02:45]" not in res
    assert "yt_123_frame_001_ts100.webp" in res
    assert "yt_123_frame_002_ts170.webp" in res


def test_weave_images_into_transcript_fallback():
    transcript = "Không có mốc thời gian nào ở đây cả."
    img_markers = (
        "## 🎬 Hình ảnh trực quan từ video\n"
        "[IMG:yt_123_frame_001_ts100.webp|alt=Slide Transformer]\n"
    )
    res = _weave_images_into_transcript(transcript, img_markers)
    
    assert "## 🖼️ Danh sách Slide HD" in res
    assert "![[yt_123_frame_001_ts100.webp]]" in res


def test_enrich_concept_references():
    concept_text = (
        "---\n"
        "title: Transformer\n"
        "---\n"
        "![[yt_123_frame_001_ts100.webp]]\n"
        "![[yt_123_frame_002_ts200.webp]]\n"
        "## References\n"
        "- [[my_source]]\n"
    )
    
    res = _enrich_concept_references(concept_text, "my_source")
    
    assert "- [[my_source]]" in res
    assert "[[my_source#^ts100|Xem slide và ngữ cảnh chi tiết" in res
    assert "[[my_source#^ts200|Xem slide và ngữ cảnh chi tiết" in res


@patch("services.brain_dump.concept_synthesis.fetch_url_title")
@patch("services.brain_dump.concept_synthesis._extract_related_links")
def test_save_transcript(mock_extract_links, mock_fetch_title, tmp_path):
    mock_fetch_title.return_value = "My Awesome Article"
    mock_extract_links.return_value = ["https://related1.com"]
    
    # Create temp transcript directory
    transcripts_dir = tmp_path / "sources" / "transcripts"
    transcripts_dir.mkdir(parents=True)
    
    mock_cfg = dataclasses.replace(cfg, sources_dir=tmp_path / "sources")
    
    with patch("services.brain_dump.concept_synthesis.cfg", mock_cfg):
        stem = _save_transcript(
            text="Raw body content of my article which is long enough.",
            original_url="https://example.com/article"
        )
        
    assert stem != ""
    # File name should be based on date and slug
    expected_file = transcripts_dir / f"{date.today().isoformat()}_my_awesome_article.md"
    assert expected_file.exists()
    
    content = expected_file.read_text(encoding="utf-8")
    assert "My Awesome Article" in content
    assert "https://related1.com" in content


@patch("services.brain_dump.concept_synthesis.call_llm")
@patch("services.brain_dump.concept_synthesis.save_concept")
def test_synthesize_and_save_concepts(mock_save_concept, mock_call_llm, tmp_path):
    # Mock Map step to return two concepts in JSON
    mock_map_res = """
    [
      {"title": "Concept One", "summary": "Summary of concept one"},
      {"title": "Concept Two", "summary": "Summary of concept two"}
    ]
    """
    
    # Mock Reduce step to return a concept note structure
    mock_reduce_res = """
    ---
    title: "Concept Name"
    ---
    > "Evidence Hook"
    
    ## Core Idea
    Body analysis
    
    ## 📖 Bản gốc & Ngữ cảnh mở rộng (Ground Truth)
    Ground Truth text
    
    ---
    ## References
    - [[my_source]]
    """
    
    mock_call_llm.side_effect = [mock_map_res, mock_reduce_res, mock_reduce_res]
    mock_save_concept.side_effect = [
        Path("/mock/concepts/concept_one.md"),
        Path("/mock/concepts/concept_two.md")
    ]
    
    res = _synthesize_and_save_concepts(
        dump_text="Some dump text with URL https://example.com/article",
        url_content="Some url content",
        source_ref="my_source"
    )
    
    assert len(res) == 2
    assert res[0] == ("concept_one", "Concept One")
    assert res[1] == ("concept_two", "Concept Two")
