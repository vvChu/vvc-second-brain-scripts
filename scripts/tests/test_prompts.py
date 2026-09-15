"""VvC Second Brain — Prompt Registry Tests (v1.0)."""

from __future__ import annotations

import pytest

from core.prompts import pipeline as pl
from core.prompts import services as sv


def test_pipeline_prompts_exist():
    # Verify crucial pipeline prompt constants exist and are non-empty
    assert pl.OCR_EXTRACT
    assert pl.TOC_EXTRACT
    assert pl.TOC_ALIGNMENT
    assert pl.OCR_CORRECTION
    assert pl.BLOCKQUOTE_VERIFY
    assert pl.CONCEPT_SYNTHESIS
    assert pl.TOPIC_SEGMENTATION
    assert pl.BOOK_CONTEXT_ENRICHMENT
    assert pl.MARKDOWN_SYNTHESIS


def test_service_prompts_exist():
    # Verify service prompt constants exist and are non-empty
    assert sv.BRAIN_DUMP_MAP
    assert sv.BRAIN_DUMP_REDUCE
    assert sv.COMMAND_RESPONSE
    assert sv.MERMAID_GENERATE
    assert sv.EXCALIDRAW_GENERATE
    assert sv.EA_SCRIPT_GENERATE
    assert sv.D2_GENERATE
    assert sv.LEGAL_CONCEPT
    assert sv.QC_MATRIX
    assert sv.DIAGRAM_CLASSIFY
    assert sv.LARGE_DOC_MAP
    assert sv.LARGE_DOC_REDUCE


def test_pipeline_prompts_placeholders():
    # Test that format strings contain expected placeholders
    
    # OCR_CORRECTION
    assert "{ocr_text}" in pl.OCR_CORRECTION
    assert "{ground_truth}" in pl.OCR_CORRECTION
    
    # BLOCKQUOTE_VERIFY
    assert "{blockquote}" in pl.BLOCKQUOTE_VERIFY
    assert "{ground_truth}" in pl.BLOCKQUOTE_VERIFY
    
    # CONCEPT_SYNTHESIS
    assert "{book_macro_context}" in pl.CONCEPT_SYNTHESIS
    assert "{highlighted}" in pl.CONCEPT_SYNTHESIS
    assert "{context}" in pl.CONCEPT_SYNTHESIS
    assert "{ground_truth}" in pl.CONCEPT_SYNTHESIS
    assert "{source_name}" in pl.CONCEPT_SYNTHESIS
    assert "{chapter}" in pl.CONCEPT_SYNTHESIS
    assert "{page}" in pl.CONCEPT_SYNTHESIS
    assert "{today}" in pl.CONCEPT_SYNTHESIS
    assert "{source_ref}" in pl.CONCEPT_SYNTHESIS
    assert "{chapter_ref}" in pl.CONCEPT_SYNTHESIS
    
    # TOPIC_SEGMENTATION
    assert "{book_macro_context}" in pl.TOPIC_SEGMENTATION
    assert "{book_name}" in pl.TOPIC_SEGMENTATION
    assert "{formatted_ocr}" in pl.TOPIC_SEGMENTATION
    
    # BOOK_CONTEXT_ENRICHMENT
    assert "{book_name}" in pl.BOOK_CONTEXT_ENRICHMENT
    assert "{current_context}" in pl.BOOK_CONTEXT_ENRICHMENT
    assert "{toc_json}" in pl.BOOK_CONTEXT_ENRICHMENT
    
    # MARKDOWN_SYNTHESIS
    assert "{content}" in pl.MARKDOWN_SYNTHESIS
    assert "{today}" in pl.MARKDOWN_SYNTHESIS
    assert "{source_name}" in pl.MARKDOWN_SYNTHESIS


