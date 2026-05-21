from __future__ import annotations

import logging
import math
from typing import Any

import openai
from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from tdai_memory.config import EmbeddingConfig

logger = logging.getLogger(__name__)

_MODEL_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}

_DEFAULT_DIMENSIONS = 1536
_MAX_BATCH_SIZE = 256


def _sanitize_and_normalize(vec: list[float]) -> list[float]:
    sanitized = [0.0 if (v is None or math.isnan(v) or math.isinf(v)) else v for v in vec]
    sq_norm = sum(v * v for v in sanitized)
    if sq_norm > 0:
        scale = 1.0 / math.sqrt(sq_norm)
        sanitized = [v * scale for v in sanitized]
    return sanitized


class EmbeddingNotReadyError(Exception):
    pass


class EmbeddingService:
    def __init__(self, config: EmbeddingConfig) -> None:
        self._model = config.model
        self._max_input_chars = config.max_input_chars
        self._dimensions_override = config.dimensions
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout_ms / 1000.0 if config.timeout_ms > 0 else 30.0,
        )

    async def embed(self, text: str) -> list[float]:
        text = text[: self._max_input_chars]
        return _sanitize_and_normalize(await self._embed_single(text))

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        truncated = [t[: self._max_input_chars] for t in texts]
        results: list[list[float]] = []
        for i in range(0, len(truncated), _MAX_BATCH_SIZE):
            batch = truncated[i : i + _MAX_BATCH_SIZE]
            results.extend(await self._embed_batch(batch))
        return [_sanitize_and_normalize(r) for r in results]

    def get_dimensions(self) -> int:
        if self._dimensions_override > 0:
            return self._dimensions_override
        return _MODEL_DIMENSIONS.get(self._model, _DEFAULT_DIMENSIONS)

    def get_provider_info(self) -> dict[str, str]:
        return {"provider": "openai", "model": self._model}

    def is_ready(self) -> bool:
        return True

    async def close(self) -> None:
        await self._client.close()

    @retry(
        retry=retry_if_exception_type(
            (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30),
    )
    async def _embed_single(self, text: str) -> list[float]:
        try:
            kwargs: dict[str, Any] = {"model": self._model, "input": text}
            if self._dimensions_override > 0:
                kwargs["dimensions"] = self._dimensions_override
            response = await self._client.embeddings.create(**kwargs)
            return response.data[0].embedding
        except openai.BadRequestError as e:
            error_msg = str(e).lower()
            if "maximum context length" in error_msg or "too long" in error_msg:
                logger.warning(
                    "Embedding text too long (%d chars), truncating by half and retrying",
                    len(text),
                )
                kwargs["input"] = text[: len(text) // 2]
                response = await self._client.embeddings.create(**kwargs)
                return response.data[0].embedding
            raise EmbeddingNotReadyError(f"Embedding API bad request: {e}") from e

    @retry(
        retry=retry_if_exception_type(
            (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30),
    )
    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        try:
            kwargs: dict[str, Any] = {"model": self._model, "input": texts}
            if self._dimensions_override > 0:
                kwargs["dimensions"] = self._dimensions_override
            response = await self._client.embeddings.create(**kwargs)
            return [d.embedding for d in response.data]
        except openai.BadRequestError as e:
            error_msg = str(e).lower()
            if "maximum context length" in error_msg or "too long" in error_msg:
                logger.warning(
                    "Batch embedding too long, truncating each text by half and retrying"
                )
                kwargs["input"] = [t[: len(t) // 2] for t in texts]
                response = await self._client.embeddings.create(**kwargs)
                return [d.embedding for d in response.data]
            raise EmbeddingNotReadyError(
                f"Embedding API bad request during batch: {e}"
            ) from e
