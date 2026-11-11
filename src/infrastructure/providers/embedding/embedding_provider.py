"""Local llama.cpp OpenAI-compatible embedding endpoint, with validated output."""
from __future__ import annotations

import asyncio
import math
import httpx

from src.infrastructure.di.inject import inject
from src.infrastructure.utils.config_reader import ConfigReader


class EmbeddingError(RuntimeError):
    pass


@inject
class EmbeddingProvider:
    def __init__(self, config_reader: ConfigReader) -> None:
        self._url = str(config_reader.get("embedding.base_url", "")).rstrip("/")
        if self._url and not self._url.startswith(("http://", "https://")):
            raise ValueError("Invalid embedding endpoint")
        self._model = str(config_reader.get("embedding.model_name", ""))
        self.model_version = str(config_reader.get("embedding.model_version", "Qwen3-Embedding-0.6B"))
        self.dimension = int(config_reader.get("embedding.dimension", 1024))
        self._batch_size = int(config_reader.get("embedding.batch_size", 4))
        self._timeout = float(config_reader.get("embedding.timeout_seconds", 180))
        self._api_key = str(config_reader.get("embedding.api_key", ""))
        if not 1 <= self.dimension <= 4096 or not 1 <= self._batch_size <= 16 or not 1 <= self._timeout <= 600:
            raise ValueError("Invalid embedding limits")
        self._slots = asyncio.Semaphore(1)

    async def embed_async(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self._url or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise EmbeddingError("EMBEDDING_UNAVAILABLE")
        output: list[list[float]] = []
        async with self._slots:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self._timeout, connect=5.0), trust_env=False,
                    headers={"Authorization": f"Bearer {self._api_key}"} if self._api_key else {},
                ) as client:
                    for start in range(0, len(texts), self._batch_size):
                        subset = texts[start:start + self._batch_size]
                        body = {"input": subset, "encoding_format": "float"}
                        if self._model:
                            body["model"] = self._model
                        response = await client.post(f"{self._url}/v1/embeddings", json=body)
                        if response.status_code != 200:
                            raise EmbeddingError("EMBEDDING_UNAVAILABLE")
                        data = response.json().get("data")
                        if not isinstance(data, list) or len(data) != len(subset):
                            raise EmbeddingError("EMBEDDING_INVALID_RESPONSE")
                        ordered = sorted(data, key=lambda item: item.get("index", -1))
                        for position, item in enumerate(ordered):
                            if item.get("index") != position:
                                raise EmbeddingError("EMBEDDING_INVALID_RESPONSE")
                            vector = item.get("embedding")
                            if not isinstance(vector, list) or len(vector) != self.dimension or any(
                                not isinstance(x, (float, int)) or isinstance(x, bool) or not math.isfinite(x)
                                for x in vector
                            ):
                                raise EmbeddingError("EMBEDDING_DIMENSION_MISMATCH")
                            output.append([float(x) for x in vector])
            except (httpx.RequestError, ValueError, TypeError, KeyError) as exc:
                raise EmbeddingError("EMBEDDING_UNAVAILABLE") from exc
        return output
