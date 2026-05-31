"""VvC Second Brain — Shared Pipeline Types Tests (v1.0)."""

from __future__ import annotations

from pathlib import Path
import pytest

from core.types import PageData, PipelineContext
from pipeline.ocr import OcrResult


def test_page_data_init():
    p = Path("/mock/image.jpg")
    pd = PageData(image_path=p, highlighted="text", context="ctx", page_number=42)
    
    assert pd.image_path == p
    assert pd.highlighted == "text"
    assert pd.context == "ctx"
    assert pd.page_number == 42


def test_page_data_defaults():
    p = Path("/mock/image.jpg")
    pd = PageData(image_path=p)
    
    assert pd.image_path == p
    assert pd.highlighted == ""
    assert pd.context == ""
    assert pd.page_number is None


def test_page_data_from_ocr():
    p = Path("/mock/image.jpg")
    ocr = OcrResult(
        raw_text="PAGE: 42\n[HIGHLIGHTED]\ntext\n[CONTEXT]\nctx",
        highlighted="text",
        context="ctx",
        page_number=42,
        is_toc=False
    )
    pd = PageData.from_ocr(p, ocr)
    
    assert pd.image_path == p
    assert pd.highlighted == "text"
    assert pd.context == "ctx"
    assert pd.page_number == 42


def test_page_data_to_dict():
    p = Path("/mock/image.jpg")
    pd = PageData(image_path=p, highlighted="text", context="ctx", page_number=42)
    d = pd.to_dict()
    
    assert d == {
        "image_path": p,
        "highlighted": "text",
        "context": "ctx",
        "page_number": 42
    }


def test_pipeline_context_init():
    p = Path("/mock/workspace")
    ctx = PipelineContext(
        book_name="test_book",
        workspace_dir=p,
        source_ref="[[test_book]]"
    )
    
    assert ctx.book_name == "test_book"
    assert ctx.workspace_dir == p
    assert ctx.source_ref == "[[test_book]]"
    assert ctx.pages == []
    assert ctx.extra == {}


def test_pipeline_context_with_pages():
    p = Path("/mock/image.jpg")
    pd = PageData(image_path=p)
    ctx = PipelineContext(pages=[pd], extra={"key": "val"})
    
    assert len(ctx.pages) == 1
    assert ctx.pages[0].image_path == p
    assert ctx.extra == {"key": "val"}
