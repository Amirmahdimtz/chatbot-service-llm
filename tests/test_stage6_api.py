"""Stage 6 FastAPI/SSE integration on a disposable SQLite DB; synthetic sources only."""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.application.web import WebService
from src.core.services.chat.chat_identity_service import ChatIdentity, ChatIdentityService
from src.core.services.knowledge.knowledge_index_service import KnowledgeIndexService
from src.infrastructure.alembic.model_discovery import load_models
from src.infrastructure.context.sql_db.psql_dbcontext import Base, PsqlDbContext
from src.infrastructure.di.inject import install_providers, resolve
from src.infrastructure.di.reflection import discover_providers
from src.infrastructure.providers.llm.llama_cpp_provider import LlamaCppProvider
from src.infrastructure.utils.config_reader import ConfigReader


TOKEN = "stage6-synthetic-" + "x" * 40
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV_TYPE", "development")
    monkeypatch.setenv("CHATBOT_DEV_API_TOKEN", TOKEN)
    monkeypatch.setenv("CHATBOT_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'stage6.sqlite').as_posix()}")
    install_providers(discover_providers())
    load_models()
    application = WebService(ConfigReader()).create_app()
    db = resolve(PsqlDbContext)
    async def initialize_async():
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(initialize_async())
    return application


def events(response):
    return [(segment.splitlines()[0][7:], json.loads(segment.splitlines()[1][6:]))
            for segment in response.text.strip().split("\n\n")]


def install_rag_mocks(monkeypatch, results, captured):
    async def retrieve_async(self, identity, query):
        captured.append(("scope", identity.audience, identity.subject, identity.tenant_id))
        if isinstance(results, Exception):
            raise results
        return results

    async def stream_chat_async(self, message, history=None, system_prompt=None, evidence=None):
        captured.append(("llm", message, history, system_prompt, evidence))
        yield "متن پاسخ فارسی"

    monkeypatch.setattr(KnowledgeIndexService, "retrieve_async", retrieve_async)
    monkeypatch.setattr(LlamaCppProvider, "stream_chat_async", stream_chat_async)


def test_rag_sse_sources_history_and_direct_regression(app, monkeypatch):
    source = {"document_id": str(uuid4()), "chunk_id": str(uuid4()), "version": 1,
              "text": "قانون ساختگی: آموزش ۶ روز است.", "title": "سند عمومی آزمایشی",
              "source_location": {"page": 2}, "source_uri": "file:///private"}
    calls = []
    install_rag_mocks(monkeypatch, [source], calls)
    with TestClient(app) as client:
        response = client.post("/api/v1/chat/stream",
            json={"message": "مدت آموزش چقدر است؟", "scenario": "knowledge_qa"}, headers=HEADERS)
        assert response.status_code == 200
        trace = events(response)
        assert [name for name, _ in trace] == ["message_start", "sources", "delta", "message_end"]
        assert trace[0][1]["route"] == "rag"
        assert trace[1][1]["documents"][0]["document_id"] == source["document_id"]
        assert "source_uri" not in str(trace[1][1])
        assert trace[-1][1]["response_type"] == "rag_generated"
        assert calls[0][1] == "public"
        assert "UNTRUSTED_EVIDENCE" in calls[1][-1]
        conv_id = trace[0][1]["conversation_id"]
        history = client.get(f"/api/v1/conversation/{conv_id}", headers=HEADERS)
        assert [(x["role"], x["status"]) for x in history.json()["messages"]] == [
            ("user", "completed"), ("assistant", "completed"),
        ]
        follow = client.post("/api/v1/chat/stream",
            json={"message": "سلام", "conversation_id": conv_id}, headers=HEADERS)
        assert [x[0] for x in events(follow)] == ["message_start", "delta", "message_end"]
        assert events(follow)[-1][1]["response_type"] == "direct_generated"
        assert calls[-1][2][-2:] == [
            {"role": "user", "content": "مدت آموزش چقدر است؟"},
            {"role": "assistant", "content": "متن پاسخ فارسی"},
        ]


