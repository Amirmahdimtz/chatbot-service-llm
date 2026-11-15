"""Stage 9: versioned synthetic dataset, seven-scenario HTTP/SSE/SQL acceptance."""
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
from src.infrastructure.scripts.seed_stage9 import (
    FIXTURE, FixtureError, load_fixture, require_isolated_database,
)
from src.infrastructure.utils.config_reader import ConfigReader

TOKEN = "stage9-" + "t" * 44
HEADERS = {"Authorization": "Bearer " + TOKEN}
MANAGER = ChatIdentity("stage9-manager", "internal", frozenset({
    "chat:use_internal", "scenario:manage", "religious:verify",
    "hr:analyze", "research:analyze", "development:analyze", "tasks:analyze",
    "knowledge:read_internal", "knowledge:read_public",
}), "stage9-synthetic")


@pytest.fixture
def application(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV_TYPE", "development")
    monkeypatch.setenv("CHATBOT_DEV_API_TOKEN", TOKEN)
    monkeypatch.setenv("CHATBOT_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'stage9_api.sqlite').as_posix()}")
    install_providers(discover_providers())
    load_models()
    web_app = WebService(ConfigReader()).create_app()
    db = resolve(PsqlDbContext)

    async def create_schema_async():
        async with db.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema_async())
    principal = {"identity": MANAGER}
    monkeypatch.setattr(ChatIdentityService, "authenticate", lambda self, auth: principal["identity"])

    async def no_evidence(self, identity, query):
        return RagContext("", ())

    monkeypatch.setattr(RagService, "prepare_async", no_evidence)
    return web_app, principal


