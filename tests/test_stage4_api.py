"""Full HTTP contract: discovery, real persistence, IDOR, audience, validation."""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from src.application.web import WebService
from src.core.services.chat.chat_identity_service import ChatIdentity, ChatIdentityService
from src.infrastructure.alembic.model_discovery import load_models
from src.infrastructure.context.sql_db.psql_dbcontext import Base, PsqlDbContext
from src.infrastructure.di.inject import install_providers, resolve
from src.infrastructure.di.reflection import discover_providers
from src.infrastructure.providers.llm import llama_cpp_provider
from src.infrastructure.utils.config_reader import ConfigReader


TOKEN = "stage4-synthetic-" + "x" * 40
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV_TYPE", "development")
    monkeypatch.setenv("CHATBOT_DEV_API_TOKEN", TOKEN)
    monkeypatch.setenv("CHATBOT_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'api.sqlite').as_posix()}")
    install_providers(discover_providers())
    load_models()
    application = WebService(ConfigReader()).create_app()
    context = resolve(PsqlDbContext)
    async def init_async():
        async with context.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    asyncio.run(init_async())
    return application


def mock_llm(monkeypatch, response="پاسخ"):
    original = httpx.AsyncClient
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, text=(
            "data: " + json.dumps({"choices": [{"delta": {"content": response}}]}, ensure_ascii=False) +
            "\n\ndata: [DONE]\n\n"
        ))

    monkeypatch.setattr(llama_cpp_provider.httpx, "AsyncClient",
                        lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    return sent


def parse_events(response):
    return [(event.splitlines()[0][7:], json.loads(event.splitlines()[1][6:]))
            for event in response.text.strip().split("\n\n")]


def test_discovery_create_continue_and_history_with_persian(app, monkeypatch):
    sent = mock_llm(monkeypatch)
    schema = app.openapi()["paths"]
    for route in ("/api/v1/conversation/", "/api/v1/conversation/{conversation_id}",
                  "/api/v1/feedback/", "/api/v1/knowledge/", "/api/v1/knowledge/{document_id}"):
        assert route in schema
    with TestClient(app) as client:
        created = client.post("/api/v1/conversation/", json={"title": " آزمایشی "}, headers=HEADERS)
        assert created.status_code == 201, created.text
        conversation_id = created.json()["id"]
        assert created.json()["title"] == "آزمایشی"
        first = client.post("/api/v1/chat/stream", json={"message": "سلام",
            "conversation_id": conversation_id}, headers=HEADERS)
        assert first.status_code == 200, first.text
        events = parse_events(first)
        assert [name for name, _ in events] == ["message_start", "delta", "message_end"]
        assert events[0][1]["conversation_id"] == conversation_id
        assert events[1][1]["text"] == "پاسخ"
        assert events[-1][1]["status"] == "completed"
        second = client.post("/api/v1/chat/stream", json={"message": "ادامه",
            "conversation_id": conversation_id}, headers=HEADERS)
        assert parse_events(second)[-1][1]["status"] == "completed"
        assert [entry["content"] for entry in sent[1]["messages"]] == [
            "Be helpful and accurate. Respond in Persian to Persian questions.",
            "سلام", "پاسخ", "ادامه",
        ]
        history = client.get(f"/api/v1/conversation/{conversation_id}?limit=2", headers=HEADERS)
        assert history.status_code == 200
        assert [item["role"] for item in history.json()["messages"]] == ["user", "assistant"]
        assert history.json()["message_next_cursor"] == "2"
        page_two = client.get(f"/api/v1/conversation/{conversation_id}?limit=2&offset=2", headers=HEADERS)
        assert [item["role"] for item in page_two.json()["messages"]] == ["user", "assistant"]
        assert page_two.json()["message_next_cursor"] is None
        listed = client.get("/api/v1/conversation/?limit=1", headers=HEADERS)
        assert [x["id"] for x in listed.json()["items"]] == [conversation_id]
        assert listed.json()["next_cursor"] is None


def test_feedback_complete_owned_unique_and_invalid(app, monkeypatch):
    mock_llm(monkeypatch)
    with TestClient(app) as client:
        response = client.post("/api/v1/chat/stream", json={"message": "hello"}, headers=HEADERS)
        message_id = parse_events(response)[0][1]["message_id"]
        feedback = client.post("/api/v1/feedback/", json={
            "message_id": message_id, "kind": "incorrect", "comment": "incorrect information"
        }, headers=HEADERS)
        assert feedback.status_code == 201 and feedback.json()["kind"] == "incorrect"
        duplicate = client.post("/api/v1/feedback/", json={
            "message_id": message_id, "kind": "positive"
        }, headers=HEADERS)
        assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "ALREADY_EXISTS"
        missing = client.post("/api/v1/feedback/", json={
            "message_id": str(uuid4()), "kind": "positive"
        }, headers=HEADERS)
        assert missing.status_code == 404
        bad = client.post("/api/v1/feedback/", json={
            "message_id": message_id, "kind": "invalid"
        }, headers=HEADERS)
        assert bad.status_code == 422


def test_knowledge_metadata_only_and_reject_internal_claim(app):
    with TestClient(app) as client:
        created = client.post("/api/v1/knowledge/", json={
            "title": "Sample", "source_type": "pdf", "audience": "public"
        }, headers=HEADERS)
        assert created.status_code == 201, created.text
        metadata = created.json()
        assert metadata["status"] == "registered" and metadata["version"] == 1
        fetched = client.get(f"/api/v1/knowledge/{metadata['id']}", headers=HEADERS)
        assert fetched.status_code == 200 and fetched.json()["status"] == "registered"
        assert len(client.get("/api/v1/knowledge/", headers=HEADERS).json()["items"]) == 1
        prohibited = client.post("/api/v1/knowledge/", json={
            "title": "secret", "source_type": "pdf", "audience": "internal"
        }, headers=HEADERS)
        assert prohibited.status_code == 403
        assert client.get(f"/api/v1/knowledge/{uuid4()}", headers=HEADERS).status_code == 404
        assert client.post("/api/v1/knowledge/", json={
            "title": "bad", "source_type": "exe", "audience": "public"
        }, headers=HEADERS).status_code == 422


def test_cross_user_and_internal_access_are_not_disclosed(app, monkeypatch):
    mock_llm(monkeypatch)
    original = ChatIdentityService.authenticate

    def with_synthetic_users(self, value):
        if value == "Bearer bob-test":
            return ChatIdentity("bob", "public")
        if value == "Bearer internal-test":
            return ChatIdentity("alice", "internal", frozenset({"knowledge:write"}))
        return original(self, value)

    monkeypatch.setattr(ChatIdentityService, "authenticate", with_synthetic_users)
    alice = ChatIdentity("synthetic-development-public", "public", frozenset({"knowledge:write"}))
    with TestClient(app) as client:
        stream = client.post("/api/v1/chat/stream", json={"message": "hi"}, headers=HEADERS)
        start = parse_events(stream)[0][1]
        conv_id, message_id = start["conversation_id"], start["message_id"]
        knowledge = client.post("/api/v1/knowledge/", json={
            "title": "public", "source_type": "txt", "audience": "public"
        }, headers=HEADERS).json()["id"]
        bob = {"Authorization": "Bearer bob-test"}
        assert client.get(f"/api/v1/conversation/{conv_id}", headers=bob).status_code == 404
        assert client.post("/api/v1/chat/stream", json={
            "message": "foreign", "conversation_id": conv_id
        }, headers=bob).status_code == 404
        assert client.post("/api/v1/feedback/", json={
            "message_id": message_id, "kind": "incorrect"
        }, headers=bob).status_code == 404
        assert client.get(f"/api/v1/knowledge/{knowledge}", headers=bob).status_code == 404
        internal = {"Authorization": "Bearer internal-test"}
        internal_doc = client.post("/api/v1/knowledge/", json={
            "title": "private", "source_type": "txt", "audience": "internal"
        }, headers=internal)
        assert internal_doc.status_code == 201
        assert client.get(f"/api/v1/knowledge/{internal_doc.json()['id']}", headers=HEADERS).status_code == 404
        assert client.get(f"/api/v1/conversation/{conv_id}", headers=internal).status_code == 404


def test_auth_and_spoofing_and_pagination_are_fail_closed(app):
    with TestClient(app) as client:
        for url in ("/api/v1/conversation/", "/api/v1/feedback/", "/api/v1/knowledge/"):
            assert client.get(url).status_code in (401, 405)
        assert client.get("/api/v1/conversation/").status_code == 401
        forged = {**HEADERS, "X-Audience": "internal"}
        assert client.get("/api/v1/conversation/", headers=forged).status_code == 403
        assert client.post("/api/v1/chat/stream", json={"message": "x"},
                           headers={**HEADERS, "X-User-ID": "admin"}).status_code == 403
        for url in ("/api/v1/conversation/?limit=0", "/api/v1/knowledge/?limit=999"):
            invalid = client.get(url, headers=HEADERS)
            assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_actual_asgi_disconnect_stops_llm_and_persists_cancelled(app, monkeypatch):
    """Test a receive-side HTTP disconnect, not only a manually closed generator."""
    upstream_closed = asyncio.Event()

    async def suspended_llm_async(self, message, history=None):
        try:
            yield "سلام"
            await asyncio.Event().wait()
        finally:
            upstream_closed.set()

    monkeypatch.setattr(llama_cpp_provider.LlamaCppProvider, "stream_chat_async", suspended_llm_async)
    body = json.dumps({"message": "سلام"}, ensure_ascii=False).encode("utf-8")
    request_sent = False
    disconnected = asyncio.Event()
    response_chunks = []

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            chunk = message.get("body", b"").decode("utf-8")
            response_chunks.append(chunk)
            if chunk.startswith("event: delta\\n"):
                disconnected.set()

    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/api/v1/chat/stream", "raw_path": b"/api/v1/chat/stream",
        "root_path": "", "query_string": b"",
        "headers": [(b"host", b"localhost"), (b"authorization", HEADERS["Authorization"].encode()),
                    (b"content-type", b"application/json")],
        "server": ("localhost", 80), "client": ("127.0.0.1", 51234),
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=8)
    assert disconnected.is_set()
    assert upstream_closed.is_set()
    start_event = next(chunk for chunk in response_chunks if chunk.startswith("event: message_start\\n"))
    start = json.loads(start_event.split("data: ", 1)[1])

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://localhost") as client:
        history = await client.get(f"/api/v1/conversation/{start['conversation_id']}", headers=HEADERS)
    assert history.status_code == 200
    messages = history.json()["messages"]
    assistant = next(item for item in messages if item["id"] == start["message_id"])
    assert assistant["status"] == "cancelled"
    assert assistant["content"] == "سلام"
    assert messages[0]["content"] == "سلام"
