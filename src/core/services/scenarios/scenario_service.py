"""Tenant-isolated, deterministic domain analysis for all seven Stage 8 workflows."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Any

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.errors import PermissionDenied, ResourceNotFound
from src.core.services.rag.rag_service import RagService
from src.core.services.scenarios.scenario_contracts import (
    AllocationInput, DevelopmentInput, DevelopmentProgressRecord, FaqRecord,
    MatchingInput, PersonnelRecord, PositionRecord, RECORD_TYPES, ResearchInput,
    ResearchRecord, SCENARIO_INPUTS, ScenarioResult, TalentInput, TaskPlanRecord,
    TransferInput, UnitRecord,
)
from src.infrastructure.di.inject import inject
from src.infrastructure.models.scenario_record import ScenarioRecord
from src.infrastructure.repositories.scenario.scenario_repository import ScenarioRepository

_INTERNAL_PERMISSIONS = {
    "personnel_matching": "hr:analyze",
    "talent_discovery": "hr:analyze",
    "internal_transfers": "hr:analyze",
    "research_advice": "research:analyze",
    "personal_development": "development:analyze",
    "task_allocation": "tasks:analyze",
}


def _normalize(text: str) -> str:
    text = text.casefold().translate(str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه"}))
    text = re.sub(r"[؟?!.,،؛:؛]+", " ", text)
    return " ".join(text.split())


def _tokens(text: str) -> set[str]:
    return {part for part in _normalize(text).split() if len(part) >= 3}


@dataclass(frozen=True)
class ReligiousDecision:
    response_type: str
    answer: str
    sources: tuple[dict, ...]
    evidence: str = ""
    pending_id: str | None = None


@inject
class ScenarioService:
    def __init__(self, scenario_repository: ScenarioRepository, rag_service: RagService):
        self._records = scenario_repository
        self._rag = rag_service

    @staticmethod
    def authorize(identity: ChatIdentity, scenario: str) -> None:
        if (not isinstance(identity, ChatIdentity) or not identity.subject.strip()
                or identity.audience not in {"public", "internal"}):
            raise PermissionDenied("Trusted identity required")
        if identity.audience == "public":
            if identity.tenant_id is not None or scenario != "religious_qa":
                raise PermissionDenied("Internal workflow not permitted")
            return
        if not identity.tenant_id or not identity.tenant_id.strip():
            raise PermissionDenied("Tenant required")
        if scenario == "religious_qa":
            if "knowledge:read_internal" not in identity.permissions:
                raise PermissionDenied("Knowledge permission required")
        elif _INTERNAL_PERMISSIONS.get(scenario) not in identity.permissions:
            raise PermissionDenied("Scenario permission required")

    @staticmethod
    def progress_key(employee_id: str, position_id: str) -> str:
        return sha256((employee_id + ":" + position_id).encode("utf-8")).hexdigest()

    async def upsert_record_async(self, identity: ChatIdentity, kind: str, key: str,
                                  payload: dict, audience: str = "internal") -> ScenarioRecord:
        if (not isinstance(identity, ChatIdentity) or identity.audience != "internal"
                or not identity.tenant_id or not identity.subject.strip()):
            raise PermissionDenied("Trusted internal tenant required")
        schema = RECORD_TYPES.get(kind)
        if schema is None:
            raise ValueError("Unsupported record kind")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", key):
            raise ValueError("Invalid record key")
        if kind == "faq":
            if "religious:verify" not in identity.permissions:
                raise PermissionDenied("Only approved experts can verify FAQ")
            if audience not in {"public", "internal"}:
                raise ValueError("Invalid FAQ audience")
        elif kind == "development_progress" and "scenario:manage" not in identity.permissions:
            if ("development:self" not in identity.permissions
                    or payload.get("employee_id") != identity.subject):
                raise PermissionDenied("Progress write not permitted")
        else:
            if "scenario:manage" not in identity.permissions:
                raise PermissionDenied("Record management not permitted")
            if audience != "internal":
                raise PermissionDenied("Non-FAQ records must remain internal")
        data = schema.model_validate(payload).model_dump(mode="json")
        if kind == "development_progress" and key != self.progress_key(
                data["employee_id"], data["position_id"]):
            raise ValueError("Invalid development progress key")
        return await self._records.upsert_scoped_async(
            audience, "" if audience == "public" else identity.tenant_id,
            identity.subject, kind, key, data, verified=kind == "faq",
        )

    async def get_record_async(self, identity: ChatIdentity, kind: str, key: str,
                               audience: str) -> ScenarioRecord:
        if not isinstance(identity, ChatIdentity) or identity.audience != "internal" or not identity.tenant_id:
            raise PermissionDenied("Internal identity required")
        if kind == "faq" and "religious:verify" in identity.permissions:
            if audience not in {"public", "internal"}:
                raise PermissionDenied("Invalid audience")
        elif "scenario:manage" not in identity.permissions or audience != "internal":
            raise PermissionDenied("Record read not permitted")
        if kind not in RECORD_TYPES:
            raise ValueError("Invalid kind")
        record = await self._records.get_scoped_async(
            audience, "" if audience == "public" else identity.tenant_id, kind, key)
        if record is None:
            raise ResourceNotFound("Record not found")
        return record

    async def get_pending_async(self, identity: ChatIdentity, key: str) -> str:
        if (not isinstance(identity, ChatIdentity) or not identity.subject.strip()
                or identity.audience not in {"public", "internal"}
                or (identity.audience == "public" and identity.tenant_id is not None)
                or (identity.audience == "internal" and not identity.tenant_id)):
            raise PermissionDenied("Identity not permitted")
        record = await self._records.get_scoped_async(
            identity.audience, identity.tenant_id or "", "faq_pending", key)
        if record is None or record.owner_id != identity.subject:
            raise ResourceNotFound("Pending record not found")
        return record.payload["status"]

    async def _list_async(self, identity: ChatIdentity, kind: str) -> list[ScenarioRecord]:
        return await self._records.list_scoped_async("internal", identity.tenant_id or "", kind)

    async def _get_async(self, identity: ChatIdentity, kind: str, key: str) -> ScenarioRecord | None:
        return await self._records.get_scoped_async("internal", identity.tenant_id or "", kind, key)

    async def religious_async(self, identity: ChatIdentity, question: str) -> ReligiousDecision:
        self.authorize(identity, "religious_qa")
        matches: list[ScenarioRecord] = []
        public = await self._records.list_scoped_async("public", "", "faq")
        available = public
        if identity.audience == "internal":
            available = await self._list_async(identity, "faq")
            if "knowledge:read_public" in identity.permissions:
                available += public
        normalized = _normalize(question)
        for record in available:
            if not record.verified:
                continue
            faq = FaqRecord.model_validate(record.payload)
            if normalized in {_normalize(faq.question), *(_normalize(a) for a in faq.aliases)}:
                matches.append(record)
        if len(matches) == 1:
            match = matches[0]
            faq = FaqRecord.model_validate(match.payload)
            return ReligiousDecision("verified_faq", faq.answer, ({
                "type": "approved_faq", "record_id": match.id,
                "source_reference": faq.source_reference, "source_title": faq.source_title,
                "expert_reference": faq.expert_reference, "version": match.version,
            },))
        # Ambiguous FAQ matches must not be treated as expert-approved answers.
        context = await self._rag.prepare_async(identity, question)
        if context.sources:
            return ReligiousDecision("rag_generated", "", context.sources, context.evidence)
        # Record incomplete evidence without creating an external referral system.
        scope = f"{identity.audience}:{identity.tenant_id or ''}:{identity.subject}:{normalized}"
        key = sha256(scope.encode("utf-8")).hexdigest()
        await self._records.register_pending_async(
            identity.audience, identity.tenant_id or "", identity.subject, key,
            {"question": question, "status": "insufficient_evidence"},
        )
        return ReligiousDecision("insufficient_evidence", self._rag.INSUFFICIENT_MESSAGE, (), pending_id=key)

    @staticmethod
    def _result(scenario: str, items: list[dict], limitations: list[str],
                sources: list[dict] | None = None, conflict: bool = False) -> ScenarioResult:
        status = "conflict" if conflict else ("completed" if items else "insufficient_data")
        return ScenarioResult.model_validate({
            "scenario": scenario, "status": status, "items": items,
            "limitations": limitations, "sources": sources or [],
        })

    @staticmethod
    def _gaps(employee: PersonnelRecord, position: PositionRecord) -> dict[str, dict[str, int]]:
        return {
            skill: {"current": employee.skills.get(skill, 0), "required": minimum}
            for skill, minimum in position.required_skills.items()
            if employee.skills.get(skill, 0) < minimum
        }

    async def analyze_async(self, scenario: str, values: dict, identity: ChatIdentity,
                            message: str) -> ScenarioResult:
        self.authorize(identity, scenario)
        schema = SCENARIO_INPUTS.get(scenario)
        if schema is None:
            raise ValueError("Unsupported structured scenario")
        data = schema.model_validate(values)
        if scenario == "personnel_matching":
            return await self._matching_async(identity, data)
        if scenario == "talent_discovery":
            return await self._talent_async(identity, data)
        if scenario == "internal_transfers":
            return await self._transfers_async(identity, data)
        if scenario == "research_advice":
            return await self._research_async(identity, data, message)
        if scenario == "personal_development":
            return await self._development_async(identity, data)
        return await self._allocation_async(identity, data)

    async def _matching_async(self, identity: ChatIdentity, data: MatchingInput) -> ScenarioResult:
        position_row = await self._get_async(identity, "position", data.position_id)
        if position_row is None:
            return self._result("personnel_matching", [], ["Position not found in authorized tenant"])
        position = PositionRecord.model_validate(position_row.payload)
        if position.open_slots == 0:
            return self._result("personnel_matching", [], ["Position has no open slots"])
        items: list[dict] = []
        for record in await self._list_async(identity, "personnel"):
            employee = PersonnelRecord.model_validate(record.payload)
            gaps = self._gaps(employee, position)
            if gaps or employee.years_experience < position.min_experience_years or not employee.available:
                continue
            met = sorted(skill for skill, level in position.preferred_skills.items()
                         if employee.skills.get(skill, 0) >= level)
            unmet = sorted(set(position.preferred_skills) - set(met))
            items.append({
                "candidate_id": record.external_key,
                "satisfied_hard_requirements": sorted(position.required_skills),
                "matched_preferred": met, "unmatched_preferred": unmet,
                "preferred_match_count": len(met),
                "limitations": ["Employment decisions require human verification"],
            })
        items.sort(key=lambda item: (-item["preferred_match_count"], item["candidate_id"]))
        return self._result("personnel_matching", items[:position.open_slots],
                            [] if items else ["No eligible candidates in authorized records"])

    async def _talent_async(self, identity: ChatIdentity, data: TalentInput) -> ScenarioResult:
        row = await self._get_async(identity, "personnel", data.employee_id)
        if row is None:
            return self._result("talent_discovery", [], ["Employee not found"])
        employee = PersonnelRecord.model_validate(row.payload)
        items = []
        for position_row in await self._list_async(identity, "position"):
            position = PositionRecord.model_validate(position_row.payload)
            if position.open_slots == 0:
                continue
            gaps = self._gaps(employee, position)
            short_experience = max(0, position.min_experience_years - employee.years_experience)
            items.append({
                "position_id": position_row.external_key, "title": position.title,
                "eligible": not gaps and short_experience == 0,
                "skill_gaps": gaps, "experience_gap_years": short_experience,
                "goal_alignment": sorted(_tokens(" ".join(employee.goals)) & _tokens(position.title)),
                "limitations": ["Eligibility depends on verified staff and position records"],
            })
        items.sort(key=lambda item: (not item["eligible"], len(item["skill_gaps"]),
                                     item["experience_gap_years"], item["position_id"]))
        return self._result("talent_discovery", items, [] if items else ["No open positions"])

    async def _transfers_async(self, identity: ChatIdentity, data: TransferInput) -> ScenarioResult:
        row = await self._get_async(identity, "personnel", data.employee_id)
        if row is None:
            return self._result("internal_transfers", [], ["Employee not found"])
        employee = PersonnelRecord.model_validate(row.payload)
        units = {row.external_key: UnitRecord.model_validate(row.payload)
                 for row in await self._list_async(identity, "unit")}
        if employee.unit_id not in units:
            return self._result("internal_transfers", [], ["Current unit capacity is unknown"])
        items, limitations = [], []
        for pos_row in await self._list_async(identity, "position"):
            position = PositionRecord.model_validate(pos_row.payload)
            unit = units.get(position.unit_id)
            if unit is None:
                limitations.append("Missing destination unit: " + position.unit_id)
                continue
            if position.unit_id == employee.unit_id:
                continue
            conflicts = []
            if not employee.transfer_allowed:
                conflicts.append("Transfer is not authorized by personnel policy")
            if position.unit_id in employee.blocked_units:
                conflicts.append("Destination blocked")
            if position.open_slots < 1 or unit.current_headcount >= unit.headcount_limit:
                conflicts.append("No available destination capacity")
            if self._gaps(employee, position):
                conflicts.append("Mandatory job skills not met")
            if employee.years_experience < position.min_experience_years:
                conflicts.append("Minimum experience not met")
            if conflicts:
                limitations.append(pos_row.external_key + ": " + ", ".join(conflicts))
                continue
            items.append({
                "employee_id": data.employee_id, "position_id": pos_row.external_key,
                "destination_unit_id": position.unit_id,
                "reason": "All explicit transfer, capacity and job constraints satisfied",
                "operational_change": False,
            })
        return self._result("internal_transfers", items, limitations or (
            ["No compatible destination positions"] if not items else []))

    async def _research_async(self, identity: ChatIdentity, data: ResearchInput,
                              question: str) -> ScenarioResult:
        terms = _tokens(question) | {_normalize(tag) for tag in data.context_tags}
        items, sources = [], []
        for row in await self._list_async(identity, "research"):
            case = ResearchRecord.model_validate(row.payload)
            overlap = sorted(terms & (_tokens(case.problem) | {_normalize(t) for t in case.context_tags}))
            if not overlap:
                continue
            differences = sorted(set(map(_normalize, case.context_tags)) - terms)
            items.append({
                "experience_id": row.external_key, "title": case.title,
                "shared_context": overlap, "different_context": differences,
                "proposal": case.solution, "benefits": case.benefits, "risks": case.risks,
                "assumptions": case.assumptions, "evaluation_metrics": case.evaluation_metrics,
                "uncertainty": "Prior experience is not proof of future effectiveness",
            })
            sources.append({"type": "research_record", "record_id": row.id,
                            "version": row.version, "source_reference": case.source_reference})
        ordered = sorted(zip(items, sources), key=lambda x: (-len(x[0]["shared_context"]),
                                                              x[0]["experience_id"]))
        items = [item for item, _ in ordered[:10]]
        sources = [source for _, source in ordered[:10]]
        limitations = [] if items else ["No sufficiently similar authorized experience"]
        if data.include_knowledge:
            if "knowledge:read_internal" not in identity.permissions:
                raise PermissionDenied("Internal knowledge retrieval permission required")
            context = await self._rag.prepare_async(identity, question)
            sources.extend([dict(source, type="knowledge_document") for source in context.sources])
            if context.sources:
                limitations.append(
                    "Retrieved document excerpts need expert interpretation; no solution inferred from excerpts")
        return self._result("research_advice", items, limitations, sources)

    async def _development_async(self, identity: ChatIdentity,
                                 data: DevelopmentInput) -> ScenarioResult:
        if ("hr:analyze" not in identity.permissions and
                ("development:self" not in identity.permissions
                 or identity.subject != data.employee_id)):
            raise PermissionDenied("Employee development record not permitted")
        employee_row = await self._get_async(identity, "personnel", data.employee_id)
        position_row = await self._get_async(identity, "position", data.target_position_id)
        if employee_row is None or position_row is None:
            return self._result("personal_development", [], ["Employee or target position missing"])
        employee = PersonnelRecord.model_validate(employee_row.payload)
        position = PositionRecord.model_validate(position_row.payload)
        progress_row = await self._get_async(identity, "development_progress",
                                            self.progress_key(data.employee_id, data.target_position_id))
        progress = (DevelopmentProgressRecord.model_validate(progress_row.payload)
                    if progress_row else None)
        current = dict(employee.skills)
        if progress is not None:
            if progress.employee_id != data.employee_id or progress.position_id != data.target_position_id:
                raise PermissionDenied("Progress belongs to another employee")
            for skill, level in progress.completed_skills.items():
                current[skill] = max(current.get(skill, 0), level)
        adjusted = employee.model_copy(update={"skills": current})
        gaps = self._gaps(adjusted, position)
        steps = []
        for index, (skill, levels) in enumerate(sorted(gaps.items())):
            steps.append({
                "skill": skill, "current_level": levels["current"], "target_level": levels["required"],
                "action": "Complete assessed training and demonstrate skill",
                "target_week": min(data.weeks, max(1, (index + 1) * data.weeks // max(len(gaps), 1))),
                "evaluation": "Assessed skill level meets target level",
                "completed": False,
            })
        return self._result("personal_development", [{
            "employee_id": data.employee_id, "target_position_id": data.target_position_id,
            "duration_weeks": data.weeks, "steps": steps,
            "remaining_skill_gaps": gaps, "progress_recorded": progress is not None,
            "operational_change": False,
        }], ["Training timelines are planning targets, not guaranteed outcomes"])

    async def _allocation_async(self, identity: ChatIdentity,
                                data: AllocationInput) -> ScenarioResult:
        plan_row = await self._get_async(identity, "task_plan", data.plan_id)
        if plan_row is None:
            return self._result("task_allocation", [], ["Plan not found"])
        plan = TaskPlanRecord.model_validate(plan_row.payload)
        units = {row.external_key: UnitRecord.model_validate(row.payload)
                 for row in await self._list_async(identity, "unit")}
        tasks = {task.task_id: task for task in plan.tasks}
        missing = sorted({dep for task in plan.tasks for dep in task.depends_on if dep not in tasks})
        if missing:
            return self._result("task_allocation", [], ["Unknown dependencies: " + ", ".join(missing)],
                                conflict=True)
        # Kahn's topological ordering: rejects cycles and enforces predecessors first.
        deps = {key: set(task.depends_on) for key, task in tasks.items()}
        ordered = []
        while deps:
            ready = sorted(key for key, predecessors in deps.items() if not predecessors)
            if not ready:
                return self._result("task_allocation", [], ["Circular task dependencies"], conflict=True)
            for key in ready:
                ordered.append(key)
                del deps[key]
            for remaining in deps.values():
                remaining.difference_update(ready)
        remaining = {key: max(0, unit.capacity_hours - unit.committed_hours)
                     for key, unit in units.items()}
        items, limitations, assigned = [], [], set()
        for key in ordered:
            task = tasks[key]
            if any(dep not in assigned for dep in task.depends_on):
                limitations.append(key + ": predecessor is unallocated")
                continue
            options = [
                unit_id for unit_id, unit in units.items()
                if set(task.required_skills).issubset(set(unit.skills))
                and remaining[unit_id] >= task.hours
                and (not task.preferred_units or unit_id in task.preferred_units)
            ]
            if not options:
                limitations.append(key + ": missing responsibility or capacity")
                continue
            chosen = sorted(options, key=lambda candidate: (-remaining[candidate], candidate))[0]
            remaining[chosen] -= task.hours
            assigned.add(key)
            items.append({
                "task_id": key, "unit_id": chosen, "hours": task.hours,
                "depends_on": task.depends_on,
                "reason": "Required capabilities, explicit preference and remaining capacity",
                "operational_change": False,
            })
        return self._result("task_allocation", items, limitations,
                            conflict=bool(limitations))
