"""
Stage 6 - Milestone 2: Gemini Embeddings Service.

Provides batch embedding generation using the official google-genai SDK
with task type support (RETRIEVAL_DOCUMENT vs RETRIEVAL_QUERY),
automatic batching, rate-limit retries with exponential backoff,
concurrency limiting, and sensitive key redaction.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import List, Optional

from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError, ServerError

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class EmbeddingError(Exception):
    """Base exception for embedding failures."""
    pass


class EmbeddingConfigurationError(EmbeddingError):
    """Raised when API key or model configuration is missing/invalid."""
    pass


class EmbeddingRateLimitError(EmbeddingError):
    """Raised when rate limits are exceeded after exhausted retries."""
    pass


def _sanitize_error(msg: str) -> str:
    """Ensure API key and internal query parameters are never exposed."""
    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY in msg:
        msg = msg.replace(settings.GEMINI_API_KEY, "[REDACTED_API_KEY]")
    # Redact common key patterns
    msg = re.sub(r"key=[A-Za-z0-9_\-]+", "key=[REDACTED]", msg)
    return msg


# ---------------------------------------------------------------------------
# Embedding Service
# ---------------------------------------------------------------------------

class GeminiEmbeddingService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        dimensions: Optional[int] = None,
        batch_size: Optional[int] = None,
        concurrency: Optional[int] = None,
        max_retries: int = 5,
        base_backoff_seconds: float = 1.0,
    ):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model = model or settings.EMBED_MODEL
        self.dimensions = dimensions or settings.EMBED_DIMENSIONS
        self.batch_size = batch_size or settings.EMBED_BATCH_SIZE
        self.concurrency = concurrency or settings.EMBED_CONCURRENCY
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds

        self._client: Optional[genai.Client] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(self.concurrency)

    def _get_client(self) -> genai.Client:
        if not self.api_key:
            raise EmbeddingConfigurationError(
                "Gemini API key is not configured. Please set GEMINI_API_KEY in environment."
            )
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if self._client is None or self._loop != current_loop:
            self._client = genai.Client(api_key=self.api_key)
            self._loop = current_loop
            self._semaphore = asyncio.Semaphore(self.concurrency)

        return self._client

    @property
    def semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.concurrency)
        return self._semaphore

    async def _embed_batch_with_retry(
        self,
        batch_texts: List[str],
        task_type: str,
    ) -> List[List[float]]:
        """Call embed_content for a single batch with exponential backoff on 429/5xx."""
        client = self._get_client()
        cfg = types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=self.dimensions,
        )

        attempt = 0
        while True:
            attempt += 1
            try:
                async with self.semaphore:
                    res = await client.aio.models.embed_content(
                        model=self.model,
                        contents=batch_texts,
                        config=cfg,
                    )
                if not res.embeddings:
                    raise EmbeddingError(f"Embedding API returned empty results for batch of size {len(batch_texts)}")
                return [list(e.values) for e in res.embeddings]

            except ClientError as ce:
                # 429 Too Many Requests: retry with backoff
                if ce.code == 429:
                    if attempt > self.max_retries:
                        sanitized = _sanitize_error(str(ce))
                        raise EmbeddingRateLimitError(
                            f"Gemini embedding rate limit exceeded after {self.max_retries} retries: {sanitized}"
                        ) from ce
                    delay = (self.base_backoff_seconds * (2 ** (attempt - 1))) + random.uniform(0.1, 0.5)
                    logger.warning(
                        "Embedding 429 rate limit hit (attempt %d/%d). Backing off %.2fs...",
                        attempt, self.max_retries, delay
                    )
                    await asyncio.sleep(delay)
                    continue
                # Other 4xx client errors (400, 401, 404): non-retryable
                sanitized = _sanitize_error(str(ce))
                raise EmbeddingError(f"Embedding ClientError ({ce.code}): {sanitized}") from ce

            except ServerError as se:
                # 5xx server errors: transient, retry
                if attempt > self.max_retries:
                    sanitized = _sanitize_error(str(se))
                    raise EmbeddingError(
                        f"Gemini embedding 5xx server error after {self.max_retries} retries: {sanitized}"
                    ) from se
                delay = (self.base_backoff_seconds * (2 ** (attempt - 1))) + random.uniform(0.1, 0.5)
                logger.warning(
                    "Embedding 5xx error (%s) on attempt %d/%d. Retrying in %.2fs...",
                    se.code, attempt, self.max_retries, delay
                )
                await asyncio.sleep(delay)
                continue

            except APIError as ae:
                sanitized = _sanitize_error(str(ae))
                raise EmbeddingError(f"Gemini embedding API error: {sanitized}") from ae

            except Exception as ex:
                sanitized = _sanitize_error(str(ex))
                raise EmbeddingError(f"Unexpected embedding error: {sanitized}") from ex

    async def embed_chunks(
        self,
        texts: List[str],
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> List[List[float]]:
        """
        Embed a list of chunk texts. Automatically batches requests into
        batches of up to self.batch_size, runs concurrently up to self.concurrency,
        and returns embeddings ordered matching the input texts.
        """
        if not texts:
            return []

        # Split texts into batches
        batches = [
            texts[i : i + self.batch_size]
            for i in range(0, len(texts), self.batch_size)
        ]

        logger.info(
            "Embedding %d texts across %d batch(es) (batch_size=%d, concurrency=%d, model=%s, dim=%d)",
            len(texts), len(batches), self.batch_size, self.concurrency, self.model, self.dimensions,
        )

        # Execute batches with bounded concurrency
        tasks = [
            self._embed_batch_with_retry(batch, task_type)
            for batch in batches
        ]
        results = await asyncio.gather(*tasks)

        # Flatten batch results in original order
        all_embeddings: List[List[float]] = []
        for batch_embs in results:
            all_embeddings.extend(batch_embs)

        if len(all_embeddings) != len(texts):
            raise EmbeddingError(
                f"Mismatch in embedding results count: expected {len(texts)}, got {len(all_embeddings)}"
            )

        return all_embeddings

    async def embed_query(self, query: str) -> List[float]:
        """Embed a single search query text using RETRIEVAL_QUERY task type."""
        trimmed = query.strip()
        if not trimmed:
            raise ValueError("Query text cannot be empty for embedding.")

        embs = await self._embed_batch_with_retry([trimmed], task_type="RETRIEVAL_QUERY")
        if not embs or len(embs[0]) != self.dimensions:
            raise EmbeddingError(
                f"Expected {self.dimensions}-dimensional embedding for query, got {len(embs[0]) if embs else 0}"
            )
        return embs[0]


# ---------------------------------------------------------------------------
# Global accessor
# ---------------------------------------------------------------------------

_embedding_service: Optional[GeminiEmbeddingService] = None


def get_embedding_service() -> GeminiEmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = GeminiEmbeddingService()
    return _embedding_service
