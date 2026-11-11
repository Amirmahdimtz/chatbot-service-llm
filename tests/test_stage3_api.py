"""Discovery, request contracts, SSE, production fail-closed and spoofing protections."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from src.application.web import WebService
from src.infrastructure.alembic.model_discovery import load_models
from src.infrastructure.context.sql_db.psql_dbcontext import Base, PsqlDbContext
from src.infrastructure.di.inject import install_providers, resolve
from src.infrastructure.di.reflection import discover_providers
from src.infrastructure.providers.llm import llama_cpp_provider
from src.infrastructure.utils.config_reader import ConfigReader


TOKEN = "stage3-synthetic-token-" + "X" * 40


@pytest.fixture
def dev_app(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV_TYPE", "development")
    monkeypatch.setenv("CHATBOT_DEV_API_TOKEN", TOKEN)
    monkeypatch.setenv("CHATBOT_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'stage3.sqlite').as_posix()}")
    monkeypatch.delenv("CHATBOT_LLM_BASE_URL", raising=False)
    install_providers(discover_providers())
    load_models()
    app = WebService(ConfigReader()).create_app()
    context = resolve(PsqlDbContext)
    async def setup_async():
        async with context.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    asyncio.run(setup_async())
    return app


def mock_stream(monkeypatch, text=None, http_status=200):
    original = httpx.AsyncClient
    if text is None:
        text = 'data: {"choices":[{"delta":{"content":"سلام"}}]}\n\ndata: [DONE]\n\n'
    def handler(request):
        return httpx.Response(http_status, text=text)
    monkeypatch.setattr(llama_cpp_provider.httpx, "AsyncClient",
                        lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


def events_from(response):
    result = []
    for event in response.text.strip().split("\n\n"):
        lines = event.splitlines()
        assert lines[0].startswith("event: ")
        assert lines[1].startswith("data: ")
        result.append((lines[0][7:], json.loads(lines[1][6:])))
    return result


def test_chat_auto_discovery_openapi_and_persian_utf8(dev_app, monkeypatch):
    mock_stream(monkeypatch)
    schema = dev_app.openapi()
    route = schema["paths"]["/api/v1/chat/stream"]["post"]
    assert route["requestBody"]["content"]["application/json"]
    assert "text/event-stream" in route["responses"]["200"]["content"]
    with TestClient(dev_app) as client:
        response = client.post("/api/v1/chat/stream", json={"message": "سلام"},
                               headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    events = events_from(response)
    assert [e[0] for e in events] == ["message_start", "delta", "message_end"]
    assert events[1][1]["text"] == "سلام"
    assert events[-1][1]["status"] == "completed"
    assert events[0][1]["conversation_id"] is not None
    assert events[0][1]["request_id"] == response.headers["x-request-id"]


def test_missing_identity_and_untrusted_claims(dev_app):
    with TestClient(dev_app) as client:
        response = client.post("/api/v1/chat/stream", json={"message": "hello"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"
        forged = client.post("/api/v1/chat/stream", json={"message": "hello"},
                             headers={"Authorization": f"Bearer {TOKEN}", "X-Audience": "internal"})
        assert forged.status_code == 403
        assert forged.json()["error"]["code"] == "UNTRUSTED_CLAIMS"


def test_conversation_continuation_has_real_persistence(dev_app, monkeypatch):
    mock_stream(monkeypatch)
    with TestClient(dev_app) as client:
        initial = client.post("/api/v1/chat/stream", json={"message": "hello"},
                              headers={"Authorization": f"Bearer {TOKEN}"})
        conversation_id = events_from(initial)[0][1]["conversation_id"]
        response = client.post("/api/v1/chat/stream", json={"message": "hello",
                               "conversation_id": conversation_id},
                               headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 200
        assert events_from(response)[0][1]["conversation_id"] == conversation_id
        assert len(client.get(f"/api/v1/conversation/{conversation_id}",
                              headers={"Authorization": f"Bearer {TOKEN}"}).json()["messages"]) == 4


def test_bad_input_produces_sanitized_json_error(dev_app):
    with TestClient(dev_app) as client:
        for payload in ({"message": " "}, {"message": "x"*1001},
                        {"message": "hello", "audience": "internal"}):
            response = client.post("/api/v1/chat/stream", json=payload,
                                   headers={"Authorization": f"Bearer {TOKEN}"})
            assert response.status_code == 422
            body = response.json()["error"]
            assert body["code"] == "VALIDATION_ERROR"
            assert body["request_id"] == response.headers["x-request-id"]
            assert "input" not in str(body)


def test_unavailable_runtime_is_safe_sse_failure(dev_app, monkeypatch):
    mock_stream(monkeypatch, http_status=503)
    with TestClient(dev_app) as client:
        response = client.post("/api/v1/chat/stream", json={"message": "hello"},
                               headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200  # The stream has started; HTTP status cannot change.
    events = events_from(response)
    assert [name for name, _ in events] == ["message_start", "error", "message_end"]
    assert events[1][1]["code"] == "LLM_UNAVAILABLE"
    assert events[-1][1]["status"] == "failed"


def test_reasoning_only_stream_returns_sanitized_empty_response(dev_app, monkeypatch):
    mock_stream(
        monkeypatch,
        text=(
            'data: {"choices":[{"delta":{"reasoning_content":"private reasoning"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":null},"finish_reason":"length"}]}\n\n'
            'data: [DONE]\n\n'
        ),
    )
    with TestClient(dev_app) as client:
        response = client.post("/api/v1/chat/stream", json={"message": "hello"},
                               headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    events = events_from(response)
    assert [name for name, _ in events] == ["message_start", "error", "message_end"]
    assert events[1][1]["code"] == "LLM_EMPTY_RESPONSE"
    assert "private reasoning" not in response.text


def test_production_denies_dev_token_even_if_present(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV_TYPE", "production")
    monkeypatch.setenv("CHATBOT_DEV_API_TOKEN", TOKEN)
    monkeypatch.setenv("CHATBOT_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'prod.sqlite').as_posix()}")
    install_providers(discover_providers())
    app = WebService(ConfigReader()).create_app()
    with TestClient(app) as client:
        response = client.post("/api/v1/chat/stream", json={"message": "hello"},
                               headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 401


def test_development_does_not_accept_empty_or_short_api_token(monkeypatch):
    from src.core.services.chat.chat_identity_service import ChatIdentityService
    class Config:
        def get(self, key, default=None):
            return {"auth.dev_enabled": True, "auth.dev_api_token": "short"}.get(key, default)
    monkeypatch.setenv("ENV_TYPE", "development")
    assert ChatIdentityService(Config()).authenticate("Bearer short") is None
