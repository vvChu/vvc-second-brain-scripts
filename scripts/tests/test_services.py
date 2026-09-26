"""Tests for services modules."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


# --- Command Handler Tests ---

def test_parse_style():
    """Should parse style prefix from query."""
    from services.command import _parse_style

    style, query = _parse_style("/tim-urban What is AI?")
    assert style == "tim-urban"
    assert query == "What is AI?"

    style, query = _parse_style("Normal query without prefix")
    assert style == "professional"
    assert query == "Normal query without prefix"

    style, query = _parse_style("/eli5 Quantum computing")
    assert style == "eli5"
    assert query == "Quantum computing"

    style, query = _parse_style("/phan-bien Kế hoạch mới")
    assert style == "sparring"
    assert query == "Kế hoạch mới"

    style, query = _parse_style("/sparring New strategy")
    assert style == "sparring"
    assert query == "New strategy"


def test_find_pending_query():
    """Should find unanswered @AI queries inside the correct Input section."""
    from services.command import _find_pending_query
    from services.command.inbox import INPUT_MARKER, HISTORY_MARKER

    # Must use exact markers from command.py (## \U0001f4e5 Input / ## \U0001f570\ufe0f Lịch sử)
    content = f"{INPUT_MARKER}\n@AI: What is transformer? ---\n\n{HISTORY_MARKER}\n"
    result = _find_pending_query(content)
    assert result is not None
    assert "What is transformer?" in result


def test_find_pending_query_answered():
    """Should return None when Inbox has no pending @AI query."""
    from services.command import _find_pending_query
    from services.command.inbox import INPUT_MARKER, HISTORY_MARKER

    # Inbox is empty — query is only in history (already answered)
    content = f"{INPUT_MARKER}\n\n{HISTORY_MARKER}\n@AI: Old question ---\n> [!done] Answer here\n"
    result = _find_pending_query(content)
    assert result is None


def test_writing_styles_count():
    """Should have exactly 11 writing styles."""
    from services.command import WRITING_STYLES

    assert len(WRITING_STYLES) == 11
    assert "professional" in WRITING_STYLES
    assert "tim-urban" in WRITING_STYLES
    assert "eli5" in WRITING_STYLES
    assert "sparring" in WRITING_STYLES
    assert "fast" in WRITING_STYLES
    assert "hero-image" in WRITING_STYLES


# --- Brain Dump Tests ---

def test_is_garbage_fetch():
    """Should detect garbage URL fetches."""
    from services.url_fetcher import _is_garbage_fetch

    assert _is_garbage_fetch("short") is True
    assert _is_garbage_fetch("javascript is disabled. Please enable javascript") is True
    assert _is_garbage_fetch("This is a legitimate article with enough content." * 5) is False


def test_find_pending_dump_processed():
    """Should return None when there is no ## Inbox section."""
    from services.brain_dump import _find_pending_dump

    # No Inbox section at all — nothing to process
    content = "## Processed\nSome old dump\n"
    assert _find_pending_dump(content) is None


def test_find_pending_dump_new():
    """Should return content from ## Inbox section."""
    from services.brain_dump import _find_pending_dump

    content = "## Inbox\nNew idea about AI and machine learning concepts.\n\n## Processed\n"
    result = _find_pending_dump(content)
    assert result is not None
    assert "AI" in result


# --- Wiki Health Tests ---

def test_reject_patterns():
    """Should reject garbage link targets."""
    import re
    from services.wiki_health import _REJECT_PATTERNS

    garbage = ["2012", "AI", "Ví dụ", "Chương 3", "42"]
    for g in garbage:
        assert any(re.match(pat, g) for pat in _REJECT_PATTERNS), f"Should reject: {g}"

    valid = ["transformer_architecture", "Bayesian Inference"]
    for v in valid:
        assert not any(re.match(pat, v) for pat in _REJECT_PATTERNS), f"Should accept: {v}"


def test_canonical_domains():
    """Should have canonical domain taxonomy."""
    from services.wiki_health import CANONICAL_DOMAINS

    assert "ai" in CANONICAL_DOMAINS
    assert "business" in CANONICAL_DOMAINS
    assert len(CANONICAL_DOMAINS) >= 10


