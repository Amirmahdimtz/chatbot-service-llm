"""Local llama.cpp HTTP connectivity; no generation or workflow in stage 2."""

from __future__ import annotations

import httpx

from src.infrastructure.di.inject import inject
from src.infrastructure.utils.config_reader import ConfigReader


@inject
class LlamaCppProvider:
    def __init__(self, config_reader: ConfigReader) -> None:
        url = config_reader.get("llm.base_url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ValueError("LLM URL is not configured; set CHATBOT_LLM_BASE_URL")
        self._base_url = url.rstrip("/")
        self._timeout = float(config_reader.get("llm.timeout_seconds", 10))
        if not 0 < self._timeout <= 300:
            raise ValueError("LLM timeout must be between 0 and 300 seconds")
        self._api_key = config_reader.get("llm.api_key", "")

    async def check_ready_async(self) -> bool:
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, trust_env=False, headers=headers) as client:
                health = await client.get(f"{self._base_url}/health")
                if health.status_code != 200:
                    return False
                models = await client.get(f"{self._base_url}/v1/models")
                if models.status_code != 200:
                    return False
                payload = models.json()
                return isinstance(payload, dict) and isinstance(payload.get("data"), list) and bool(payload["data"])
        except (httpx.RequestError, ValueError):
            return False