def trace(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = []
    for frame in response.text.strip().split("\n\n"):
        lines = frame.splitlines()
        assert len(lines) >= 2 and lines[0].startswith("event: ") and lines[1].startswith("data: ")
        frames.append((lines[0][7:], json.loads(lines[1][6:])))
    return frames


def test_fixture_schema_validation_and_isolated_seed_guard(monkeypatch, tmp_path):
    fixture, digest = load_fixture()
    assert len(digest) == 64
    assert len(fixture["records"]) >= 15
    assert {case["scenario"] for case in fixture["cases"]} == {
        "religious_qa", "personnel_matching", "talent_discovery", "internal_transfers",
        "research_advice", "personal_development", "task_allocation",
    }
    assert len(fixture["cases"]) >= 13
    assert all("religion" not in row["payload"] for row in fixture["records"] if row["kind"] == "personnel")
    duplicate = dict(fixture)
    duplicate["records"] = fixture["records"] + [fixture["records"][0]]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(duplicate, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(FixtureError, match="Duplicate"):
        load_fixture(path)
    monkeypatch.delenv("CHATBOT_STAGE9_ISOLATED", raising=False)
    with pytest.raises(FixtureError, match="CHATBOT_STAGE9_ISOLATED"):
        require_isolated_database("sqlite+aiosqlite:///stage9_example.sqlite")
    monkeypatch.setenv("CHATBOT_STAGE9_ISOLATED", "1")
    assert require_isolated_database("sqlite+aiosqlite:///stage9_example.sqlite")
    assert require_isolated_database(
        "postgresql+asyncpg://user:password@postgres:5432/chatbot_stage9_ci"
    )
    for url in (
        "postgresql+asyncpg://user:password@postgres:5432/chatbot",
        "postgresql+asyncpg://user:password@remote.example:5432/chatbot_stage9_ci",
        "sqlite+aiosqlite:///production.db",
        "sqlite+aiosqlite:///:memory:",
    ):
        with pytest.raises(FixtureError, match="Refusing"):
            require_isolated_database(url)


def test_all_seven_scenarios_have_oracle_checked_sse_and_persistence(application):
    app, principal = application
    fixture, _ = load_fixture()
    id_field = {
        "personnel_matching": "candidate_id",
        "talent_discovery": "position_id",
        "internal_transfers": "position_id",
        "research_advice": "experience_id",
        "personal_development": "employee_id",
        "task_allocation": "task_id",
    }
    with TestClient(app) as client:
        for row in fixture["records"]:
            response = client.put(
                f"/api/v1/scenario/records/{row['kind']}/{row['key']}",
                headers=HEADERS,
                json={"audience": row.get("audience", "internal"), "payload": row["payload"]},
            )
            assert response.status_code == 200, (row["key"], response.text)
        for case in fixture["cases"]:
            principal["identity"] = (ChatIdentity("synthetic-public", "public")
                                     if case["scenario"] == "religious_qa" else MANAGER)
            response = client.post(
                "/api/v1/chat/stream", headers=HEADERS,
                json={"scenario": case["scenario"], "message": case["message"],
                      **({"scenario_input": case["scenario_input"]}
                         if "scenario_input" in case else {})},
            )
            events = trace(response)
            names = [name for name, _ in events]
            assert names[0] == "message_start" and names[-1] == "message_end"
            assert names.count("scenario_result") == 1
            assert names.count("delta") >= 1
            assert events[-1][1]["status"] == "completed", case["name"]
            result = next(payload["result"] for name, payload in events if name == "scenario_result")
            if case["scenario"] == "religious_qa":
                assert result["response_type"] == case["expected_response_type"], case["name"]
                if result["response_type"] == "verified_faq":
                    assert len(result["sources"]) == 1
                    assert result["sources"][0]["source_reference"] == case["expected_source_reference"]
                    assert result["sources"][0]["type"] == "approved_faq"
                else:
                    assert result["sources"] == [] and result["pending_id"]
                    pending = client.get(
                        f"/api/v1/scenario/pending/{result['pending_id']}", headers=HEADERS
                    )
                    assert pending.status_code == 200
            else:
                assert result["scenario"] == case["scenario"]
                assert result["status"] == case["expected_status"], case["name"]
                actual = [item[id_field[case["scenario"]]] for item in result["items"]]
                assert actual == case["expected_ids"], case["name"]
                assert not (set(actual) & set(case.get("excluded_ids", [])))
                if case["scenario"] in {"internal_transfers", "personal_development", "task_allocation"}:
                    assert all(item["operational_change"] is False for item in result["items"])
                if case["scenario"] == "research_advice" and result["items"]:
                    assert len(result["sources"]) == len(result["items"])
                    assert all(item["source_reference"].startswith("synthetic-")
                               for item in result["sources"])
            conversation_id = events[0][1]["conversation_id"]
            history = client.get(f"/api/v1/conversation/{conversation_id}", headers=HEADERS)
            assert history.status_code == 200
            assert history.json()["messages"][-1]["scenario_payload"] == result
            # Same-ID identity with another tenant cannot fetch persisted conversation.
            if case["scenario"] != "religious_qa":
                principal["identity"] = ChatIdentity(
                    MANAGER.subject, "internal", MANAGER.permissions, "other-tenant"
                )
                assert client.get(
                    f"/api/v1/conversation/{conversation_id}", headers=HEADERS
                ).status_code == 404
        principal["identity"] = MANAGER
        # Scenario recommendations never mutate the underlying position or staff.
        row = client.get("/api/v1/scenario/records/personnel/alice", headers=HEADERS)
        assert row.status_code == 200
        assert row.json()["payload"]["position_id"] == "junior"


def test_stage9_identity_forgery_sensitive_data_and_progress_scope(application):
    app, principal = application
    with TestClient(app) as client:
        principal["identity"] = ChatIdentity("public-only", "public")
        denied = client.put("/api/v1/scenario/records/personnel/hacker", headers=HEADERS,
                            json={"audience": "internal", "payload": {}})
        assert denied.status_code == 403
        assert client.post("/api/v1/chat/stream", headers=HEADERS, json={
            "scenario": "task_allocation", "message": "assign",
            "scenario_input": {"plan_id": "plan_valid"},
        }).status_code == 403
        assert client.post("/api/v1/chat/stream", headers={**HEADERS, "X-Tenant-ID": "stage9-synthetic"},
                           json={"scenario": "religious_qa", "message": "test"}).status_code == 403
        principal["identity"] = MANAGER
        invalid = client.put("/api/v1/scenario/records/personnel/injected", headers=HEADERS, json={
            "audience": "internal",
            "payload": {"skills": {"python": 4}, "years_experience": 5, "unit_id": "u1",
                        "position_id": "p1", "religion": "sensitive"},
        })
        assert invalid.status_code == 422
        principal["identity"] = ChatIdentity(
            "bob", "internal", frozenset({"chat:use_internal", "development:self",
                                          "development:analyze"}), "stage9-synthetic"
        )
        assert client.post("/api/v1/scenario/progress", headers=HEADERS, json={
            "employee_id": "alice", "position_id": "senior", "completed_skills": {"sql": 4},
        }).status_code == 403


def test_stage9_production_without_identity_fails_closed(monkeypatch):
    from src.core.services.chat.chat_identity_service import ChatIdentityService

    class Config:
        def get(self, key, default=None):
            return {"auth.dev_enabled": True, "auth.dev_api_token": "x" * 48}.get(key, default)

    monkeypatch.setenv("ENV_TYPE", "production")
    assert ChatIdentityService(Config()).authenticate("Bearer " + "x" * 48) is None
