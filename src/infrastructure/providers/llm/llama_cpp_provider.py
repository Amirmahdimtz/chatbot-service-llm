"""Local llama.cpp readiness and bounded async OpenAI-compatible chat streaming."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json

import httpx

from src.infrastructure.di.inject import inject
from src.infrastructure.utils.config_reader import ConfigReader


class LlmStreamError(RuntimeError):
    """Sanitized error code; never expose upstream response bodies or credentials."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@inject
class LlamaCppProvider:
    __di_singleton__ = True  # Limit CPU inference across injected ChatService instances.

    def __init__(self, config_reader: ConfigReader) -> None:
        url = config_reader.get("llm.base_url")
        if not isinstance(url, str) or (url and not url.startswith(("http://", "https://"))):
            raise ValueError("LLM URL is not configured; set CHATBOT_LLM_BASE_URL")
        self._base_url = url.rstrip("/")
        self._timeout = float(config_reader.get("llm.timeout_seconds", 120))
        if not 0 < self._timeout <= 600:
            raise ValueError("LLM timeout must be between 0 and 600 seconds")
        self._api_key = config_reader.get("llm.api_key", "")
        self._max_tokens = int(config_reader.get("llm.max_tokens", 256))
        if not 1 <= self._max_tokens <= 1024:
            raise ValueError("llm.max_tokens must be between 1 and 1024")
        concurrency = int(config_reader.get("llm.max_concurrent_requests", 1))
        if not 1 <= concurrency <= 4:
            raise ValueError("llm.max_concurrent_requests must be between 1 and 4")
        self._slots = asyncio.Semaphore(concurrency)
        model_name = config_reader.get("llm.model_name", "")
        self._model_name = model_name if isinstance(model_name, str) else ""

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

    async def check_ready_async(self) -> bool:
        if not self._base_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=self._timeout, trust_env=False, headers=self._headers()) as client:
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

    async def stream_chat_async(self, message: str) -> AsyncIterator[str]:
        if not self._base_url:
            raise LlmStreamError("LLM_UNAVAILABLE")
        # Never queue CPU inference indefinitely; a busy model yields a structured SSE error.
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=0.02)
        except TimeoutError as exc:
            raise LlmStreamError("LLM_BUSY") from exc
        try:
            body: dict = {
                "messages": [
                    {"role": "system", "content": "Be helpful and accurate. Respond in Persian to Persian questions."},
                    {"role": "user", "content": message},
                ],
                "stream": True,
                "max_tokens": self._max_tokens,
            }
            if self._model_name:
                body["model"] = self._model_name
            timeout = httpx.Timeout(connect=5.0, read=self._timeout, write=10.0, pool=5.0)
            try:
                async with asyncio.timeout(self._timeout):
                    async with httpx.AsyncClient(timeout=timeout, trust_env=False, headers=self._headers()) as client:
                        async with client.stream("POST", f"{self._base_url}/v1/chat/completions",
                                                 json=body, headers={"Accept": "text/event-stream"}) as response:
                            if response.status_code != 200:
                                raise LlmStreamError("LLM_UNAVAILABLE")
                            done = False
                            async for line in response.aiter_lines():
                                if not line or line.startswith(":"):
                                    continue
                                if not line.startswith("data:"):
                                    continue
                                data = line[5:].strip()
                                if data == "[DONE]":
                                    done = True
                                    break
                                if len(data) > 65536:
                                    raise LlmStreamError("LLM_BAD_RESPONSE")
                                try:
                                    packet = json.loads(data)
                                    choices = packet["choices"]
                                    delta = choices[0]["delta"]
                                    content = delta.get("content")
                                    if content is not None and not isinstance(content, str):
                                        raise ValueError("Invalid stream content")
                                except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                                    raise LlmStreamError("LLM_BAD_RESPONSE") from exc
                                if content:
                                    yield content
                            if not done:
                                raise LlmStreamError("LLM_BAD_RESPONSE")
            except (httpx.TimeoutException, TimeoutError) as exc:
                raise LlmStreamError("LLM_TIMEOUT") from exc
            except httpx.RequestError as exc:
                raise LlmStreamError("LLM_UNAVAILABLE") from exc
        finally:
            self._slots.release()