# --- Mermaid Worker Tests ---

def test_clean_mermaid_valid():
    """Should accept valid Mermaid syntax."""
    from services.mermaid_worker import _clean_mermaid

    valid = "graph TD\n  A[Start] --> B[End]"
    assert _clean_mermaid(valid) == valid

    fenced = "```mermaid\nflowchart LR\n  A --> B\n```"
    cleaned = _clean_mermaid(fenced)
    assert cleaned.startswith("flowchart")
    assert "```" not in cleaned


def test_clean_mermaid_invalid():
    """Should reject invalid Mermaid syntax."""
    from services.mermaid_worker import _clean_mermaid

    assert _clean_mermaid("This is just text") == ""
    assert _clean_mermaid("") == ""


# --- MOC Diagram Tests ---

def test_group_by_chapter():
    """Should group concepts by ground_truth_chapter with fallback."""
    from services.moc_mermaid import group_by_chapter

    concepts = [
        {"_stem": "a", "ground_truth_chapter": '[[07_CHAPTER 4]]'},
        {"_stem": "b", "ground_truth_chapter": '[[07_CHAPTER 4]]'},
        {"_stem": "c", "ground_truth_chapter": '[[08_Chapter 5]]'},
        {"_stem": "d", "ground_truth_chapter": "", "source_chapter": ""},
        {"_stem": "e"},  # No chapter at all
    ]
    groups = group_by_chapter(concepts)

    assert "07_CHAPTER 4" in groups
    assert len(groups["07_CHAPTER 4"]) == 2
    assert "08_Chapter 5" in groups
    assert "_ungrouped" in groups
    assert len(groups["_ungrouped"]) == 2


def test_clean_chapter_name():
    """Should clean chapter key into display-friendly name."""
    from services.moc_mermaid import clean_chapter_name

    assert clean_chapter_name("09_Chuong_6_Hop_phan_van_de") == "Chuong 6 Hop Phan Van De"
    assert clean_chapter_name("07_CHAPTER 4") == "Chapter 4"


# --- URL Deduplication Tests (v8.9) ---

def test_normalize_url():
    """Should normalize URLs by removing schemes, query tracking and trailing slashes."""
    from services.brain_dump import _normalize_url

    assert _normalize_url("https://example.com/some-article/") == "example.com/some-article"
    assert _normalize_url("http://www.example.com/some-article?utm_source=facebook&ref=xyz") == "example.com/some-article"
    # Special Youtube handling
    assert _normalize_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=share") == "youtube.com/watch?v=dQw4w9WgXcQ"
    assert _normalize_url("https://youtu.be/dQw4w9WgXcQ") == "youtu.be/dQw4w9WgXcQ"


def test_check_override():
    """Should detect override keywords in the inbox line."""
    from services.brain_dump import _check_override

    assert _check_override("https://example.com/art xử lý lại") is True
    assert _check_override("https://example.com/art /force") is True
    assert _check_override("https://example.com/art") is False
    assert _check_override("Normal line without keywords") is False


def test_url_deduplication_logic():
    """Should detect duplicate URL and build proper auto-feedback loop."""
    import json
    from unittest.mock import MagicMock
    from services.brain_dump import _normalize_url, _check_override

    # Create dummy registry
    dummy_registry = {
        "example.com/old-article": {
            "source_note": "2026-05-28_old_article",
            "concepts": [
                {"stem": "old_concept_1", "title": "Old Concept 1"}
            ],
            "processed_at": "2026-05-28T13:20:00"
        }
    }

    # Verify matching
    norm_url = _normalize_url("https://example.com/old-article")
    assert norm_url in dummy_registry

    # Verify building feedback lines
    entry = dummy_registry[norm_url]
    feedback_lines = []
    if entry.get("source_note"):
        feedback_lines.append(f"- [[{entry['source_note']}|Ghi chép gốc (Đã xử lý trước đó)]]")
    for c in entry.get("concepts", []):
        feedback_lines.append(f"  - [[{c['stem']}|{c['title']}]] (Đã tồn tại)")

    assert len(feedback_lines) == 2
    assert "2026-05-28_old_article" in feedback_lines[0]
    assert "old_concept_1" in feedback_lines[1]




