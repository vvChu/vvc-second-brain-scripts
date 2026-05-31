"""VvC Second Brain — Shared Pipeline Types (v8.10).

Centralized type definitions for the ingestion pipeline data flow.
Provides typed alternatives to raw dicts for better IDE support and documentation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.ocr import OcrResult


@dataclass
class PageData:
    """Typed representation of a single page's OCR + Ground Truth data.

    Replaces untyped dict passed between pipeline stages.
    Used in: image_processor.py, map_reduce.py.

    Attributes:
        image_path: Path to the original source image.
        highlighted: Highlighted/underlined text from OCR.
        context: Surrounding context text from OCR.
        page_number: Detected page number (None if unknown, 0 as default).
    """
    image_path: Path
    highlighted: str = ""
    context: str = ""
    page_number: int | None = None

    @classmethod
    def from_ocr(cls, image_path: Path, ocr: OcrResult) -> PageData:
        """Create a PageData from an OcrResult.

        Args:
            image_path: Source image path.
            ocr: Structured OCR result.

        Returns:
            Populated PageData instance.
        """
        return cls(
            image_path=image_path,
            highlighted=ocr.highlighted,
            context=ocr.context,
            page_number=ocr.page_number,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to legacy dict format for backward compatibility.

        Returns:
            Dict with keys: image_path, highlighted, context, page_number.
        """
        return {
            "image_path": self.image_path,
            "highlighted": self.highlighted,
            "context": self.context,
            "page_number": self.page_number,
        }


@dataclass
class PipelineContext:
    """Shared context passed through the full pipeline for a single batch.

    Attributes:
        book_name: Normalized book identifier.
        workspace_dir: Path to the book's workspace in 05-Fleeting/.
        source_ref: Wiki-link stem to the source note.
        pages: List of PageData for all pages in this batch.
        extra: Extensible dict for stage-specific metadata.
    """
    book_name: str = ""
    workspace_dir: Path | None = None
    source_ref: str = ""
    pages: list[PageData] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

