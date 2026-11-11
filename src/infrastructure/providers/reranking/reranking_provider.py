"""Bounded local llama.cpp reranking using the /v1/rerank endpoint."""
from __future__ import annotations

import asyncio
import math
import httpx

from src.infrastructure.di.inject import inject
from src.infrastructure.utils.config_reader import ConfigReader


class RerankingError(RuntimeError):
    pass


@inject
class RerankingProvider:
    def __init__(self, config_reader: ConfigReader) -> None:
        self._url = str(config_reader.get("reranking.base_url", "")).rstrip("/")
        if self._url and not self._url.startswith(("http://", "https://")):
            raise ValueError("Invalid reranker endpoint")
        self.model_version = str(config_reader.get("reranking.model_version", "BGE-reranker-v2-m3"))
        self._timeout = float(config_reader.get("reranking.timeout_seconds", 180))
        self._max_candidates = int(config_reader.get("reranking.max_candidates", 20))
        self._api_key = str(config_reader.get("reranking.api_key", ""))
        if not 1 <= self._max_candidates <= 100 or not 1 <= self._timeout <= 600:
            raise ValueError("Invalid reranking limits")
        self._slots = asyncio.Semaphore(1)

    async def rerank_async(self, query: str, texts: list[str]) -> list[tuple[int, float]]:
        if not texts:
            return []
        if not self._url or not query.strip() or len(texts) > self._max_candidates:
            raise RerankingError("RERANKING_UNAVAILABLE")
        async with self._slots:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self._timeout, connect=5.0), trust_env=False,
                    headers={"Authorization": f"Bearer {self._api_key}"} if self._api_key else {},
                ) as client:
                    response = await client.post(
                        f"{self._url}/v1/rerank", json={"query": query, "documents": texts, "top_n": len(texts)}
                    )
                    if response.status_code != 200:
                        raise RerankingError("RERANKING_UNAVAILABLE")
                    data = response.json()
                results = data.get("results") if isinstance(data, dict) else data
                if not isinstance(results, list) or len(results) != len(texts):
                    raise RerankingError("RERANKING_INVALID_RESPONSE")
                scores = []
                for item in results:
                    idx = item.get("index")
                    score = item.get("relevance_score", item.get("score"))
                    if type(idx) is not int or not 0 <= idx < len(texts) or type(score) not in (int, float) or not math.isfinite(score):
                        raise RerankingError("RERANKING_INVALID_RESPONSE")
                    scores.append((idx, float(score)))
                if len({idx for idx, _ in scores}) != len(texts):
                    raise RerankingError("RERANKING_INVALID_RESPONSE")
                return sorted(scores, key=lambda item: (-item[1], item[0]))
            except (httpx.RequestError, ValueError, TypeError, AttributeError) as exc:
                raise RerankingError("RERANKING_UNAVAILABLE") from exc
