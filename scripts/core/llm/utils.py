"""VvC Second Brain — LLM Utils.

Common utilities for the LLM package.
"""

import base64
import logging
import re
import threading
from datetime import date
from pathlib import Path

import requests

_logger = logging.getLogger("vvc.llm.utils")

# --- Global HTTP Session (TCP Pooling) ---
http_session = requests.Session()

# --- Daily API Call Counters (thread-safe) ---
_counters_lock = threading.Lock()
_daily_counters: dict[str, int] = {}
_counter_date: str = ""

def increment_counter(key: str) -> int:
    """Increment and return daily call count for a key."""
    global _counter_date
    today = date.today().isoformat()
    with _counters_lock:
        if _counter_date != today:
            _daily_counters.clear()
            _counter_date = today
        _daily_counters[key] = _daily_counters.get(key, 0) + 1
        return _daily_counters[key]

def get_counter(key: str) -> int:
    """Get current daily call count."""
    with _counters_lock:
        return _daily_counters.get(key, 0)

# --- Think Tag Stripping ---
_THINK_PATTERN = re.compile(r"<think>.*?</think>\n*", re.DOTALL | re.IGNORECASE)
_THINK_UNCLOSED = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)
_ORPHAN_END = re.compile(r"^.*?</think>\n*", re.DOTALL | re.IGNORECASE)

def strip_think_tags(text: str) -> str:
    """Unconditionally remove all <think>...</think> blocks or orphan </think>."""
    if not text:
        return text
    text = _THINK_PATTERN.sub("", text)
    if "</think>" in text.lower():
        text = _ORPHAN_END.sub("", text)
    text = _THINK_UNCLOSED.sub("", text)
    return text.strip()

# --- Output Validation ---
_GARBAGE_PATTERNS = [
    r"Error connecting",
    r"ECONNREFUSED",
    r"fetch failed",
    r"rate limit exceeded",
    r"quota exceeded",
]

def is_garbage(text: str, allowed_shorts: tuple[str, ...] = ()) -> bool:
    """Check if LLM output is garbage (timeout, error, garbled)."""
    if not text:
        return True
    clean = text.strip().upper()
    
    # Combined default boolean whitelist with dynamic permitted short strings
    default_shorts = ("YES", "NO", "TRUE", "FALSE")
    custom_shorts = tuple(str(x).upper() for x in allowed_shorts)
    full_whitelist = default_shorts + custom_shorts
    
    if clean in full_whitelist or any(clean.startswith(w) for w in full_whitelist):
        return False
    if len(clean) < 10:
        return True
    text_lower = text.lower()
    return any(re.search(pat, text, re.IGNORECASE) for pat in _GARBAGE_PATTERNS)

# --- Image Encoding ---
def encode_image(image_path: Path, max_pixels: int = 1024) -> str:
    """Resize and base64-encode an image for vision APIs."""
    try:
        from PIL import Image, ImageOps

        img = Image.open(image_path)
        img = ImageOps.exif_transpose(img)  # Auto-orient
        img.thumbnail((max_pixels, max_pixels), Image.Resampling.LANCZOS)

        from io import BytesIO
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        _logger.error(f"Image encoding failed: {e}")
        # Fallback: raw base64 without resize
        return base64.b64encode(image_path.read_bytes()).decode("utf-8")
