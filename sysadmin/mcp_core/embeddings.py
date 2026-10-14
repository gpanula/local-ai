"""Embedding generation module for the Local AI lesson-learning system.

Generates dense vector embeddings using a local Ollama instance (defaulting to
``nomic-embed-text:latest``, 768 dimensions). Uses Ollama's modern batch ``/api/embed``
endpoint with graceful fallback. All functions degrade safely without raising exceptions
if Ollama is offline or the embedding model is unavailable.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, List, Optional

DEFAULT_EMBEDDING_MODEL = "nomic-embed-text:latest"
DEFAULT_EMBEDDING_DIMENSIONS = 768


def _get_ollama_host(host: Optional[str] = None) -> str:
    """Resolve and validate the Ollama host URL."""
    raw = host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raw = f"http://{raw}"
    return raw.rstrip("/")


def _normalize_text_for_embedding(text: str) -> str:
    """Normalize input text for dense embedding generation.

    Preserves sentence structure, punctuation, and casing while stripping leading/trailing
    whitespace and collapsing duplicate whitespace runs.
    """
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def embed_texts(
    texts: List[str],
    model: str = DEFAULT_EMBEDDING_MODEL,
    host: Optional[str] = None,
    timeout: int = 30,
) -> List[Optional[List[float]]]:
    """Generate dense vector embeddings for a batch of text strings.

    Args:
        texts: List of text strings to embed.
        model: Ollama embedding model name.
        host: Optional Ollama host override (defaults to $OLLAMA_HOST).
        timeout: HTTP request timeout in seconds.

    Returns:
        List of float lists (each matching model dimensionality) or None for failed items.
    """
    if not texts:
        return []

    cleaned = [_normalize_text_for_embedding(t) for t in texts]
    # Check if all inputs are empty
    valid_indices = [i for i, t in enumerate(cleaned) if t]
    if not valid_indices:
        return [None] * len(texts)

    base_url = _get_ollama_host(host)
    valid_texts = [cleaned[i] for i in valid_indices]

    results: List[Optional[List[float]]] = [None] * len(texts)

    # Primary path: Ollama /api/embed (batch capable)
    try:
        url = f"{base_url}/api/embed"
        req = urllib.request.Request(
            url,
            data=json.dumps({"model": model, "input": valid_texts}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            embeddings = payload.get("embeddings", [])
            for idx, orig_pos in enumerate(valid_indices):
                if idx < len(embeddings) and isinstance(embeddings[idx], list):
                    results[orig_pos] = [float(v) for v in embeddings[idx]]
        return results
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, OSError):
        pass

    # Secondary fallback path: /api/embeddings (single item iteration)
    for idx, orig_pos in enumerate(valid_indices):
        text_item = valid_texts[idx]
        try:
            url = f"{base_url}/api/embeddings"
            req = urllib.request.Request(
                url,
                data=json.dumps({"model": model, "prompt": text_item}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                emb = payload.get("embedding")
                if isinstance(emb, list):
                    results[orig_pos] = [float(v) for v in emb]
        except Exception:
            results[orig_pos] = None

    return results


def embed_text(
    text: str,
    model: str = DEFAULT_EMBEDDING_MODEL,
    host: Optional[str] = None,
    timeout: int = 30,
) -> Optional[List[float]]:
    """Generate a dense vector embedding for a single text string.

    Args:
        text: Text string to embed.
        model: Ollama embedding model name.
        host: Optional Ollama host override.
        timeout: HTTP request timeout in seconds.

    Returns:
        List of floats (length 768 for nomic-embed-text) or None on error/empty input.
    """
    if not text or not _normalize_text_for_embedding(text):
        return None
    res = embed_texts([text], model=model, host=host, timeout=timeout)
    return res[0] if res else None


# Backward-compatibility alias
get_embedding = embed_text
