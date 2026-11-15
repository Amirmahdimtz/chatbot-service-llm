"""Stage 8 authenticated API + SSE + SQL persistence integration on synthetic SQLite."""
from __future__ import annotations

import asyncio
import json

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

TOKEN = "synthetic-stage8-" + "x" * 40
HEADERS = {"Authorization": "Bearer " + TOKEN}
MANAGER = ChatIdentity("manager", "internal", frozenset({
    "chat:use_internal", "hr:analyze", "research:analyze", "development:analyze",
    "tasks:analyze", "scenario:manage", "religious:verify", "knowledge:read_internal",
    "knowledge:read_public",
}), "tenant-a")


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV_TYPE", "development")
    monkeypatch.setenv("CHATBOT_DEV_API_TOKEN", TOKEN)
    monkeypatch.setenv("CHATBOT_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'stage8.sqlite').as_posix()}")
    install_providers(discover_providers())
    load_models()
    application = WebService(ConfigReader()).create_app()
    db = resolve(PsqlDbContext)

    async def initialize_async():
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(initialize_async())
    principal = {"identity": MANAGER}
    monkeypatch.setattr(ChatIdentityService, "authenticate", lambda self, auth: principal["identity"])
    return application, principal


def events(response):
    return [(part.splitlines()[0][7:], json.loads(part.splitlines()[1][6:]))
            for part in response.text.strip().split("\n\n")]


def put(client, kind, key, payload, audience="internal"):
    return client.put(f"/api/v1/scenario/records/{kind}/{key}",
                      json={"audience": audience, "payload": payload}, headers=HEADERS)


def seed(client):
    assert put(client, "personnel", "alice", {"skills": {"python": 4},
           "years_experience": 4, "unit_id": "u1", "position_id": "junior",
           "transfer_allowed": True}).status_code == 200
    assert put(client, "position", "junior", {
        "title": "Junior", "unit_id": "u1", "open_slots": 0,
    }).status_code == 200
    assert put(client, "position", "senior", {
        "title": "Senior", "unit_id": "u2", "required_skills": {"python": 4},
        "open_slots": 1,
    }).status_code == 200
    assert put(client, "unit", "u1", {"name": "Source", "skills": ["python"],
        "headcount_limit": 5, "current_headcount": 2,
        "capacity_hours": 10, "committed_hours": 1}).status_code == 200
    assert put(client, "unit", "u2", {"name": "Destination", "skills": ["python"],
        "headcount_limit": 5, "current_headcount": 1,
        "capacity_hours": 10, "committed_hours": 1}).status_code == 200
    assert put(client, "research", "case1", {
        "title": "Synthetic pilot", "problem": "python pipeline too slow",
        "context_tags": ["python"], "solution": "Test incremental batching",
        "benefits": ["Latency"], "risks": ["Retries"], "assumptions": ["Stable demand"],
        "evaluation_metrics": ["p95"], "source_reference": "synthetic-record",
    }).status_code == 200
    assert put(client, "task_plan", "plan1", {"objective": "Synthetic deployment", "tasks": [
        {"task_id": "t1", "hours": 2, "required_skills": ["python"]},
    ]}).status_code == 200


@pytest.mark.parametrize("scenario,params", [
    ("personnel_matching", {"position_id": "senior"}),
    ("talent_discovery", {"employee_id": "alice"}),
    ("internal_transfers", {"employee_id": "alice"}),
    ("research_advice", {"context_tags": ["python"]}),
    ("personal_development", {"employee_id": "alice", "target_position_id": "senior"}),
    ("task_allocation", {"plan_id": "plan1"}),
])
def test_six_scenarios_sse_and_history(app, scenario, params):
    application, principal = app
    with TestClient(application) as client:
        seed(client)
        result = client.post("/api/v1/chat/stream", json={
            "scenario": scenario, "message": "Analyze synthetic records",
            "scenario_input": params,
        }, headers=HEADERS)
        assert result.status_code == 200, result.text
        trace = events(result)
        assert [name for name, _ in trace] == [
            "message_start", "tool_start", "tool_result",
            *(["sources"] if scenario == "research_advice" else []),
            "scenario_result", "delta", "message_end",
        ]
        structured = next(data["result"] for name, data in trace if name == "scenario_result")
        assert structured["scenario"] == scenario
        assert structured["status"] == "completed"
        assert trace[-1][1]["status"] == "completed"
        assert trace[-1][1]["response_type"] == "agent_generated"
        cid = trace[0][1]["conversation_id"]
        history = client.get(f"/api/v1/conversation/{cid}", headers=HEADERS)
        assert history.status_code == 200
        assert history.json()["messages"][-1]["scenario_payload"] == structured


