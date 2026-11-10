"""Mock HTTP transports test local-only readiness without downloading a model."""

from __future__ import annotations

import httpx
import pytest

from src.infrastructure.providers.llm import llama_cpp_provider
from src.infrastructure.providers.vector_db import qdrant_provider


class StubConfig:
    def __init__(self, values: dict):
        self.values = values

    def get(self, key: str, default=None):
        return self.values.get(key, default)


@pytest.mark.asyncio
async def test_qdrant_readiness_and_collections_api(monkeypatch):
    original = httpx.AsyncClient

    def handler(request):
        if request.url.path == "/readyz":
            return httpx.Response(200, text="healthz check passed")
        if request.url.path == "/collections":
            return httpx.Response(200, json={"result": {"collections": []}})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(qdrant_provider.httpx, "AsyncClient", lambda **kw: original(transport=transport, **kw))
    provider = qdrant_provider.QdrantProvider(StubConfig({"vector.url": "http://qdrant:6333"}))
    assert await provider.check_ready_async()
    assert await provider.check_api_async()


@pytest.mark.asyncio
async def test_qdrant_unavailable_returns_false(monkeypatch):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    monkeypatch.setattr(qdrant_provider.httpx, "AsyncClient", lambda **kw: original(transport=transport, **kw))
    provider = qdrant_provider.QdrantProvider(StubConfig({"vector.url": "http://qdrant:6333"}))
    assert not await provider.check_ready_async()
    assert not await provider.check_api_async()


@pytest.mark.asyncio
async def test_llama_ready_requires_loaded_model_and_sends_optional_key(monkeypatch):
    original = httpx.AsyncClient
    received = []

    def handler(request):
        received.append((request.url.path, request.headers.get("authorization")))
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "synthetic-model"}]})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llama_cpp_provider.httpx, "AsyncClient", lambda **kw: original(transport=transport, **kw))
    provider = llama_cpp_provider.LlamaCppProvider(
        StubConfig({"llm.base_url": "http://host.docker.internal:8080", "llm.api_key": "synthetic"})
    )
    assert await provider.check_ready_async()
    assert received == [("/health", "Bearer synthetic"), ("/v1/models", "Bearer synthetic")]


@pytest.mark.asyncio
async def test_llama_not_ready_without_loaded_model(monkeypatch):
    original = httpx.AsyncClient

    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(
        llama_cpp_provider.httpx, "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    provider = llama_cpp_provider.LlamaCppProvider(StubConfig({"llm.base_url": "http://localhost:8080"}))
    assert not await provider.check_ready_async()


def test_missing_runtime_urls_rejected():
    with pytest.raises(ValueError, match="Qdrant URL"):
        qdrant_provider.QdrantProvider(StubConfig({}))
    with pytest.raises(ValueError, match="LLM URL"):
        llama_cpp_provider.LlamaCppProvider(StubConfig({}))


@pytest.mark.asyncio
async def test_llama_connection_failure_is_controlled(monkeypatch):
    original = httpx.AsyncClient

    def offline(request):
        raise httpx.ConnectError("synthetic offline runtime", request=request)

    monkeypatch.setattr(
        llama_cpp_provider.httpx, "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(offline), **kw),
    )
    provider = llama_cpp_provider.LlamaCppProvider(StubConfig({"llm.base_url": "http://localhost:8080"}))
    assert not await provider.check_ready_async()
