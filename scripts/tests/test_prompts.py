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
    assert sv.LEGAL_CONCEPT
    assert sv.QC_MATRIX
    assert sv.DIAGRAM_CLASSIFY


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

    # LEGAL_CONCEPT
    assert "{registry_data}" in sv.LEGAL_CONCEPT
    assert "{date}" in sv.LEGAL_CONCEPT