def test_extract_video_visuals_mock():
    """Should mock video download and frames extraction, returning mock visual description."""
    from services.youtube import extract_video_visuals
    
    with patch("yt_dlp.YoutubeDL") as mock_ydl, \
         patch("shutil.which", return_value="C:\\ffmpeg\\bin\\ffmpeg.exe"), \
         patch("subprocess.run") as mock_run, \
         patch("pathlib.Path.glob") as mock_glob, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_file", return_value=True), \
         patch("pathlib.Path.read_bytes", return_value=b"MOCK_BYTES"), \
         patch("core.llm.utils.encode_image", return_value="MOCK_B64"), \
         patch("core.llm.utils.http_session.post") as mock_post:
         
        # Mock yt-dlp extracting info
        mock_instance = mock_ydl.return_value.__enter__.return_value
        mock_instance.extract_info.return_value = {"id": "K-uyMNSoFhk"}
        
        # Mock glob to find the downloaded video and frames without raising StopIteration
        from pathlib import Path
        def custom_glob(pattern):
            if "K-uyMNSoFhk" in str(pattern):
                return [Path("D:\\VvC_Notes\\scripts\\scratch\\_video_tmp\\K-uyMNSoFhk.mp4")]
            else:
                return [Path(f"D:\\VvC_Notes\\scripts\\scratch\\_video_tmp\\frame_{i:04d}.jpg") for i in range(1, 5)]
        mock_glob.side_effect = custom_glob
        
        # Mock subprocess run to simulate successful ffmpeg execution
        mock_run.return_value.returncode = 0
        
        # Mock HTTP POST response from Gateway API
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "Đây là mô tả visual của các slide và sơ đồ trong video YouTube."
                }
            }]
        }
        mock_post.return_value = mock_response
        
        result = extract_video_visuals("https://youtu.be/K-uyMNSoFhk")
        assert "mô tả visual" in result
        assert result.startswith("Đây là")


def test_extract_video_visuals_with_keyframes():
    """Should save selected key frames and append IMG markers to visual summary."""
    from services.youtube import extract_video_visuals
    
    with patch("yt_dlp.YoutubeDL") as mock_ydl, \
         patch("shutil.which", return_value="C:\\ffmpeg\\bin\\ffmpeg.exe"), \
         patch("subprocess.run") as mock_run, \
         patch("pathlib.Path.glob") as mock_glob, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.is_file", return_value=True), \
         patch("pathlib.Path.read_bytes", return_value=b"MOCK_BYTES"), \
         patch("core.llm.utils.encode_image", return_value="MOCK_B64"), \
         patch("PIL.Image.open") as mock_pil_open, \
         patch("core.llm.utils.http_session.post") as mock_post:
         
        # Mock yt-dlp extracting info
        mock_instance = mock_ydl.return_value.__enter__.return_value
        mock_instance.extract_info.return_value = {"id": "K-uyMNSoFhk"}
        
        # Mock glob to find the downloaded video and frames
        from pathlib import Path
        def custom_glob(pattern):
            if "K-uyMNSoFhk" in str(pattern):
                return [Path("D:\\VvC_Notes\\scripts\\scratch\\_video_tmp\\K-uyMNSoFhk.mp4")]
            else:
                return [Path(f"D:\\VvC_Notes\\scripts\\scratch\\_video_tmp\\frame_{i:04d}.jpg") for i in range(1, 5)]
        mock_glob.side_effect = custom_glob
        
        # Mock subprocess run
        mock_run.return_value.returncode = 0
        
        # Mock PIL Image open
        mock_img = MagicMock()
        mock_pil_open.return_value = mock_img
        
        # Mock HTTP POST response from Gateway API including KEY_FRAMES JSON
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "Đây là mô tả visual của các slide.\n\nKEY_FRAMES: [1, 2]"
                }
            }]
        }
        mock_post.return_value = mock_response
        
        result = extract_video_visuals("https://youtu.be/K-uyMNSoFhk")
        
        assert "mô tả visual" in result
        assert "Hình ảnh trực quan từ video" in result
        assert "[IMG:yt_K-uyMNSoFhk_frame_001_ts" in result


