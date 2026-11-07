"""
Unit & integration tests for GeminiEmbeddingService (Stage 6, Milestone 2).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from google.genai.errors import ClientError

from app.config import settings
from app.services.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingError,
    EmbeddingRateLimitError,
    GeminiEmbeddingService,
    _sanitize_error,
)


# ---------------------------------------------------------------------------
# Unit tests (Mocked API)
# ---------------------------------------------------------------------------

def test_sanitize_error_removes_api_key():
    fake_key = "AIzaSyTestKey1234567890"
    with patch.object(settings, "GEMINI_API_KEY", fake_key):
        err = f"API failed with {fake_key} and key=SecretValue"
        cleaned = _sanitize_error(err)
        assert fake_key not in cleaned
        assert "[REDACTED_API_KEY]" in cleaned
        assert "key=[REDACTED]" in cleaned


def test_missing_api_key_raises_config_error():
    service = GeminiEmbeddingService(api_key="")
    with pytest.raises(EmbeddingConfigurationError):
        service._get_client()


@pytest.mark.asyncio
async def test_embed_empty_texts_returns_empty():
    service = GeminiEmbeddingService()
    res = await service.embed_chunks([])
    assert res == []


@pytest.mark.asyncio
async def test_embed_batching_and_order():
    """Verify that 10 chunks with batch_size=3 are split into 4 batches and combined in order."""
    service = GeminiEmbeddingService(batch_size=3, dimensions=768)

    mock_client = MagicMock()
    # Mock embed_content to return embeddings containing the text index
    async def mock_embed_content(model, contents, config):
        res = MagicMock()
        res.embeddings = [
            MagicMock(values=[float(int(c.split()[1]))] * 768)
            for c in contents
        ]
        return res

    mock_client.aio.models.embed_content = AsyncMock(side_effect=mock_embed_content)

    with patch.object(service, "_get_client", return_value=mock_client):
        texts = [f"Chunk {i}" for i in range(10)]
        results = await service.embed_chunks(texts)

        assert len(results) == 10
        assert mock_client.aio.models.embed_content.call_count == 4  # 3 + 3 + 3 + 1
        for i, emb in enumerate(results):
            assert len(emb) == 768
            assert emb[0] == float(i)


@pytest.mark.asyncio
async def test_retry_on_429_rate_limit():
    """Verify exponential backoff retries when 429 is encountered."""
    service = GeminiEmbeddingService(batch_size=5, max_retries=2, base_backoff_seconds=0.01)

    call_count = 0
    mock_client = MagicMock()

    async def mock_embed(model, contents, config):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            resp = MagicMock()
            resp.status_code = 429
            raise ClientError(429, {"error": {"message": "Rate limit exceeded"}}, resp)
        res = MagicMock()
        res.embeddings = [MagicMock(values=[0.1] * 768) for _ in contents]
        return res

    mock_client.aio.models.embed_content = AsyncMock(side_effect=mock_embed)

    with patch.object(service, "_get_client", return_value=mock_client):
        results = await service.embed_chunks(["Test chunk"])
        assert len(results) == 1
        assert call_count == 2


# ---------------------------------------------------------------------------
# Live API Integration Test (runs when GEMINI_API_KEY is available)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_embed_20_chunks_and_query():
    """
    Live test against Gemini API:
    Embeds 20 chunks (batch_size=8 → 3 batches), checks length & 768 dimensions,
    then embeds 1 query with RETRIEVAL_QUERY.
    """
    if not settings.GEMINI_API_KEY:
        pytest.skip("GEMINI_API_KEY not configured; skipping live test.")

    service = GeminiEmbeddingService(batch_size=8, dimensions=768)

    sample_chunks = [
        f"Document sample chunk {i}: Architecture and vector search overview with page number {i % 5 + 1}."
        for i in range(20)
    ]

    embeddings = await service.embed_chunks(sample_chunks)
    assert len(embeddings) == 20
    for emb in embeddings:
        assert len(emb) == 768
        assert any(v != 0.0 for v in emb)  # not all zeros

    # Test single query embedding
    query_emb = await service.embed_query("How does vector search work?")
    assert len(query_emb) == 768
    assert any(v != 0.0 for v in query_emb)
