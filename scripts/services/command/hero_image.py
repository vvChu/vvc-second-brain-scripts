"""VvC Second Brain — Hero Image Command & Metaphor Synthesizer (v8.13.0).

Handles /hero-image, /hero, and /banner commands:
- Extracts context from referenced topic notes in 04 - Permanent/topics/
- Synthesizes 16:9 cinematic visual metaphor descriptions & prompts
- Generates hero images via AI Gateway or pluggable generator
- Saves to 03 - Resources/attachments/{slug}_hero.jpg
- Embeds ![[{slug}_hero.jpg|100%]] beneath the H1 title of the topic note
"""

from __future__ import annotations

import base64
import logging
import re
import os
from pathlib import Path
from typing import Any, Callable

from core.config import cfg
from core.frontmatter import extract_body, normalize_stem, parse_frontmatter, _FM_PATTERN
from core.llm import call_llm
from core.log import log
from core.prompts.services import COMMAND_RESPONSE as _RESPONSE_PROMPT
from services.command.styles import WRITING_STYLES
from services.rag_builder import build_rag_context

_logger = logging.getLogger("vvc.command.hero_image")

# Global custom image generator hook for testing or external plugins
_custom_image_generator: Callable[[str, Path], bool] | None = None


def set_custom_image_generator(fn: Callable[[str, Path], bool] | None) -> None:
    """Set or clear a custom image generator callback."""
    global _custom_image_generator
    _custom_image_generator = fn


def find_topic_note(query: str, topics_dir: Path) -> tuple[str, Path | None]:
    """Identify topic note from query wikilink(s), title, or slug.

    Supports multiple wikilinks in query, frontmatter title/alias resolution,
    and subpath prefixes (e.g. [[topics/slug]]).

    Args:
        query: Query string, possibly containing [[topic_slug]] or a title.
        topics_dir: Directory containing topic notes (04 - Permanent/topics/).

    Returns:
        tuple of (slug, topic_path). topic_path is None if not found on disk.
    """
    wikilinks = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", query)

    def _resolve_candidate(target_raw: str) -> tuple[str, Path] | None:
        clean = target_raw.strip()
        if clean.endswith(".md"):
            clean = clean[:-3]
        target_stem = Path(clean).stem
        slug = normalize_stem(target_stem) or "topic"

        candidates = [
            topics_dir / f"{clean}.md",
            topics_dir / f"{target_stem}.md",
            topics_dir / f"{slug}.md",
        ]
        for cand in candidates:
            if cand.exists():
                return cand.stem, cand

        # Search existing topic files for title or alias match
        if topics_dir.exists():
            for f in topics_dir.glob("*.md"):
                if f.stem.lower() == slug.lower() or f.stem.lower() == target_stem.lower():
                    return f.stem, f
                try:
                    fm = parse_frontmatter(f.read_text(encoding="utf-8"))
                    title = fm.get("title", "")
                    if title and (target_stem.lower() == str(title).lower() or slug == normalize_stem(str(title))):
                        return f.stem, f
                    aliases = fm.get("aliases", [])
                    if isinstance(aliases, list):
                        for a in aliases:
                            if isinstance(a, str) and (
                                target_stem.lower() == a.lower() or slug == normalize_stem(a)
                            ):
                                return f.stem, f
                except Exception:
                    continue
        return None

    # 1. Check each wikilink in query
    for link in wikilinks:
        res = _resolve_candidate(link)
        if res is not None:
            return res

    # 2. If no wikilink matched an existing file, try matching plain query
    clean_q = query.strip()
    if clean_q:
        res = _resolve_candidate(clean_q)
        if res is not None:
            return res

    # 3. Fallback: determine slug from wikilink or query
    fallback_target = wikilinks[0] if wikilinks else clean_q
    if fallback_target.endswith(".md"):
        fallback_target = fallback_target[:-3]
    fallback_stem = Path(fallback_target).stem
    slug = normalize_stem(fallback_stem) or "topic"
    return slug, None