def test_faq_verified_and_pending_public_scope(app, monkeypatch):
    application, principal = app

    async def prepare_async(self, identity, query):
        return RagContext("", ())

    async def stream_chat_async(self, message, history=None, system_prompt=None, evidence=None):
        raise AssertionError("Exact approved FAQ should not call local model")
        yield ""

    monkeypatch.setattr(RagService, "prepare_async", prepare_async)
    monkeypatch.setattr(LlamaCppProvider, "stream_chat_async", stream_chat_async)
    with TestClient(application) as client:
        faq = put(client, "faq", "faq1", {
            "question": "حکم یک نمونه آزمایشی چیست؟",
            "answer": "پاسخ تأییدشده آزمایشی",
            "aliases": ["حکم نمونه چیست؟"],
            "source_reference": "source-1", "source_title": "مرجع آزمایشی",
            "expert_reference": "expert-1",
        }, "public")
        assert faq.status_code == 200 and faq.json()["verified"] is True
        principal["identity"] = ChatIdentity("public-1", "public")
        result = client.post("/api/v1/chat/stream", json={
            "scenario": "religious_qa", "message": "حکم نمونه چیست؟",
        }, headers=HEADERS)
        trace = events(result)
        assert trace[-1][1]["response_type"] == "verified_faq"
        assert trace[1][0] == "sources"
        assert trace[2][1]["result"]["sources"][0]["expert_reference"] == "expert-1"
        assert trace[-2][1]["text"] == "پاسخ تأییدشده آزمایشی"
        unknown = client.post("/api/v1/chat/stream", json={
            "scenario": "religious_qa", "message": "موضوع ناموجود ساختگی",
        }, headers=HEADERS)
        trace = events(unknown)
        assert trace[-1][1]["response_type"] == "insufficient_evidence"
        pending = trace[1][1]["result"]["pending_id"]
        assert pending
        assert client.get(f"/api/v1/scenario/pending/{pending}", headers=HEADERS).json()["status"] == "insufficient_evidence"
        principal["identity"] = ChatIdentity("public-2", "public")
        assert client.get(f"/api/v1/scenario/pending/{pending}", headers=HEADERS).status_code == 404


def test_internal_cross_tenant_and_public_security(app):
    application, principal = app
    with TestClient(application) as client:
        seed(client)
        principal["identity"] = ChatIdentity("someone", "internal", MANAGER.permissions, "tenant-b")
        response = client.post("/api/v1/chat/stream", json={
            "scenario": "personnel_matching", "scenario_input": {"position_id": "senior"},
            "message": "match",
        }, headers=HEADERS)
        trace = events(response)
        assert trace[-1][1]["status"] == "completed"
        assert next(x["result"] for n, x in trace if n == "scenario_result")["items"] == []
        assert client.get("/api/v1/scenario/records/personnel/alice", headers=HEADERS).status_code == 404
        principal["identity"] = ChatIdentity("public-1", "public")
        assert put(client, "personnel", "evil", {}).status_code == 403
        assert client.post("/api/v1/chat/stream", json={
            "scenario": "task_allocation", "scenario_input": {"plan_id": "plan1"},
            "message": "assign",
        }, headers=HEADERS).status_code == 403
        assert client.post("/api/v1/chat/stream", json={
            "scenario": "personnel_matching", "scenario_input": {"position_id": "senior"},
            "message": "match", "audience": "internal",
        }, headers=HEADERS).status_code == 422
        assert client.post("/api/v1/chat/stream", json={
            "scenario": "personnel_matching", "scenario_input": {
                "position_id": "senior", "tenant": "tenant-a"},
            "message": "match",
        }, headers=HEADERS).status_code == 422
        assert client.post("/api/v1/chat/stream", json={
            "scenario": "personnel_matching", "scenario_input": {"position_id": "senior"},
            "message": "match",
        }, headers={**HEADERS, "X-Audience": "internal"}).status_code == 403


def test_progress_scope_and_reassessment(app):
    application, principal = app
    with TestClient(application) as client:
        seed(client)
        principal["identity"] = ChatIdentity("alice", "internal", frozenset({
            "chat:use_internal", "development:analyze", "development:self",
        }), "tenant-a")
        update = client.post("/api/v1/scenario/progress", json={
            "employee_id": "alice", "position_id": "senior",
            "completed_skills": {"python": 5},
        }, headers=HEADERS)
        assert update.status_code == 200
        assert update.json()["kind"] == "development_progress"
        response = client.post("/api/v1/chat/stream", json={
            "scenario": "personal_development",
            "scenario_input": {"employee_id": "alice", "target_position_id": "senior"},
            "message": "development plan",
        }, headers=HEADERS)
        trace = events(response)
        assert next(x["result"] for n, x in trace if n == "scenario_result")["items"][0]["progress_recorded"]
        assert client.post("/api/v1/scenario/progress", json={
            "employee_id": "someone-else", "position_id": "senior",
            "completed_skills": {"python": 5},
        }, headers=HEADERS).status_code == 403
