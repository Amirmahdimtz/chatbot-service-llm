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
    __di_singleton__ = True

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
        self._enable_thinking = config_reader.get("llm.enable_thinking", True)
        if not isinstance(self._enable_thinking, bool):
            raise ValueError("llm.enable_thinking must be a boolean")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

    async def check_ready_async(self) -> bool:
        return await self.readiness_status_async() == "ready"

    async def readiness_status_async(self) -> str:
        if not self._base_url:
            return "not_configured"
        try:
            async with httpx.AsyncClient(
                timeout=min(self._timeout, 10.0), trust_env=False, headers=self._headers()
            ) as client:
                health = await client.get(f"{self._base_url}/health")
                if health.status_code in (401, 403):
                    return "unauthorized"
                if health.status_code == 503:
                    return "model_loading"
                if health.status_code != 200:
                    return "health_error"
                models = await client.get(f"{self._base_url}/v1/models")
                if models.status_code in (401, 403):
                    return "unauthorized"
                if models.status_code != 200:
                    return "models_endpoint_error"
                try:
                    payload = models.json()
                except ValueError:
                    return "invalid_models_response"
                if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                    return "invalid_models_response"
                return "ready" if payload["data"] else "no_model_loaded"
        except httpx.TimeoutException:
            return "timeout"
        except httpx.ConnectError:
            return "connection_failed"
        except httpx.RequestError:
            return "network_error"

    async def stream_chat_async(
        self, message: str, history: list[dict[str, str]] | None = None
    ) -> AsyncIterator[str]:
        if not self._base_url:
            raise LlmStreamError("LLM_UNAVAILABLE")
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=0.02)
        except TimeoutError as exc:
            raise LlmStreamError("LLM_BUSY") from exc
        try:
            messages = [{"role": "system", "content": "Be helpful and accurate. Respond in Persian to Persian questions."}]
            if history:
                messages.extend(history)
            messages.append({"role": "user", "content": message})
            body: dict = {"messages": messages, "stream": True, "max_tokens": self._max_tokens}
            if not self._enable_thinking:
                body["chat_template_kwargs"] = {"enable_thinking": False}
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
