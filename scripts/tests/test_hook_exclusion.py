"""Unit tests for sequential Hook Overlap Prevention in Map-Reduce batch processing."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.image_processor import _clean_blockquote_quote, process_image_batch
from core.types import PageData


def test_clean_blockquote_quote():
    """Should correctly clean blockquotes, removing markdown syntax, citations, and outer quotes."""
    # Standard blockquote with straight double quotes
    bq1 = (
        '> "Nói một cách đơn giản, năng lực liên quan đến cái đầu (có khả năng), '
        'sự cam kết liên quan đến tay chân (có mặt ở đó) và sự đóng góp liên quan đến trái tim."\n'
        '> — **Dave Ulrich**, trích dẫn trong sách *Reinventing the Organization* '
        '([[2026-05-12_reinventing_the_organization_h_arthur_yeung|Tái tạo tổ chức, 2026]])'
    )
    cleaned1 = _clean_blockquote_quote(bq1)
    assert cleaned1 == (
        "Nói một cách đơn giản, năng lực liên quan đến cái đầu (có khả năng), "
        "sự cam kết liên quan đến tay chân (có mặt ở đó) và sự đóng góp liên quan đến trái tim."
    )

    # Blockquote with curly double quotes and no citation
    bq2 = (
        '> “Các đường ống ý tưởng và đường ống tài năng cần phải hợp tác với nhau, '
        'như đã chứng kiến trong các Hệ sinh thái định hướng thị trường sáng tạo.”'
    )
    cleaned2 = _clean_blockquote_quote(bq2)
    assert cleaned2 == (
        "Các đường ống ý tưởng và đường ống tài năng cần phải hợp tác với nhau, "
        "như đã chứng kiến trong các Hệ sinh thái định hướng thị trường sáng tạo."
    )

    # Multi-line blockquote
    bq3 = (
        '> Dòng thứ nhất của trích dẫn.\n'
        '> Dòng thứ hai của trích dẫn.\n'
        '> — **Tác giả**, 2026'
    )
    cleaned3 = _clean_blockquote_quote(bq3)
    assert cleaned3 == "Dòng thứ nhất của trích dẫn. Dòng thứ hai của trích dẫn."

    # Empty/None input
    assert _clean_blockquote_quote("") == ""
    assert _clean_blockquote_quote(None) == ""


@patch("pipeline.image_processor.trigger_moc_rebuild")
@patch("pipeline.self_correct.verify_and_correct")
@patch("pipeline.ground_truth.correct_ocr")
@patch("pipeline.map_reduce.segment_concepts")
@patch("pipeline.ground_truth.find_ground_truth")
@patch("pipeline.synthesize.synthesize_concept")
@patch("pipeline.post_process.save_concept")
@patch("pipeline.image_processor._get_chapter_diagrams")
@patch("pipeline.post_process.archive_image")
def test_batch_hook_exclusion_data_flow(
    mock_archive, mock_diagrams, mock_save, mock_synthesize, mock_ground_truth, mock_segment, mock_correct_ocr, mock_verify, mock_rebuild
):
    """Should correctly inject exclude_hooks sequentially into subsequent synthesis calls in the same batch."""
    # 0. Mock JIT-imported LLM calling correction functions to run fast and locally without network requests
    mock_correct_ocr.side_effect = lambda h, gt: h
    mock_verify.side_effect = lambda content, gt: content
    mock_rebuild.return_value = None
    # 1. Setup mock segment_concepts returning 2 concepts
    mock_segment.return_value = [
        {"title": "Concept Một", "page_start": 1, "page_end": 1, "rationale": "Trang 1"},
        {"title": "Concept Hai", "page_start": 2, "page_end": 2, "rationale": "Trang 2"},
    ]

    # 2. Setup mock ground_truth
    gt_mock = MagicMock()
    gt_mock.paragraph = "This is ground truth paragraph."
    gt_mock.chapter = "some_chapter"
    gt_mock.page = 1
    gt_mock.score = 95.5
    mock_ground_truth.return_value = gt_mock

    # 3. Setup mock synthesize_concept
    # First synthesis yields a note with Evidence Hook "Trích dẫn thứ nhất."
    # Second synthesis yields a note with Evidence Hook "Trích dẫn thứ hai."
    first_note = (
        "---\n"
        "title: Concept Một\n"
        "---\n"
        "> \"Trích dẫn thứ nhất.\"\n"
        "> — **Tác giả**, *Sách* ([[ref|ref]])\n"
        "\n"
        "## Core Idea\n"
        "Nội dung phân tích một."
    )
    second_note = (
        "---\n"
        "title: Concept Hai\n"
        "---\n"
        "> \"Trích dẫn thứ hai.\"\n"
        "> — **Tác giả**, *Sách* ([[ref|ref]])\n"
        "\n"
        "## Core Idea\n"
        "Nội dung phân tích hai."
    )
    mock_synthesize.side_effect = [first_note, second_note]

    # 4. Setup other mocks
    mock_save.return_value = True
    mock_diagrams.return_value = ""

    # 5. Prepare pages_data (3 pages to trigger Map-Reduce which requires >=3 pages)
    pages_data = [
        PageData(image_path=Path("p1.webp"), page_number=1, highlighted="Highlight 1", context="Ctx 1"),
        PageData(image_path=Path("p2.webp"), page_number=2, highlighted="Highlight 2", context="Ctx 2"),
        PageData(image_path=Path("p3.webp"), page_number=3, highlighted="Highlight 3", context="Ctx 3"),
    ]

    # Run batch process
    with patch("pipeline.image_processor._interpolate_page_numbers") as mock_interpolate:
        # Patch the pages_data extraction inside process_image_batch
        # We need to construct it carefully to bypass actual OCR.
        with patch("pipeline.map_reduce.get_or_create_book_context") as mock_ctx:
            mock_ctx.return_value = "<BOOK_CONTEXT></BOOK_CONTEXT>"
            
            # Since process_image_batch receives Paths, runs OCR JIT, we mock the OCR stage
            # and JIT segmentations by patching inside the function.
            # Let's mock a simple wrapper that calls the Map-Reduce directly.
            # Instead of fighting GDrive/OCR mock complexity, let's test the batch reduce loop
            # by calling process_image_batch with pre-loaded mock states.
            # To do that, we patch the OCR and PageData creation in process_image_batch.
            with patch("pipeline.ocr.extract_ocr") as mock_extract_ocr:
                # Mock three OCR objects
                ocr1 = MagicMock()
                ocr1.is_toc = False
                ocr1.highlighted = "Highlight 1 - This is a long dummy text that is over thirty characters long."
                ocr1.context = "Ctx 1"
                ocr1.page_number = 1

                ocr2 = MagicMock()
                ocr2.is_toc = False
                ocr2.highlighted = "Highlight 2 - This is a long dummy text that is over thirty characters long."
                ocr2.context = "Ctx 2"
                ocr2.page_number = 2

                ocr3 = MagicMock()
                ocr3.is_toc = False
                ocr3.highlighted = "Highlight 3 - This is a long dummy text that is over thirty characters long."
                ocr3.context = "Ctx 3"
                ocr3.page_number = 3

                mock_extract_ocr.side_effect = [ocr1, ocr2, ocr3]

                img1 = Path("05 - Fleeting/Reinventing_the_Organization/p1.webp")
                img2 = Path("05 - Fleeting/Reinventing_the_Organization/p2.webp")
                img3 = Path("05 - Fleeting/Reinventing_the_Organization/p3.webp")

                success = process_image_batch([img1, img2, img3])
                
                assert success is True

    # 6. Verify synthesize_concept calls
    assert mock_synthesize.call_count == 2
    
    # First call: exclude_hooks was empty, so highlighted should NOT contain [CRITICAL DIRECTIVE]
    first_call_args = mock_synthesize.call_args_list[0][1]
    assert "[CRITICAL DIRECTIVE" not in first_call_args["highlighted"]

    # Second call: exclude_hooks should contain cleaned "Trích dẫn thứ nhất." from first note!
    second_call_args = mock_synthesize.call_args_list[1][1]
    assert "[CRITICAL DIRECTIVE: Để tránh trùng lặp trích dẫn" in second_call_args["highlighted"]
    assert '- "Trích dẫn thứ nhất."' in second_call_args["highlighted"]
    assert "Hãy chọn một câu trích dẫn/highlight khác" in second_call_args["highlighted"]
