"""LLM readiness returns actionable, fixed codes without exposing runtime responses."""

from __future__ import annotations

import httpx
import pytest

from src.infrastructure.providers.llm import llama_cpp_provider
from src.infrastructure.providers.llm.llama_cpp_provider import LlamaCppProvider


class StubConfig:
    def __init__(self, url="http://host.docker.internal:8080"):
        self.url = url

    def get(self, key, default=None):
        return self.url if key == "llm.base_url" else default


@pytest.mark.asyncio
@pytest.mark.parametrize("health, models, expected", [
    (503, None, "model_loading"),
    (401, None, "unauthorized"),
    (502, None, "health_error"),
    (200, 401, "unauthorized"),
    (200, 404, "models_endpoint_error"),
    (200, [], "no_model_loaded"),
    (200, "invalid-json", "invalid_models_response"),
    (200, {"unexpected": True}, "invalid_models_response"),
    (200, [{"id": "synthetic"}], "ready"),
])
async def test_statuses_are_safe_and_stable(monkeypatch, health, models, expected):
    original_client = httpx.AsyncClient

    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(health, text="secret server details")
        if request.url.path == "/v1/models":
            if isinstance(models, int):
                return httpx.Response(models, text="secret server details")
            if isinstance(models, str):
                return httpx.Response(200, text=models)
            if isinstance(models, dict):
                return httpx.Response(200, json=models)
            return httpx.Response(200, json={"data": models})
        return httpx.Response(404)

    monkeypatch.setattr(llama_cpp_provider.httpx, "AsyncClient", lambda **kw: original_client(
        transport=httpx.MockTransport(handler), **kw
    ))
    provider = LlamaCppProvider(StubConfig())
    assert await provider.readiness_status_async() == expected
    assert await provider.check_ready_async() == (expected == "ready")
    assert "secret" not in await provider.readiness_status_async()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type,expected", [
    (httpx.ConnectError, "connection_failed"),
    (httpx.ReadTimeout, "timeout"),
    (httpx.RemoteProtocolError, "network_error"),
])
async def test_network_status_redacts_error_message(monkeypatch, error_type, expected):
    original_client = httpx.AsyncClient

    def offline(request):
        raise error_type("secret internal endpoint", request=request)

    monkeypatch.setattr(llama_cpp_provider.httpx, "AsyncClient", lambda **kw: original_client(
        transport=httpx.MockTransport(offline), **kw
    ))
    provider = LlamaCppProvider(StubConfig())
    assert await provider.readiness_status_async() == expected


@pytest.mark.asyncio
async def test_explicitly_unconfigured_runtime_is_not_ready():
    provider = LlamaCppProvider(StubConfig(url=""))
    assert await provider.readiness_status_async() == "not_configured"
    assert not await provider.check_ready_async()
