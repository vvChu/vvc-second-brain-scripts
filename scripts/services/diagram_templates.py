"""VvC Second Brain — Diagram Template Library & Matching Engine.

Loads diagram templates and performs semantic template selection
via AI Gateway embeddings with keyword frequency fallback.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.config import cfg

_logger = logging.getLogger("vvc.diagram.templates")

_TEMPLATES_PATH = Path(__file__).parent.parent / "resources" / "diagram_templates.yaml"
_templates_cache: dict[str, Any] | None = None


def load_templates() -> dict[str, Any]:
    """Load diagram templates from YAML config (cached)."""
    global _templates_cache
    if _templates_cache is not None:
        return _templates_cache

    if not _TEMPLATES_PATH.exists():
        _logger.warning(f"Template library not found: {_TEMPLATES_PATH}")
        _templates_cache = {}
        return _templates_cache

    try:
        import yaml
        with open(_TEMPLATES_PATH, encoding="utf-8") as f:
            _templates_cache = yaml.safe_load(f) or {}
        _logger.info(f"Loaded diagram templates: {list(_templates_cache.keys())}")
    except Exception as e:
        _logger.warning(f"Failed to load diagram templates: {e}")
        _templates_cache = {}

    return _templates_cache


def _fetch_template_embeddings(texts: list[str]) -> list[Any] | None:
    """Fetch embeddings from AI Gateway for context and candidate templates."""
    try:
        import numpy as np
        import requests as req_lib
    except ImportError:
        return None

    if not cfg.gateway_url or not cfg.gateway_api_key:
        return None

    url = f"{cfg.gateway_url.rstrip('/')}/embeddings"
    headers = {
        "Authorization": f"Bearer {cfg.gateway_api_key}",
        "Content-Type": "application/json",
    }
    try:
        payload = {"model": "gemini-embed", "input": texts}
        resp = req_lib.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()

        raw_embs = [
            np.array(d["embedding"], dtype=np.float32)
            for d in resp.json()["data"]
        ]
        for i in range(len(raw_embs)):
            norm = np.linalg.norm(raw_embs[i])
            if norm > 0:
                raw_embs[i] /= norm
        return raw_embs
    except Exception as e:
        _logger.debug(f"Embedding request failed: {e}")
        return None


def _find_best_embedding_match(
    context_emb: Any,
    template_embs: list[Any],
    template_names: list[str],
) -> tuple[str, float] | None:
    """Compute cosine similarity and return best matching template."""
    import numpy as np
    best_name = None
    best_score = 0.0

    for i, name in enumerate(template_names):
        score = float(np.dot(context_emb, template_embs[i]))
        if score > best_score:
            best_score = score
            best_name = name

    if best_score >= 0.35 and best_name is not None:
        return (best_name, best_score)
    return None


def _select_by_embedding(
    context: str,
    section: dict[str, Any],
) -> tuple[str, float] | None:
    """Select template using embedding cosine similarity."""
    texts_to_embed = [context[:500]]
    template_names = []
    for name, tmpl in section.items():
        desc = tmpl.get("description", "")
        keywords = " ".join(tmpl.get("keywords", []))
        texts_to_embed.append(f"{desc} {keywords}")
        template_names.append(name)

    if not template_names:
        return None

    embeddings = _fetch_template_embeddings(texts_to_embed)
    if not embeddings or len(embeddings) < 2:
        return None

    return _find_best_embedding_match(embeddings[0], embeddings[1:], template_names)


def _select_by_keywords(context: str, section: dict[str, Any]) -> str | None:
    """Fallback: select template by keyword frequency matching."""
    context_lower = context.lower()
    best_name = None
    best_hits = 0

    for name, tmpl in section.items():
        keywords = tmpl.get("keywords", [])
        hits = sum(1 for kw in keywords if kw.lower() in context_lower)
        if hits > best_hits:
            best_hits = hits
            best_name = name

    return best_name if best_hits >= 2 else None


def select_template(
    context: str,
    diagram_type: str = "mermaid",
) -> dict[str, Any] | None:
    """Select the best-matching template for the given context."""
    templates = load_templates()
    section = templates.get(diagram_type, {})
    if not section:
        return None

    best = _select_by_embedding(context, section)
    if best:
        _logger.info(f"Template selected via embedding: {best[0]} (score={best[1]:.3f})")
        return section[best[0]]

    best_kw = _select_by_keywords(context, section)
    if best_kw:
        _logger.info(f"Template selected via keywords: {best_kw}")
        return section[best_kw]

    return None