def test_insufficient_retrieval_error_invalid_scenario_and_spoofing(app, monkeypatch):
    calls = []
    install_rag_mocks(monkeypatch, [], calls)
    with TestClient(app) as client:
        response = client.post("/api/v1/chat/stream",
            json={"message": "سؤال ناشناخته", "scenario": "knowledge_qa"}, headers=HEADERS)
        trace = events(response)
        assert [name for name, _ in trace] == ["message_start", "delta", "message_end"]
        assert trace[-1][1]["response_type"] == "insufficient_evidence"
        assert all(item[0] != "llm" for item in calls)
        assert client.post("/api/v1/chat/stream", json={
            "message": "hi", "scenario": "internal"}, headers=HEADERS).status_code == 422
        assert client.post("/api/v1/chat/stream", json={
            "message": "hi", "scenario": "knowledge_qa", "audience": "internal"
        }, headers=HEADERS).status_code == 422
        assert client.post("/api/v1/chat/stream", json={
            "message": "read internal", "scenario": "knowledge_qa"
        }, headers={**HEADERS, "X-Audience": "internal"}).status_code == 403
        assert client.post("/api/v1/chat/stream",
            json={"message": "hi", "scenario": "knowledge_qa"}).status_code == 401

    install_rag_mocks(monkeypatch, RuntimeError("secret error detail"), calls)
    with TestClient(app) as client:
        response = client.post("/api/v1/chat/stream",
            json={"message": "سؤال", "scenario": "knowledge_qa"}, headers=HEADERS)
        trace = events(response)
        assert [name for name, _ in trace] == ["message_start", "error", "message_end"]
        assert trace[1][1]["code"] == "RETRIEVAL_UNAVAILABLE"
        assert trace[-1][1]["status"] == "failed"
        assert "secret" not in response.text


def test_internal_tenant_permission_and_idor_are_enforced_before_persisting(app, monkeypatch):
    monkeypatch.setattr(ChatIdentityService, "authenticate",
                        lambda self, auth: ChatIdentity("staff", "internal", frozenset(), "tenant-1"))
    with TestClient(app) as client:
        denied = client.post("/api/v1/chat/stream",
            json={"message": "اطلاعات خصوصی", "scenario": "knowledge_qa"}, headers=HEADERS)
        assert denied.status_code == 403
        assert client.get("/api/v1/conversation/", headers=HEADERS).json()["items"] == []
    monkeypatch.setattr(ChatIdentityService, "authenticate",
                        lambda self, auth: ChatIdentity("staff", "internal", frozenset({"knowledge:read_internal"}), None))
    with TestClient(app) as client:
        assert client.post("/api/v1/chat/stream",
            json={"message": "internal", "scenario": "knowledge_qa"}, headers=HEADERS).status_code == 403


def test_internal_same_subject_different_tenants_cannot_read_conversation(app, monkeypatch):
    principal = {"tenant": "tenant-1"}
    monkeypatch.setattr(ChatIdentityService, "authenticate", lambda self, auth:
                        ChatIdentity("same-person", "internal",
                                     frozenset({"knowledge:read_internal"}), principal["tenant"]))
    calls = []
    install_rag_mocks(monkeypatch, [], calls)
    with TestClient(app) as client:
        created = client.post("/api/v1/chat/stream",
            json={"message": "تست داخلی", "scenario": "knowledge_qa"}, headers=HEADERS)
        assert created.status_code == 200
        identifier = events(created)[0][1]["conversation_id"]
        assert client.get(f"/api/v1/conversation/{identifier}", headers=HEADERS).status_code == 200
        principal["tenant"] = "tenant-2"
        assert client.get(f"/api/v1/conversation/{identifier}", headers=HEADERS).status_code == 404
        assert client.post("/api/v1/chat/stream",
            json={"message": "cross tenant", "conversation_id": identifier},
            headers=HEADERS).status_code == 404
        assert client.get("/api/v1/conversation/", headers=HEADERS).json()["items"] == []