# --- Article Image Extraction Tests ---

def test_is_noise_image_logo_url():
    """Should detect logo URLs as noise."""
    from services.article_images import _is_noise_image
    from bs4 import BeautifulSoup

    html = '<img src="https://example.com/wp-content/logo.png" alt="Logo">'
    soup = BeautifulSoup(html, "html.parser")
    img = soup.find("img")
    assert _is_noise_image(img, "https://example.com/wp-content/logo.png") is True


def test_is_noise_image_small_dimensions():
    """Should detect small-dimension images as noise."""
    from services.article_images import _is_noise_image
    from bs4 import BeautifulSoup

    html = '<img src="https://example.com/tiny.png" width="30" height="30">'
    soup = BeautifulSoup(html, "html.parser")
    img = soup.find("img")
    assert _is_noise_image(img, "https://example.com/tiny.png") is True


def test_is_noise_image_valid_content():
    """Should NOT flag a valid content image as noise."""
    from services.article_images import _is_noise_image
    from bs4 import BeautifulSoup

    html = '<article><img src="https://example.com/diagram.png" width="500" height="400" alt="Software diagram"></article>'
    soup = BeautifulSoup(html, "html.parser")
    img = soup.find("img")
    assert _is_noise_image(img, "https://example.com/diagram.png") is False


def test_is_noise_image_in_nav():
    """Should detect images inside nav elements as noise."""
    from services.article_images import _is_noise_image
    from bs4 import BeautifulSoup

    html = '<nav><img src="https://example.com/menu-icon.png" alt="Menu"></nav>'
    soup = BeautifulSoup(html, "html.parser")
    img = soup.find("img")
    assert _is_noise_image(img, "https://example.com/menu-icon.png") is True


def test_is_noise_image_in_sidebar():
    """Should detect images inside sidebar div as noise."""
    from services.article_images import _is_noise_image
    from bs4 import BeautifulSoup

    html = '<div id="sidebar"><img src="https://example.com/ad.png" alt="Ad"></div>'
    soup = BeautifulSoup(html, "html.parser")
    img = soup.find("img")
    assert _is_noise_image(img, "https://example.com/ad.png") is True


def test_format_image_metadata_empty():
    """Should return empty string for empty image list."""
    from services.article_images import format_image_metadata
    assert format_image_metadata([]) == ""


def test_format_image_metadata_with_images():
    """Should format image metadata as structured text."""
    from services.article_images import format_image_metadata

    images = [
        {"filename": "example_diagram.webp", "alt": "A diagram", "original_url": "https://example.com/diagram.png"},
        {"filename": "example_chart.webp", "alt": "A chart", "original_url": "https://example.com/chart.png"},
    ]
    result = format_image_metadata(images)
    assert "🖼️ Hình ảnh bài viết" in result
    assert "[IMG:example_diagram.webp|alt=A diagram]" in result
    assert "[IMG:example_chart.webp|alt=A chart]" in result


def test_make_image_filename_unique():
    """Should generate unique filenames with collision prevention."""
    from services.article_images import _make_image_filename

    seen = set()
    f1 = _make_image_filename("https://example.com/test.png", "example", seen)
    f2 = _make_image_filename("https://example.com/test.png", "example", seen)
    assert f1 != f2
    assert f1 == "example_test.webp"
    assert "example_test_2.webp" == f2


