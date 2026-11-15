"""Stage 8 deterministic algorithms and scope/security regression with synthetic records."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.errors import PermissionDenied
from src.core.services.rag.rag_service import RagContext
from src.core.services.scenarios.scenario_contracts import (
    FaqRecord, PersonnelRecord, PositionRecord, TaskPlanRecord,
)
from src.core.services.scenarios.scenario_service import ScenarioService

PUBLIC = ChatIdentity("public-demo", "public")
STAFF = ChatIdentity("hr-demo", "internal", frozenset({
    "chat:use_internal", "hr:analyze", "research:analyze",
    "development:analyze", "tasks:analyze", "knowledge:read_internal",
}), "tenant-a")


@dataclass
class Row:
    kind: str
    external_key: str
    payload: dict
    audience: str = "internal"
    tenant_key: str = "tenant-a"
    verified: bool = False
    version: int = 1
    id: str = ""

    def __post_init__(self):
        self.id = self.id or str(uuid4())


class Repository:
    def __init__(self):
        self.rows = []
        self.pending = []

    def add(self, kind, key, payload, *, tenant="tenant-a", audience="internal",
            verified=False):
        row = Row(kind, key, payload, audience, tenant, verified)
        self.rows.append(row)
        return row

    async def list_scoped_async(self, audience, tenant_key, kind, limit=200):
        return [r for r in self.rows if r.audience == audience and
                r.tenant_key == tenant_key and r.kind == kind][:limit]

    async def get_scoped_async(self, audience, tenant_key, kind, key):
        return next((r for r in self.rows if r.audience == audience
                     and r.tenant_key == tenant_key and r.kind == kind
                     and r.external_key == key), None)

    async def register_pending_async(self, audience, tenant_key, owner_id, key, payload):
        self.pending.append((audience, tenant_key, owner_id, key, payload))


class Rag:
    def __init__(self, sources=()):
        self.sources = sources
        self.scopes = []
        self.INSUFFICIENT_MESSAGE = "شواهد کافی یافت نشد"

    async def prepare_async(self, identity, query):
        self.scopes.append((identity, query))
        return RagContext("synthetic untrusted evidence" if self.sources else "", self.sources)


def seed(repo):
    repo.add("personnel", "alice", {"skills": {"python": 4, "sql": 4}, "years_experience": 5,
             "unit_id": "u1", "position_id": "junior", "transfer_allowed": True})
    repo.add("personnel", "bob", {"skills": {"python": 4}, "years_experience": 2,
             "unit_id": "u1", "position_id": "junior", "available": True})
    repo.add("position", "senior", {"title": "Senior python", "unit_id": "u2",
             "required_skills": {"python": 3, "sql": 3},
             "preferred_skills": {"python": 4}, "min_experience_years": 3, "open_slots": 2})
    repo.add("position", "lead", {"title": "Engineering leader", "unit_id": "u3",
             "required_skills": {"python": 5}, "open_slots": 1})
    repo.add("unit", "u1", {"name": "Current", "skills": ["python"],
             "headcount_limit": 5, "current_headcount": 3,
             "capacity_hours": 10, "committed_hours": 8})
    repo.add("unit", "u2", {"name": "Destination", "skills": ["python", "sql"],
             "headcount_limit": 2, "current_headcount": 1,
             "capacity_hours": 12, "committed_hours": 2})
    repo.add("unit", "u3", {"name": "Full", "skills": ["python"],
             "headcount_limit": 1, "current_headcount": 1,
             "capacity_hours": 4, "committed_hours": 4})
    repo.add("research", "case1", {
        "title": "Synthetic productivity case", "problem": "slow python pipeline",
        "context_tags": ["python", "pipeline"], "solution": "Test incremental batching",
        "benefits": ["Lower latency"], "risks": ["More retries"],
        "assumptions": ["Stable workload"], "evaluation_metrics": ["p95 latency"],
        "source_reference": "synthetic-case-1",
    })
    repo.add("task_plan", "p1", {"objective": "Synthetic deployment", "tasks": [
        {"task_id": "prepare", "hours": 4, "required_skills": ["python"]},
        {"task_id": "deploy", "hours": 6, "required_skills": ["sql"],
         "depends_on": ["prepare"]},
    ]})


@pytest.mark.asyncio
async def test_verified_faq_exact_alias_and_unknown_pending_without_fabrication():
    repo = Repository()
    faq = FaqRecord(question="حکم یک نمونه آزمایشی چیست؟",
                    answer="پاسخ تأییدشده آزمایشی", aliases=["حکم نمونه چیست؟"],
                    source_reference="book-synthetic-01", source_title="مرجع ساختگی",
                    expert_reference="approved-expert-01").model_dump()
    repo.add("faq", "f1", faq, audience="public", tenant="", verified=True)
    repo.add("faq", "unapproved", {**faq, "answer": "NOT APPROVED"}, audience="public",
             tenant="", verified=False)
    rag = Rag()
    service = ScenarioService(repo, rag)
    result = await service.religious_async(PUBLIC, "حكم نمونه چيست؟")
    assert result.response_type == "verified_faq"
    assert result.answer == "پاسخ تأییدشده آزمایشی"
    assert result.sources[0]["expert_reference"] == "approved-expert-01"
    assert rag.scopes == []
    unknown = await service.religious_async(PUBLIC, "پرسش کاملاً متفاوت")
    assert unknown.response_type == "insufficient_evidence"
    assert unknown.pending_id and len(repo.pending) == 1
    assert repo.pending[0][2] == PUBLIC.subject
    assert "NOT APPROVED" not in unknown.answer


@pytest.mark.asyncio
async def test_religious_rag_not_confused_with_verified_faq_and_internal_scope():
    repo = Repository()
    rag = Rag(({"document_id": str(uuid4()), "chunk_id": str(uuid4()),
                "title": "Synthetic", "version": 1},))
    decision = await ScenarioService(repo, rag).religious_async(PUBLIC, "پرسش جدید")
    assert decision.response_type == "rag_generated"
    assert decision.answer == ""
    assert decision.evidence == "synthetic untrusted evidence"
    assert rag.scopes == [(PUBLIC, "پرسش جدید")]


@pytest.mark.asyncio
async def test_matching_hard_constraints_and_explainable_preference_order():
    repo = Repository()
    seed(repo)
    result = await ScenarioService(repo, Rag()).analyze_async(
        "personnel_matching", {"position_id": "senior"}, STAFF, "match candidates")
    assert result.status == "completed"
    assert [r["candidate_id"] for r in result.items] == ["alice"]
    assert result.items[0]["matched_preferred"] == ["python"]
    assert "score" not in result.items[0]
    missing = await ScenarioService(repo, Rag()).analyze_async(
        "personnel_matching", {"position_id": "unknown"}, STAFF, "match")
    assert missing.status == "insufficient_data"


@pytest.mark.asyncio
async def test_talent_qualification_skill_gap_and_transfer_policy_capacity():
    repo = Repository()
    seed(repo)
    service = ScenarioService(repo, Rag())
    talent = await service.analyze_async(
        "talent_discovery", {"employee_id": "alice"}, STAFF, "careers")
    assert talent.items[0]["position_id"] == "senior"
    assert talent.items[0]["eligible"] is True
    assert talent.items[1]["skill_gaps"]["python"]["required"] == 5
    transfer = await service.analyze_async(
        "internal_transfers", {"employee_id": "alice"}, STAFF, "transfers")
    assert [x["destination_unit_id"] for x in transfer.items] == ["u2"]
    assert all(x["operational_change"] is False for x in transfer.items)
    assert any("lead" in limitation for limitation in transfer.limitations)


@pytest.mark.asyncio
async def test_research_grounded_citation_and_development_progress():
    repo = Repository()
    seed(repo)
    service = ScenarioService(repo, Rag())
    research = await service.analyze_async(
        "research_advice", {"context_tags": ["pipeline"]}, STAFF, "python problem")
    assert research.items[0]["proposal"] == "Test incremental batching"
    assert research.sources[0]["source_reference"] == "synthetic-case-1"
    empty = await service.analyze_async("research_advice", {}, STAFF, "unrelated")
    assert empty.status == "insufficient_data" and not empty.sources
    plan = await service.analyze_async("personal_development", {
        "employee_id": "alice", "target_position_id": "lead", "weeks": 8,
    }, STAFF, "career")
    assert plan.items[0]["steps"][0]["skill"] == "python"
    assert plan.items[0]["steps"][0]["target_level"] == 5
    repo.add("development_progress", service.progress_key("alice", "lead"), {
        "employee_id": "alice", "position_id": "lead", "completed_skills": {"python": 5},
    })
    updated = await service.analyze_async("personal_development", {
        "employee_id": "alice", "target_position_id": "lead",
    }, STAFF, "career")
    assert updated.items[0]["progress_recorded"] is True
    assert not updated.items[0]["remaining_skill_gaps"]


@pytest.mark.asyncio
async def test_task_dependency_capacity_conflicts_and_no_mutation():
    repo = Repository()
    seed(repo)
    service = ScenarioService(repo, Rag())
    valid = await service.analyze_async("task_allocation", {"plan_id": "p1"}, STAFF, "assign")
    assert [item["task_id"] for item in valid.items] == ["prepare", "deploy"]
    assert all(not item["operational_change"] for item in valid.items)
    assert valid.status == "completed"
    repo.add("task_plan", "cycle", {"objective": "Synthetic cyclic tasks", "tasks": [
        {"task_id": "a", "hours": 1, "depends_on": ["b"]},
        {"task_id": "b", "hours": 1, "depends_on": ["a"]},
    ]})
    cycle = await service.analyze_async("task_allocation", {"plan_id": "cycle"}, STAFF, "assign")
    assert cycle.status == "conflict"
    assert "Circular" in cycle.limitations[0]
    repo.add("task_plan", "large", {"objective": "Oversized synthetic plan", "tasks": [
        {"task_id": "huge", "hours": 100000, "required_skills": ["python"]},
    ]})
    shortage = await service.analyze_async("task_allocation", {"plan_id": "large"}, STAFF, "assign")
    assert shortage.status == "conflict" and not shortage.items


@pytest.mark.asyncio
async def test_public_and_cross_tenant_fail_closed_and_inputs_are_strict():
    repo = Repository()
    seed(repo)
    service = ScenarioService(repo, Rag())
    for scenario, params in [
        ("personnel_matching", {"position_id": "senior"}),
        ("talent_discovery", {"employee_id": "alice"}),
        ("internal_transfers", {"employee_id": "alice"}),
        ("research_advice", {}),
        ("personal_development", {"employee_id": "alice", "target_position_id": "lead"}),
        ("task_allocation", {"plan_id": "p1"}),
    ]:
        with pytest.raises(PermissionDenied):
            await service.analyze_async(scenario, params, PUBLIC, "private info")
    other_tenant = ChatIdentity(STAFF.subject, "internal", STAFF.permissions, "tenant-b")
    outcome = await service.analyze_async(
        "personnel_matching", {"position_id": "senior"}, other_tenant, "match")
    assert outcome.items == [] and outcome.status == "insufficient_data"
    with pytest.raises(Exception):
        await service.analyze_async(
            "personnel_matching", {"position_id": "senior", "tenant_id": "tenant-a"},
            STAFF, "match")
    with pytest.raises(PermissionDenied):
        await service.upsert_record_async(PUBLIC, "personnel", "evil", {}, "internal")


def test_import_contract_rejects_unrelated_sensitive_fields():
    with pytest.raises(Exception):
        PersonnelRecord.model_validate({
            "skills": {"python": 4}, "unit_id": "u1", "position_id": "p1",
            "years_experience": 2, "religion": "not job-relevant",
        })
    with pytest.raises(Exception):
        PositionRecord.model_validate({
            "title": "role", "unit_id": "u1", "required_skills": {"python": 6}})
    with pytest.raises(Exception):
        TaskPlanRecord.model_validate({
            "objective": "synthetic", "tasks": [
                {"task_id": "duplicate", "hours": 1},
                {"task_id": "duplicate", "hours": 1},
            ]})
