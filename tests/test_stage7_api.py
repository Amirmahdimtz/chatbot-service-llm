"""Stage 7 FastAPI integration with synthetic decisions and real SQL persistence."""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.application.web import WebService
from src.core.services.chat.chat_identity_service import ChatIdentity, ChatIdentityService
from src.core.services.rag.rag_service import RagContext, RagService
from src.infrastructure.alembic.model_discovery import load_models
from src.infrastructure.context.sql_db.psql_dbcontext import Base, PsqlDbContext
from src.infrastructure.di.inject import install_providers, resolve
from src.infrastructure.di.reflection import discover_providers
from src.infrastructure.providers.llm.llama_cpp_provider import LlamaCppProvider
from src.infrastructure.utils.config_reader import ConfigReader

TOKEN = "synthetic-stage7-" + "x" * 40
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV_TYPE", "development")
    monkeypatch.setenv("CHATBOT_DEV_API_TOKEN", TOKEN)
    monkeypatch.setenv("CHATBOT_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'stage7.sqlite').as_posix()}")
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


def model_stubs(monkeypatch, choices, evidence=True):
    decisions = iter(choices)
    calls = []
    source = {"document_id": str(uuid4()), "chunk_id": str(uuid4()),
              "title": "Synthetic authorized record", "version": 1,
              "source_location": {"page": 2}}

    async def complete_json_async(self, message, history=None, system_prompt=None, evidence=None,
                                  response_schema=None):
        calls.append(("plan", evidence))
        return next(decisions)

    async def stream_chat_async(self, message, history=None, system_prompt=None, evidence=None):
        calls.append(("final", evidence))
        yield "نتیجه آزمایشی"

    async def prepare_async(self, identity, query):
        calls.append(("scope", identity.audience, identity.tenant_id))
        return RagContext("synthetic evidence", (source,)) if evidence else RagContext("", ())

    monkeypatch.setattr(LlamaCppProvider, "complete_json_async", complete_json_async)
    monkeypatch.setattr(LlamaCppProvider, "stream_chat_async", stream_chat_async)
    monkeypatch.setattr(RagService, "prepare_async", prepare_async)
    return calls, source


def choose(name, args):
    return {"action": "tool", "tool": name, "arguments": args}


def finish():
    return {"action": "finish", "tool": None, "arguments": {}}


def test_agent_api_multi_tool_sse_persistence_and_regression(app, monkeypatch):
    calls, source = model_stubs(monkeypatch, [
        choose("search_knowledge", {"query": "synthetic policy"}),
        choose("list_owned_documents", {"limit": 2}), finish(),
    ])
    with TestClient(app) as client:
        response = client.post("/api/v1/chat/stream", json={
            "scenario": "agent_qa", "message": "Find policy and my documents",
        }, headers=HEADERS)
        assert response.status_code == 200
        trace = events(response)
        assert [x[0] for x in trace] == [
            "message_start", "tool_start", "tool_result", "sources", "tool_start",
            "tool_result", "delta", "message_end",
        ]
        assert trace[0][1]["route"] == "agent" and trace[0][1]["scenario"] == "agent_qa"
        assert trace[-1][1]["status"] == "completed"
        assert trace[-1][1]["response_type"] == "agent_generated"
        assert trace[3][1]["documents"][0]["document_id"] == source["document_id"]
        assert "secret" not in response.text.lower()
        assert calls[-1][0] == "final" and "synthetic evidence" in calls[-1][1]
        conv_id = trace[0][1]["conversation_id"]
        record = client.get(f"/api/v1/conversation/{conv_id}", headers=HEADERS)
        assert [m["status"] for m in record.json()["messages"]] == ["completed", "completed"]
        assert record.json()["messages"][-1]["content"] == "نتیجه آزمایشی"
        general = client.post("/api/v1/chat/stream", json={"message": "hello"}, headers=HEADERS)
        assert events(general)[0][1]["route"] == "direct_llm"
        assert events(general)[-1][1]["response_type"] == "direct_generated"