def extract_topic_context(topic_path: Path, max_chars: int = 4000) -> str:
    """Read topic note and extract body context without frontmatter.

    Args:
        topic_path: Path to topic note markdown file.
        max_chars: Maximum characters to return.

    Returns:
        Clean body content string.
    """
    try:
        content = topic_path.read_text(encoding="utf-8")
    except OSError as e:
        _logger.warning(f"Failed to read topic note {topic_path}: {e}")
        return ""

    body = extract_body(content).strip()
    return body[:max_chars]


def embed_hero_image_in_topic(topic_content: str, image_filename: str) -> str:
    """Seamlessly embed ![[{image_filename}|100%]] beneath the H1 title of a topic note.

    Preserves frontmatter and handles both LF and Windows CRLF line endings.
    Idempotent: does not duplicate if already embedded.

    Args:
        topic_content: Markdown content of the topic note.
        image_filename: e.g. "thiet_ke_deep_module_hero.jpg".

    Returns:
        Updated topic note markdown content.
    """
    embed_tag = f"![[{image_filename}|100%]]"
    if f"![[{image_filename}" in topic_content:
        return topic_content

    # Match H1 title (# Heading) safely across LF and CRLF
    h1_match = re.search(r"^(#\s+[^\r\n]+)", topic_content, re.MULTILINE)
    if h1_match:
        end = h1_match.end()
        rest = topic_content[end:].lstrip("\r\n")
        return topic_content[:end].rstrip("\r\n") + f"\n\n{embed_tag}\n\n" + rest

    # Fallback: if no H1, insert after YAML frontmatter
    fm_match = _FM_PATTERN.match(topic_content)
    if fm_match:
        end = fm_match.end()
        rest = topic_content[end:].lstrip("\r\n")
        return topic_content[:end].rstrip("\r\n") + f"\n\n{embed_tag}\n\n" + rest

    # Fallback: insert at very top
    return f"{embed_tag}\n\n" + topic_content.lstrip("\r\n")


def extract_image_prompt(response: str) -> str:
    """Extract English visual metaphor prompt from LLM response text.

    Args:
        response: Full LLM response containing visual analysis and prompt.

    Returns:
        Extracted prompt string for image generation.
    """
    def _clean_candidate(text: str) -> str:
        t = text.strip()
        # Strip markdown code fences if enclosed
        t = re.sub(r"^```[a-zA-Z]*\s*\n?", "", t)
        t = re.sub(r"\n?```\s*$", "", t)
        return t.strip(" \"'`")

    # Look for designated prompt sections
    patterns = [
        r"(?:###\s*Final Image Prompt|###\s*Image Prompt|Final Image Prompt:|Prompt:)\s*\n*(.*?)(?:\n\n---|\n#|\Z)",
        r"> \*\*Final Image Prompt\*\*:\s*(.*?)(?:\n\n|\Z)",
        r"```(?:text|prompt)?\s*\n(.*?)\n```",
    ]
    for pattern in patterns:
        m = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
        if m:
            candidate = _clean_candidate(m.group(1))
            if len(candidate) > 20:
                return candidate

    # Fallback: look for English paragraph with cinematic/lighting keywords
    paragraphs = response.split("\n\n")
    for p in paragraphs:
        lower = p.lower()
        if any(kw in lower for kw in ("16:9", "cinematic", "lighting", "render", "photographic", "palette")):
            return _clean_candidate(p)

    return _clean_candidate(response[:500])


