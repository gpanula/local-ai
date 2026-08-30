"""Embedding generation via the local Ollama HTTP API.

Phase 4.02: ``get_embedding`` produces a float vector for a text snippet using
Ollama's ``/api/embed`` endpoint. It talks directly to the Ollama HTTP API
(mirroring ``mcp_ollama/server.py``'s ``_http_request`` pattern) rather than
going through the MCP server, since no embedding tool is exposed there.

The default model is ``nomic-embed-text`` (768-dim), pulled via
``ollama pull nomic-embed-text``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


def _validate_ollama_host(raw: str) -> str:
    """Validate that OLLAMA_HOST has an http/https scheme and is a loopback/private address."""
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"OLLAMA_HOST must use http or https scheme, got: {raw!r}")
    hostname = parsed.hostname or ""
    if hostname not in ("127.0.0.1", "localhost", "::1"):
        import ipaddress

        try:
            addr = ipaddress.ip_address(hostname)
            if not (addr.is_loopback or addr.is_private):
                raise ValueError(f"OLLAMA_HOST resolves to a non-private address: {hostname}")
        except ValueError:
            raise ValueError(f"OLLAMA_HOST hostname must be localhost/loopback or a private IP: {hostname}")
    return raw.rstrip("/")


OLLAMA_HOST = _validate_ollama_host(os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))


def _http_request(endpoint: str, method: str = "GET", data: Optional[Dict[str, Any]] = None, timeout: int = 120) -> Dict[str, Any]:
    """Perform a JSON HTTP request against the Ollama API and return parsed JSON."""
    url = f"{OLLAMA_HOST}{endpoint}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    body = json.dumps(data).encode("utf-8") if data is not None else None
    try:
        with urllib.request.urlopen(req, data=body, timeout=timeout) as response:
            res_body = response.read().decode("utf-8")
            if not res_body.strip():
                return {}
            return json.loads(res_body)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama API HTTP {e.code} ({url}): {e.reason} - {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to connect to Ollama at {url}: {e}")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Ollama API request error ({url}): {e}")


def get_embedding(text: str, model: str = "nomic-embed-text") -> List[float]:
    """Return a float embedding vector for ``text`` via Ollama's ``/api/embed``.

    Raises ``RuntimeError`` on any failure (connection, HTTP error, or a missing
    embedding in the response).
    """
    if not text or not text.strip():
        raise ValueError("Cannot embed empty text")

    data = _http_request(
        "/api/embed",
        method="POST",
        data={"model": model, "input": text},
    )

    embeddings = data.get("embeddings") or []
    if not embeddings or not embeddings[0]:
        raise RuntimeError(f"Ollama returned no embedding for model {model!r}")

    vector = embeddings[0]
    if not isinstance(vector, list) or not all(isinstance(v, (int, float)) for v in vector):
        raise RuntimeError(f"Ollama returned a malformed embedding for model {model!r}")

    return [float(v) for v in vector]