@patch("services.article_images._requests")
@patch("services.article_images.PILImage")
def test_extract_article_images_mock(mock_pil, mock_requests):
    """Should extract and filter images from article HTML (mocked)."""
    from services.article_images import extract_article_images

    html = """
    <html><body>
    <nav><img src="/logo.png" alt="Logo"></nav>
    <article>
        <img src="https://example.com/diagram1.png" width="500" height="400" alt="Diagram 1">
        <img src="https://example.com/diagram2.png" width="600" height="300" alt="Diagram 2">
        <img src="https://example.com/diagram3.png" width="400" height="250" alt="Diagram 3">
        <img src="https://example.com/icon-small.png" width="20" height="20" alt="Icon">
    </article>
    <footer><img src="/footer-badge.png" alt="Badge"></footer>
    </body></html>
    """

    # Mock HTTP response for each image download
    mock_resp = MagicMock()
    mock_resp.content = b"\x00" * 10_000  # 10KB fake content
    mock_resp.raise_for_status = MagicMock()
    mock_requests.get.return_value = mock_resp

    # Mock PIL Image
    mock_img = MagicMock()
    mock_img.width = 500
    mock_img.height = 400
    mock_img.mode = "RGB"
    mock_pil.open.return_value = mock_img
    mock_pil.Resampling.LANCZOS = 1

    results = extract_article_images(html, "https://example.com/article")

    # Should extract 3 diagrams, exclude logo (nav), icon (small), badge (footer)
    assert len(results) == 3
    assert all("diagram" in r["alt"].lower() for r in results)


def test_make_image_filename_svg():
    """Should generate correct unique .svg filename when original is SVG."""
    from services.article_images import _make_image_filename

    seen = set()
    f1 = _make_image_filename("https://example.com/diagram.svg", "myblog", seen)
    f2 = _make_image_filename("https://example.com/diagram.svg", "myblog", seen)
    assert f1 == "myblog_diagram.svg"
    assert f2 == "myblog_diagram_2.svg"


def test_extract_custom_theme_images():
    """Should extract custom React <ThemeImage> tags, prioritizing dark URL."""
    from services.article_images import _extract_custom_theme_images

    # JSX Format
    jsx_html = """
    <div>
      <ThemeImage urls={{dark: "https://example.com/dark.svg", light: "https://example.com/light.svg"}} alt="My Cool Diagram" />
    </div>
    """
    res1 = _extract_custom_theme_images(jsx_html)
    assert len(res1) == 1
    assert res1[0]["url"] == "https://example.com/dark.svg"
    assert res1[0]["alt"] == "My Cool Diagram"

    # Escaped JSON string Format (e.g. Next.js server payload)
    escaped_html = '\\u003cThemeImage urls={{dark: \\"https://example.com/a_dark.svg\\", light: \\"https://example.com/a_light.svg\\"}} width={738} height={427} alt=\\"Diagram showing architecture\\" /\\u003e'
    res2 = _extract_custom_theme_images(escaped_html)
    assert len(res2) == 1
    assert res2[0]["url"] == "https://example.com/a_dark.svg"
    assert res2[0]["alt"] == "Diagram showing architecture"


@patch("services.article_images._requests")
def test_download_and_compress_svg(mock_requests, tmp_path):
    """Should bypass Pillow and write SVG bytes directly to disk."""
    from services.article_images import _download_and_compress

    mock_resp = MagicMock()
    mock_resp.content = b"<svg>Mock Vector Graphic</svg>"
    mock_resp.raise_for_status = MagicMock()
    mock_requests.get.return_value = mock_resp

    save_path = tmp_path / "diagram.svg"
    success = _download_and_compress("https://example.com/diagram.svg", save_path)

    assert success is True
    assert save_path.exists()
    assert save_path.read_bytes() == b"<svg>Mock Vector Graphic</svg>"


@patch("services.twitter._fetch_fxtwitter_payload")
def test_fetch_url_twitter_fxtwitter_conversion(mock_payload):
    """Should automatically intercept x.com and twitter.com and fetch via Twitter service."""
    from services.url_fetcher import fetch_url
    
    mock_payload.return_value = {
        "text": "Legitimate Twitter content crawling via fxtwitter",
        "author": {"name": "Test Author", "screen_name": "test_author"},
        "created_at": "Mon Sep 21 15:00:00 +0000 2026",
    }
    
    result = fetch_url("https://x.com/test_author/status/2059939222333567211", transcribe=False)
    
    assert "Legitimate Twitter content" in result
    assert "test_author" in result


