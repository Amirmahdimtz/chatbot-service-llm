"""Infrastructure-only Qdrant readiness and REST connectivity checks."""

from __future__ import annotations

import httpx

from src.infrastructure.di.inject import inject
from src.infrastructure.utils.config_reader import ConfigReader


@inject
class QdrantProvider:
    def __init__(self, config_reader: ConfigReader) -> None:
        url = config_reader.get("vector.url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ValueError("Qdrant URL is not configured; set CHATBOT_QDRANT_URL")
        self._base_url = url.rstrip("/")
        self._timeout = float(config_reader.get("vector.timeout_seconds", 5))
        if not 0 < self._timeout <= 120:
            raise ValueError("Qdrant timeout must be between 0 and 120 seconds")

    async def check_ready_async(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
                response = await client.get(f"{self._base_url}/readyz")
                return response.status_code == 200
        except httpx.RequestError:
            return False

    async def check_api_async(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
                response = await client.get(f"{self._base_url}/collections")
                if response.status_code != 200:
                    return False
                payload = response.json()
                return isinstance(payload, dict) and isinstance(payload.get("result"), dict) and isinstance(
                    payload["result"].get("collections"), list
                )
        except (httpx.RequestError, ValueError):
            return False