def test_agent_duplicate_tool_decision_completes_sse_and_persists(app, monkeypatch):
    calls, _ = model_stubs(monkeypatch, [
        choose("list_owned_documents", {"limit": 5}),
        choose("list_owned_documents", {"limit": 5}),
    ])
    with TestClient(app) as client:
        response = client.post("/api/v1/chat/stream", json={
            "scenario": "agent_qa", "message": "List my available documents",
        }, headers=HEADERS)
        assert response.status_code == 200
        trace = events(response)
        assert [name for name, _ in trace] == [
            "message_start", "tool_start", "tool_result", "delta", "message_end",
        ]
        assert trace[2][1]["item_count"] == 0
        assert trace[1][1]["call_id"] == trace[2][1]["call_id"]
        assert trace[-1][1]["status"] == "completed"
        assert trace[-1][1]["response_type"] == "agent_generated"
        assert [item[0] for item in calls] == ["plan", "plan"]
        assert '"items":[]' in calls[-1][1]
        assert "سندی متعلق به شما یافت نشد" in trace[3][1]["text"]
        assert "Authentication Service" not in trace[3][1]["text"]
        conversation_id = trace[0][1]["conversation_id"]
        history = client.get(f"/api/v1/conversation/{conversation_id}", headers=HEADERS)
        assert history.status_code == 200
        assert [item["status"] for item in history.json()["messages"]] == [
            "completed", "completed",
        ]


def test_agent_refuses_tool_free_completion_and_persists_failure(app, monkeypatch):
    calls, _ = model_stubs(monkeypatch, [finish()])
    with TestClient(app) as client:
        response = client.post("/api/v1/chat/stream", json={
            "scenario": "agent_qa", "message": "Show my owned documents",
        }, headers=HEADERS)
        trace = events(response)
        assert [name for name, _ in trace] == ["message_start", "error", "message_end"]
        assert trace[1][1]["code"] == "AGENT_INVALID_DECISION"
        assert trace[-1][1]["status"] == "failed"
        assert calls == [("plan", None)]
        conversation_id = trace[0][1]["conversation_id"]
        history = client.get(f"/api/v1/conversation/{conversation_id}", headers=HEADERS)
        assert history.status_code == 200
        assert history.json()["messages"][-1]["status"] == "failed"


def test_agent_rejects_bad_choices_and_no_spoofed_scope(app, monkeypatch):
    model_stubs(monkeypatch, [choose("shell", {})])
    with TestClient(app) as client:
        failed = client.post("/api/v1/chat/stream", json={
            "scenario": "agent_qa", "message": "do something",
        }, headers=HEADERS)
        trace = events(failed)
        assert [x[0] for x in trace] == ["message_start", "error", "message_end"]
        assert trace[1][1]["code"] == "AGENT_INVALID_TOOL"
        assert trace[-1][1]["status"] == "failed"
        assert sum(x[0] == "message_end" for x in trace) == 1
        assert client.post("/api/v1/chat/stream", json={
            "scenario": "agent_qa", "message": "read internal", "audience": "internal",
        }, headers=HEADERS).status_code == 422
        assert client.post("/api/v1/chat/stream", json={
            "scenario": "agent_qa", "message": "read internal",
        }, headers={**HEADERS, "X-Tenant-Id": "tenant-other"}).status_code == 403
        assert client.post("/api/v1/chat/stream", json={
            "scenario": "agent_qa", "message": "without authorization",
        }).status_code == 401


def test_agent_internal_permission_and_conversation_idor(app, monkeypatch):
    principal = {"tenant": "tenant-a", "permissions": frozenset({"knowledge:read_internal"})}
    monkeypatch.setattr(ChatIdentityService, "authenticate", lambda self, auth:
                        ChatIdentity("synthetic-staff", "internal", principal["permissions"], principal["tenant"]))
    model_stubs(monkeypatch, [choose("list_owned_documents", {"limit": 5}), finish()])
    with TestClient(app) as client:
        principal["permissions"] = frozenset({"chat:use_internal"})
        assert client.post("/api/v1/chat/stream", json={
            "scenario": "agent_qa", "message": "private policy",
        }, headers=HEADERS).status_code == 403
        principal["permissions"] = frozenset({"knowledge:read_internal"})
        result = client.post("/api/v1/chat/stream", json={
            "scenario": "agent_qa", "message": "private policy",
        }, headers=HEADERS)
        cid = events(result)[0][1]["conversation_id"]
        assert client.get(f"/api/v1/conversation/{cid}", headers=HEADERS).status_code == 200
        principal["tenant"] = "tenant-b"
        assert client.get(f"/api/v1/conversation/{cid}", headers=HEADERS).status_code == 404
        assert client.post("/api/v1/chat/stream", json={
            "scenario": "agent_qa", "message": "cross tenant", "conversation_id": cid,
        }, headers=HEADERS).status_code == 404
