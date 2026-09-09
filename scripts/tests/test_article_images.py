"""Tests for article_images service module, including Aspect Ratio Gate."""

import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image as PILImage

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.article_images import (
    _MAX_ASPECT_RATIO,
    _download_and_compress,
    _is_noise_image,
    _make_image_filename,
)


def _create_test_image_bytes(width: int, height: int, fmt: str = "JPEG") -> bytes:
    """Helper to create dummy in-memory image bytes guaranteed to be > 5KB."""
    img = PILImage.new("RGB", (width, height))
    pixels = img.load()
    for x in range(width):
        for y in range(height):
            pixels[x, y] = ((x * 37 + y * 17) % 256, (x * 41 + y * 13) % 256, (y * 53 + x) % 256)
    buf = BytesIO()
    img.save(buf, format=fmt, quality=95)
    return buf.getvalue()


def test_aspect_ratio_gate_rejection(tmp_path):
    """Extreme aspect ratios (> 4.5) should be rejected as banners or dividers."""
    save_path = tmp_path / "banner.webp"

    # 1. Thin horizontal banner (1200 x 200 -> ratio 6.0 > 4.5)
    wide_bytes = _create_test_image_bytes(1200, 200)
    mock_resp = MagicMock()
    mock_resp.content = wide_bytes
    mock_resp.raise_for_status.return_value = None

    with patch("requests.get", return_value=mock_resp):
        success = _download_and_compress("https://example.com/banner.png", save_path)
        assert success is False
        assert not save_path.exists()

    # 2. Tall vertical divider (200 x 1000 -> ratio 5.0 > 4.5)
    tall_bytes = _create_test_image_bytes(200, 1000)
    mock_resp.content = tall_bytes

    with patch("requests.get", return_value=mock_resp):
        success = _download_and_compress("https://example.com/vertical_bar.png", save_path)
        assert success is False
        assert not save_path.exists()


def test_aspect_ratio_gate_acceptance(tmp_path):
    """Normal aspect ratios (<= 4.5) should pass the gate and be saved as WebP."""
    save_path = tmp_path / "diagram.webp"

    # Standard diagram (800 x 600 -> ratio 1.33)
    normal_bytes = _create_test_image_bytes(800, 600)
    mock_resp = MagicMock()
    mock_resp.content = normal_bytes
    mock_resp.raise_for_status.return_value = None

    with patch("requests.get", return_value=mock_resp):
        success = _download_and_compress("https://example.com/diagram.png", save_path)
        assert success is True
        assert save_path.exists()


def test_aspect_ratio_boundary_values(tmp_path):
    """Verify exact boundary behavior around ratio 4.5."""
    save_path = tmp_path / "boundary.webp"

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None

    # Ratio exactly 4.5 (900 x 200) -> Allowed (<= 4.5)
    mock_resp.content = _create_test_image_bytes(900, 200)
    with patch("requests.get", return_value=mock_resp):
        success = _download_and_compress("https://example.com/boundary_pass.png", save_path)
        assert success is True

    save_path.unlink()

    # Ratio 4.6 (920 x 200) -> Rejected (> 4.5)
    mock_resp.content = _create_test_image_bytes(920, 200)
    with patch("requests.get", return_value=mock_resp):
        success = _download_and_compress("https://example.com/boundary_fail.png", save_path)
        assert success is False
        assert not save_path.exists()


def test_svg_bypasses_pillow_and_aspect_ratio(tmp_path):
    """SVG files should bypass Pillow decoding and aspect ratio check entirely."""
    save_path = tmp_path / "vector.svg"
    svg_data = b"<svg width='2000' height='50'><rect width='2000' height='50'/></svg>"

    mock_resp = MagicMock()
    mock_resp.content = svg_data
    mock_resp.raise_for_status.return_value = None

    with patch("requests.get", return_value=mock_resp):
        success = _download_and_compress("https://example.com/vector.svg", save_path)
        assert success is True
        assert save_path.exists()
        assert save_path.read_bytes() == svg_data


def test_make_image_filename_dedup():
    """Verify filename generation and collision prevention."""
    seen = set()
    fn1 = _make_image_filename("https://example.com/images/architecture.png", "my_domain", seen)
    fn2 = _make_image_filename("https://example.com/other/architecture.png", "my_domain", seen)

    assert fn1 == "my_domain_architecture.webp"
    assert fn2 == "my_domain_architecture_2.webp"
    assert len(seen) == 2
