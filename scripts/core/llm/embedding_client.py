"""VvC Second Brain — AI Gateway Embedding Client.

Centralized Deep Module for fetching L2-normalized vector embeddings from AI Gateway.
Features exponential backoff retries for transient errors and immediate abort on fatal errors.
"""

from __future__ import annotations

import logging
import time

import numpy as np

try:
    import requests
except ImportError:
    requests = None

from core.config import cfg
from core.llm.utils import http_session

_logger = logging.getLogger("vvc.llm.embedding")


def _handle_http_error(
    he: requests.exceptions.HTTPError,
    attempt: int,
    max_retries: int,
    backoff_factor: float,
) -> bool:
    """Handle HTTP errors, determining if retry is appropriate."""
    status_code = he.response.status_code if he.response is not None else 500
    if status_code in (400, 401, 403, 404):
        _logger.error(
            f"[Embedding] Fatal API error {status_code} fetching embedding. Aborting. Error: {he}"
        )
        return False
    if attempt < max_retries - 1:
        sleep_time = backoff_factor ** (attempt + 1)
        _logger.warning(
            f"[Embedding] Transient HTTP {status_code} (attempt {attempt+1}/{max_retries}). "
            f"Retrying in {sleep_time:.1f}s... Error: {he}"
        )
        time.sleep(sleep_time)
        return True
    _logger.error(
        f"[Embedding] Failed to fetch embedding after {max_retries} attempts "
        f"due to HTTP {status_code}: {he}"
    )
    return False


def _handle_network_error(
    te: Exception,
    attempt: int,
    max_retries: int,
    backoff_factor: float,
) -> None:
    """Handle connection drops and timeout retries."""
    if attempt < max_retries - 1:
        sleep_time = backoff_factor ** (attempt + 1)
        _logger.warning(
            f"[Embedding] Network/Timeout error (attempt {attempt+1}/{max_retries}). "
            f"Retrying in {sleep_time:.1f}s... Error: {te}"
        )
        time.sleep(sleep_time)
    else:
        _logger.error(
            f"[Embedding] Failed to fetch embedding after {max_retries} attempts "
            f"due to Network/Timeout: {te}"
        )


def get_embedding(
    text: str,
    *,
    model: str = "gemini-embed",
    timeout: float = 15.0,
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    max_chars: int = 2000,
) -> np.ndarray | None:
    """Fetch L2-normalized embedding vector from AI Gateway."""
    if not cfg.gateway_url or not cfg.gateway_api_key or requests is None:
        return None

    url = f"{cfg.gateway_url.rstrip('/')}/embeddings"
    headers = {
        "Authorization": f"Bearer {cfg.gateway_api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "input": [text[:max_chars]]}
    session = http_session if http_session is not None else requests

    for attempt in range(max_retries):
        try:
            resp = session.post(url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            values = resp.json()["data"][0]["embedding"]
            emb = np.array(values, dtype=np.float32)
            norm = np.linalg.norm(emb)
            return emb / norm if norm > 0 else emb
        except requests.exceptions.HTTPError as he:
            if not _handle_http_error(he, attempt, max_retries, backoff_factor):
                break
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as te:
            _handle_network_error(te, attempt, max_retries, backoff_factor)
        except Exception as e:
            _logger.error(f"[Embedding] Unexpected error fetching embedding: {e}")
            break

    return None


def get_embedding_via_gateway(text: str, timeout: float = 15.0) -> list[float] | None:
    """Backward-compatible wrapper returning python list of floats or None."""
    emb = get_embedding(text, timeout=timeout)
    return emb.tolist() if emb is not None else None
