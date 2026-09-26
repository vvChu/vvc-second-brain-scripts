"""Tests for proactive modular decomposition (Issue #20).

Verifies interface parity and direct unit behavior of decomposed modules:
- services/youtube/transcript_cleaner.py
- tools/video_heal_extractor.py
- pipeline/book_staging.py
- pipeline/batch_helpers.py
- pipeline/book_diagram_enricher.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add scripts root to sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from core.types import PageData


def test_transcript_cleaner_direct_and_parity():
    """Verify transcript_cleaner routines and re-export parity in transcript.py."""
    import services.youtube.transcript as transcript_mod
    import services.youtube.transcript_cleaner as cleaner_mod

    # Parity checks
    for sym in [
        "_is_machine_translated",
        "_find_lang",
        "_find_native_asr",
        "_select_subtitle_stream",
        "_find_target_sub_url",
        "_group_timed_segments",
        "_parse_json3_subtitles",
        "_parse_fallback_text",
        "_extract_video_id",
    ]:
        assert hasattr(cleaner_mod, sym), f"cleaner_mod missing {sym}"
        assert getattr(transcript_mod, sym) is getattr(cleaner_mod, sym), f"Parity mismatch for {sym}"

    # Behavioral checks
    assert cleaner_mod._extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert cleaner_mod._extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert cleaner_mod._is_machine_translated([{"url": "https://yt.com/sub?tlang=vi"}]) is True
    assert cleaner_mod._is_machine_translated([{"url": "https://yt.com/sub?lang=en"}]) is False


def test_video_heal_extractor_parity():
    """Verify video_heal_extractor routines and re-export parity in heal_video_frames.py."""
    import tools.heal_video_frames as heal_mod
    import tools.video_heal_extractor as extractor_mod

    for sym in [
        "_run_ffmpeg",
        "extract_frame_via_stream",
        "extract_frame_from_local_video",
        "save_as_webp",
        "download_local_video",
        "_get_video_stream",
        "_process_pending_with_download",
        "heal_video_id_frames",
    ]:
        assert hasattr(extractor_mod, sym), f"extractor_mod missing {sym}"
        assert getattr(heal_mod, sym) is getattr(extractor_mod, sym), f"Parity mismatch for {sym}"


def test_book_staging_direct_and_parity(tmp_path):
    """Verify book_staging routines and re-export parity in book_ingest.py."""
    import book_ingest as ingest_mod
    import pipeline.book_staging as staging_mod

    for sym in [
        "_normalize_book_name",
        "_create_workspace",
        "_create_source_note",
        "_convert_epub",
        "_convert_book_corpus",
        "_sync_toc_and_macro_context",
    ]:
        assert hasattr(staging_mod, sym), f"staging_mod missing {sym}"
        assert getattr(ingest_mod, sym) is getattr(staging_mod, sym), f"Parity mismatch for {sym}"

    assert staging_mod._normalize_book_name("Tư Duy Sâu - Deep Thinking.epub") == "Tư_Duy_Sâu_Deep_Thinking"


def test_batch_helpers_direct_and_parity():
    """Verify batch_helpers routines and re-export parity in batch_processor.py."""
    import pipeline.batch_helpers as helpers_mod
    import pipeline.batch_processor as proc_mod

    for sym in [
        "_clean_blockquote_quote",
        "_interpolate_page_numbers",
        "_get_diagrams_helper",
        "_interpolate_helper",
        "_trigger_moc_helper",
        "_build_hook_exclusion_directive",
        "_resolve_concept_pages",
        "_cleanup_batch_images",
    ]:
        assert hasattr(helpers_mod, sym), f"helpers_mod missing {sym}"
        assert getattr(proc_mod, sym) is getattr(helpers_mod, sym), f"Parity mismatch for {sym}"

    # Test interpolation
    pages = [
        PageData(image_path=Path("p1.webp"), page_number=None, highlighted="h1", context="c1"),
        PageData(image_path=Path("p2.webp"), page_number=20, highlighted="h2", context="c2"),
        PageData(image_path=Path("p3.webp"), page_number=None, highlighted="h3", context="c3"),
    ]
    helpers_mod._interpolate_page_numbers(pages)
    assert pages[0].page_number == 19
    assert pages[1].page_number == 20
    assert pages[2].page_number == 21


def test_book_diagram_enricher_direct_and_parity():
    """Verify book_diagram_enricher routines and re-export parity in book_assets.py."""
    import pipeline.book_assets as assets_mod
    import pipeline.book_diagram_enricher as enricher_mod

    for sym in [
        "build_chapter_diagrams_catalog",
        "FIGURE_ENRICH_PROMPT",
        "_load_figure_inventory",
        "_resolve_vision_caller",
        "_save_figure_inventory",
        "_parse_json_block",
        "_format_diagram_xml",
        "_enrich_diagram_metadata",
    ]:
        assert hasattr(enricher_mod, sym), f"enricher_mod missing {sym}"
        assert getattr(assets_mod, sym) is getattr(enricher_mod, sym), f"Parity mismatch for {sym}"

    # Test JSON parser
    json_text = '```json\n{"caption": "Cap", "alt_text": "Alt"}\n```'
    parsed = enricher_mod._parse_json_block(json_text)
    assert parsed == {"caption": "Cap", "alt_text": "Alt"}

    # Test XML formatting
    xml_lines = enricher_mod._format_diagram_xml("fig.png", "fig.webp", "Cap", "Alt")
    assert "<FILENAME>fig.png</FILENAME>" in xml_lines[1]
    assert "<ADAPTIVE_NAME>fig.webp</ADAPTIVE_NAME>" in xml_lines[2]