def test_service_prompts_placeholders():
    # Test that service format strings contain expected placeholders
    
    # BRAIN_DUMP_MAP
    assert "{dump_text}" in sv.BRAIN_DUMP_MAP
    assert "{url_content}" in sv.BRAIN_DUMP_MAP
    assert "{min_concepts}" in sv.BRAIN_DUMP_MAP
    assert "{max_concepts}" in sv.BRAIN_DUMP_MAP
    
    # BRAIN_DUMP_REDUCE
    assert "{today}" in sv.BRAIN_DUMP_REDUCE
    assert "{concept_title}" in sv.BRAIN_DUMP_REDUCE
    assert "{concept_summary}" in sv.BRAIN_DUMP_REDUCE
    assert "{dump_text}" in sv.BRAIN_DUMP_REDUCE
    assert "{url_content}" in sv.BRAIN_DUMP_REDUCE
    assert "{source_ref}" in sv.BRAIN_DUMP_REDUCE
    
    # COMMAND_RESPONSE
    assert "{style_instruction}" in sv.COMMAND_RESPONSE
    assert "{rag_context}" in sv.COMMAND_RESPONSE
    assert "{query}" in sv.COMMAND_RESPONSE
    
    # MERMAID_GENERATE
    assert "{context}" in sv.MERMAID_GENERATE
    
    # EXCALIDRAW_GENERATE
    assert "{context}" in sv.EXCALIDRAW_GENERATE

    # EA_SCRIPT_GENERATE
    assert "{context}" in sv.EA_SCRIPT_GENERATE

    # D2_GENERATE
    assert "{context}" in sv.D2_GENERATE

    # LEGAL_CONCEPT
    assert "{registry_data}" in sv.LEGAL_CONCEPT
    assert "{date}" in sv.LEGAL_CONCEPT

    # LARGE_DOC_MAP
    assert "{idx}" in sv.LARGE_DOC_MAP
    assert "{total_chunks}" in sv.LARGE_DOC_MAP
    assert "{chunk}" in sv.LARGE_DOC_MAP

    # LARGE_DOC_REDUCE
    assert "{total_chars:,}" in sv.LARGE_DOC_REDUCE
    assert "{total_chunks}" in sv.LARGE_DOC_REDUCE
    assert "{combined_notes}" in sv.LARGE_DOC_REDUCE


def test_command_response_invariants():
    assert "ZERO-ASCII INVARIANT" in sv.COMMAND_RESPONSE
    assert "NATIVE FENCED BLOCKS" in sv.COMMAND_RESPONSE
    assert "\\|" in sv.COMMAND_RESPONSE
    assert "HYBRID GOLDEN THRESHOLD" in sv.COMMAND_RESPONSE
    assert "THE 5 MERMAID INVARIANTS" in sv.COMMAND_RESPONSE
    assert "EXECUTIVE TYPOGRAPHY 16:9" in sv.COMMAND_RESPONSE
    assert "FLAT TWO-NODE INVARIANT" in sv.COMMAND_RESPONSE
    assert "ARROW-LABEL CLEARANCE" in sv.COMMAND_RESPONSE
    assert "TWO-TRACK DOCUMENT ERGONOMICS" in sv.COMMAND_RESPONSE
    assert "CLEAN CALLOUT HEADER INVARIANT" in sv.COMMAND_RESPONSE
    assert "TARGET LANGUAGE SYNTAX ALIGNMENT" in sv.COMMAND_RESPONSE
    assert "MINIMAL BANNER INVARIANT" in sv.COMMAND_RESPONSE
    assert "CẤM BỌC DẤU BACKTICK" in sv.COMMAND_RESPONSE
    assert "`[[file|[id]]]`" not in sv.COMMAND_RESPONSE
    assert "⚙️" not in sv.COMMAND_RESPONSE
    assert "📋" not in sv.COMMAND_RESPONSE
    # Diagram prompt tests
    assert "FLAT TWO-NODE & SUBGRAPH INVARIANT" in sv.MERMAID_GENERATE
    assert "EXECUTIVE TYPOGRAPHY 16:9 & ARROW CLEARANCE" in sv.EXCALIDRAW_GENERATE


def test_pipeline_prompts_invariants():
    assert "TUYỆT ĐỐI KHÔNG bọc ngoài wikilink bằng dấu backtick" in pl.CONCEPT_SYNTHESIS
    assert "TUYỆT ĐỐI KHÔNG bọc ngoài wikilink bằng dấu backtick" in pl.MARKDOWN_SYNTHESIS
    assert "`[[slug" not in pl.CONCEPT_SYNTHESIS
    assert "`[[source" not in pl.MARKDOWN_SYNTHESIS


def test_scan_wikilink_code_pills(tmp_path):
    from services.wiki_health import scan_wikilink_code_pills

    fake_concept_dir = tmp_path / "concepts"
    fake_concept_dir.mkdir(parents=True)
    test_file = fake_concept_dir / "test_note.md"
    test_file.write_text("This has a `[[some_concept|[1]]]` and regular [[other_concept]].\n", encoding="utf-8")

    findings = scan_wikilink_code_pills(fix=False, target_dirs=[fake_concept_dir])
    assert len(findings) == 1
    assert findings[0]["count"] == 1
    assert findings[0]["matches"] == ["[[some_concept|[1]]]"]

    # Now run with fix=True
    scan_wikilink_code_pills(fix=True, target_dirs=[fake_concept_dir])
    fixed_content = test_file.read_text(encoding="utf-8")
    assert "`[[some_concept|[1]]]`" not in fixed_content
    assert "[[some_concept|[1]]]" in fixed_content