def generate_hero_image(prompt: str, output_path: Path, active_cfg: Any = None) -> bool:
    """Generate hero image from prompt and save to output_path.

    Tries custom generator hook first, then AI Gateway /images/generations endpoint.

    Args:
        prompt: Visual metaphor prompt.
        output_path: Destination path (03 - Resources/attachments/{slug}_hero.jpg).
        active_cfg: Optional configuration override (defaults to core cfg).

    Returns:
        True if generated and saved, False otherwise.
    """
    if _custom_image_generator is not None:
        try:
            return _custom_image_generator(prompt, output_path)
        except Exception as e:
            _logger.warning(f"Custom image generator failed: {e}")
            return False

    target_cfg = active_cfg if active_cfg is not None else cfg
    if not target_cfg.gateway_url or not target_cfg.gateway_api_key:
        _logger.debug("No gateway image generation endpoint configured")
        return False

    try:
        from core.llm.utils import http_session

        headers = {
            "Authorization": f"Bearer {target_cfg.gateway_api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "prompt": prompt,
            "n": 1,
            "size": "1792x1024",  # 16:9 cinematic
            "response_format": "b64_json",
        }
        image_model = os.environ.get("IMAGE_MODEL") or getattr(target_cfg, "gateway_image_model", None)
        if image_model:
            payload["model"] = image_model
        resp = http_session.post(
            f"{target_cfg.gateway_url}/images/generations",
            headers=headers,
            json=payload,
            timeout=60,
        )
        if resp.status_code == 200:
            data = resp.json()
            item = data.get("data", [{}])[0]
            if "b64_json" in item:
                img_bytes = base64.b64decode(item["b64_json"])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(img_bytes)
                _logger.info(f"Hero image saved from gateway b64: {output_path.name}")
                return True
            elif "url" in item:
                img_resp = http_session.get(item["url"], timeout=30)
                if img_resp.status_code == 200:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(img_resp.content)
                    _logger.info(f"Hero image downloaded and saved: {output_path.name}")
                    return True
        _logger.warning(f"Gateway image generation returned HTTP {resp.status_code}")
    except Exception as e:
        _logger.warning(f"Gateway image generation error: {e}")

    return False


def process_hero_image(
    clean_query: str,
    active_cfg: Any,
    call_llm_fn: Any = None,
) -> tuple[str, Path | None, Path | None]:
    """Execute the full hero-image command orchestration flow.

    Args:
        clean_query: Query string with style prefix removed.
        active_cfg: VaultConfig instance (supports test mocking).
        call_llm_fn: Optional LLM invocation callable.

    Returns:
        tuple of (response_text, topic_path, image_path_if_saved).
    """
    llm = call_llm_fn or call_llm
    topics_dir = active_cfg.vault_root / "04 - Permanent" / "topics"
    topic_slug, topic_path = find_topic_note(clean_query, topics_dir)

    if topic_path and topic_path.exists():
        topic_text = extract_topic_context(topic_path)
        rag_context = (
            f"NỘI DUNG TOPIC NOTE ĐƯỢC THAM CHIẾU [[{topic_slug}]]:\n"
            f"---\n{topic_text}\n---"
        )
    else:
        rag_context, _ = build_rag_context(clean_query)
        if not rag_context:
            rag_context = f"(Chủ đề cần tạo Hero Image: {clean_query})"

    style = WRITING_STYLES["hero-image"]
    prompt = _RESPONSE_PROMPT.format(
        style_instruction=style["system"],
        rag_context=rag_context,
        query=clean_query,
    )

    response = llm(prompt, task="synthesis")
    if not response:
        return "", topic_path, None

    # Determine image details
    image_name = f"{topic_slug}_hero.jpg"
    attachments_dir = active_cfg.attachments_dir
    attachments_dir.mkdir(parents=True, exist_ok=True)
    image_path = attachments_dir / image_name

    image_prompt = extract_image_prompt(response)
    image_generated = generate_hero_image(image_prompt, image_path, active_cfg=active_cfg)

    if image_generated:
        log("image", f"Hero image generated: {image_name}")
        # Seamlessly embed beneath H1 in topic note if note exists
        if topic_path and topic_path.exists():
            try:
                original_text = topic_path.read_text(encoding="utf-8")
                updated_text = embed_hero_image_in_topic(original_text, image_name)
                if updated_text != original_text:
                    topic_path.write_text(updated_text, encoding="utf-8")
                    _logger.info(f"Embedded {image_name} beneath H1 in {topic_path.name}")
                    log("compile", f"Hero image embedded in topic: {topic_path.stem}")
            except OSError as e:
                _logger.error(f"Failed to embed hero image in topic note: {e}")

        # Ensure image preview embed is at top of response for Command.md
        if f"![[{image_name}" not in response:
            response = f"![[{image_name}|100%]]\n\n" + response
    else:
        # If image generation wasn't performed, append info notice
        if f"![[{image_name}" not in response:
            response = f"> ℹ️ **Hero Banner Placeholder:** `![[{image_name}|100%]]`\n\n" + response

    return response, topic_path, (image_path if image_generated else None)
