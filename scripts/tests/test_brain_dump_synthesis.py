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
    _backlink_source_to_concepts,
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
        "[IMG:yt_123_frame_001_ts100.webp|alt=Sơ đồ Transformer]\n"
        "[IMG:yt_123_frame_002_ts170.webp|alt=Code BERT]\n"
    )
    
    res = _weave_images_into_transcript(transcript, img_markers)
    
    # Check that images are woven at the right spots and raw timestamps are stripped
    assert "[01:30]" not in res
    assert "[02:45]" not in res
    assert "yt_123_frame_001_ts100.webp" in res
    assert "yt_123_frame_002_ts170.webp" in res
    
    # Verify context-aware styling:
    # 1. "Sơ đồ Transformer" -> [!abstract]- 📊 Sơ đồ / Kiến trúc tại 01:40
    assert "> [!abstract]- 📊 Sơ đồ / Kiến trúc tại 01:40 ^ts100" in res
    # 2. "Code BERT" -> [!example]- 💻 Mã nguồn / Thiết lập tại 02:50
    assert "> [!example]- 💻 Mã nguồn / Thiết lập tại 02:50 ^ts170" in res


def test_weave_images_into_transcript_fallback():
    transcript = "Không có mốc thời gian nào ở đây cả."
    img_markers = (
        "## 🎬 Hình ảnh trực quan từ video\n"
        "[IMG:yt_123_frame_001_ts100.webp|alt=Bảng so sánh các mô hình]\n"
    )
    res = _weave_images_into_transcript(transcript, img_markers)
    
    assert "Danh sách Slide HD" in res
    assert "![[yt_123_frame_001_ts100.webp]]" in res
    # Verify fallback catalog style: "Bảng so sánh" -> 📋 Bảng biểu / Đối chiếu
    assert "### 📋 Bảng biểu / Đối chiếu tại 100s ^ts100" in res


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


def test_backlink_source_to_concepts(tmp_path):
    """Backlinks are inserted inside ^ts callout blocks in the Source Note."""
    # Setup: Source Note with ^ts callouts
    transcripts_dir = tmp_path / "sources" / "transcripts"
    transcripts_dir.mkdir(parents=True)
    source_file = transcripts_dir / "my_yt_source.md"
    source_file.write_text(
        "---\ntitle: Test\n---\n\n"
        "Some intro text.\n\n"
        "> [!abstract]- 🖼️ Slide tại 01:40 ^ts100\n"
        "> ![[yt_abc_ts100.webp]]\n\n"
        "Transcript about transformers.\n\n"
        "> [!abstract]- 🖼️ Slide tại 03:20 ^ts200\n"
        "> ![[yt_abc_ts200.webp]]\n\n"
        "Transcript about BERT.\n",
        encoding="utf-8",
    )

    # Setup: Concept file referencing ts100
    concepts_dir = tmp_path / "concepts"
    concepts_dir.mkdir(parents=True)
    concept_file = concepts_dir / "transformer_arch.md"
    concept_file.write_text(
        "---\ntitle: Transformer\n---\n"
        "> \"Evidence Hook\"\n\n"
        "## Core Idea\n![[yt_abc_ts100.webp]]\nAnalysis.\n\n"
        "## References\n- [[my_yt_source]]\n",
        encoding="utf-8",
    )

    mock_cfg = dataclasses.replace(
        cfg,
        sources_dir=tmp_path / "sources",
        concepts_dir=concepts_dir,
    )

    with patch("services.brain_dump.concept_synthesis.cfg", mock_cfg):
        _backlink_source_to_concepts(
            "my_yt_source", [("transformer_arch", "Kiến trúc Transformer")]
        )

    result = source_file.read_text(encoding="utf-8")
    # Backlink should be inside the ^ts100 callout block
    assert "> 📎 [[transformer_arch|Kiến trúc Transformer]]" in result
    # ^ts200 callout should NOT have a backlink (no concept references it)
    ts200_idx = result.index("^ts200")
    after_ts200 = result[ts200_idx:]
    assert "transformer_arch" not in after_ts200


def test_backlink_source_to_concepts_idempotent(tmp_path):
    """Calling backlink twice does not create duplicate entries."""
    transcripts_dir = tmp_path / "sources" / "transcripts"
    transcripts_dir.mkdir(parents=True)
    source_file = transcripts_dir / "my_yt_source.md"
    source_file.write_text(
        "> [!abstract]- 🖼️ Slide tại 01:40 ^ts100\n"
        "> ![[yt_abc_ts100.webp]]\n\n"
        "Transcript text.\n",
        encoding="utf-8",
    )

    concepts_dir = tmp_path / "concepts"
    concepts_dir.mkdir(parents=True)
    (concepts_dir / "my_concept.md").write_text(
        "![[yt_abc_ts100.webp]]\n## References\n- [[my_yt_source]]\n",
        encoding="utf-8",
    )

    mock_cfg = dataclasses.replace(
        cfg,
        sources_dir=tmp_path / "sources",
        concepts_dir=concepts_dir,
    )

    with patch("services.brain_dump.concept_synthesis.cfg", mock_cfg):
        _backlink_source_to_concepts("my_yt_source", [("my_concept", "My Concept")])
        _backlink_source_to_concepts("my_yt_source", [("my_concept", "My Concept")])

    result = source_file.read_text(encoding="utf-8")
    assert result.count("> 📎 [[my_concept|My Concept]]") == 1
