"""Unit and integration tests for mcp_core.embeddings and nomic-embed-text validation."""

import math
from unittest.mock import MagicMock, patch
import pytest

from mcp_core.embeddings import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
    embed_text,
    embed_texts,
)


def cosine_sim(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def test_embed_text_empty_input():
    assert embed_text("") is None
    assert embed_text("   \n\t  ") is None


def test_embed_texts_empty_list():
    assert embed_texts([]) == []
    assert embed_texts(["", "   "]) == [None, None]


def test_embed_texts_offline_fallback():
    # Points to a non-existent port to guarantee network error
    res = embed_texts(["Test text"], host="http://127.0.0.1:59999", timeout=1)
    assert res == [None]


def test_embed_texts_mocked_batch():
    mock_cm = MagicMock()
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"embeddings": [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]}'
    mock_cm.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_cm):
        res = embed_texts(["First rule", "Second rule"], model="test-model")
        assert len(res) == 2
        assert res[0] == [0.1, 0.2, 0.3, 0.4]
        assert res[1] == [0.5, 0.6, 0.7, 0.8]


def test_nomic_embed_live_discrimination():
    """Live verification of resident nomic-embed-text model (Stage 2A Step 1 benchmark)."""
    # Sample lessons:
    # r1 & r2: duplicate rules with syntax/phrasing shift
    r1 = "Always enable set -euo pipefail and register an ERR trap for diagnostics."
    r2 = "Ensure set -euo pipefail is active and register an ERR trap in bash scripts."
    # r3: different domain entirely
    r3 = "Clinical trials database patient matching and oncology eligibility criteria."

    embs = embed_texts([r1, r2, r3])
    # If Ollama is not available in the test runner environment, skip live assertion
    if any(e is None for e in embs):
        pytest.skip("Local Ollama nomic-embed-text:latest is not reachable in test environment")

    assert len(embs[0]) == DEFAULT_EMBEDDING_DIMENSIONS
    assert len(embs[1]) == DEFAULT_EMBEDDING_DIMENSIONS
    assert len(embs[2]) == DEFAULT_EMBEDDING_DIMENSIONS

    sim_dup = cosine_sim(embs[0], embs[1])
    sim_unrelated = cosine_sim(embs[0], embs[2])

    print(f"\n[Stage 2A Benchmark] Duplicate cosine similarity: {sim_dup:.4f}")
    print(f"[Stage 2A Benchmark] Unrelated cosine similarity: {sim_unrelated:.4f}")

    # Duplicates should have high similarity (>0.85)
    assert sim_dup >= 0.85, f"Expected duplicate similarity >= 0.85, got {sim_dup}"
    # Unrelated rules should have low similarity (<0.60)
    assert sim_unrelated <= 0.60, f"Expected unrelated similarity <= 0.60, got {sim_unrelated}"
