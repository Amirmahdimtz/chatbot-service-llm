"""Strict schemas for imported synthetic/organizational records and scenario requests."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="before")
    @classmethod
    def validate_non_blank_strings(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            raise ValueError("Blank record fields are not permitted")
        return value


class FaqRecord(StrictRecord):
    question: str = Field(min_length=5, max_length=1000)
    answer: str = Field(min_length=5, max_length=4000)
    aliases: list[str] = Field(default_factory=list, max_length=10)
    source_reference: str = Field(min_length=3, max_length=200)
    source_title: str = Field(min_length=3, max_length=200)
    expert_reference: str = Field(min_length=3, max_length=200)

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, aliases: list[str]) -> list[str]:
        if any(not alias.strip() or len(alias) > 1000 for alias in aliases):
            raise ValueError("Invalid FAQ aliases")
        return aliases


class PersonnelRecord(StrictRecord):
    skills: dict[str, int] = Field(max_length=50)
    years_experience: int = Field(ge=0, le=80)
    unit_id: str = Field(min_length=1, max_length=100)
    position_id: str = Field(min_length=1, max_length=100)
    available: bool = True
    transfer_allowed: bool = False
    blocked_units: list[str] = Field(default_factory=list, max_length=30)
    goals: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("skills")
    @classmethod
    def skill_levels(cls, skills: dict[str, int]) -> dict[str, int]:
        if any(not 1 <= level <= 5 or not name.strip() or len(name) > 80 for name, level in skills.items()):
            raise ValueError("Skill levels must be 1..5")
        return skills


class PositionRecord(StrictRecord):
    title: str = Field(min_length=1, max_length=200)
    unit_id: str = Field(min_length=1, max_length=100)
    required_skills: dict[str, int] = Field(default_factory=dict, max_length=50)
    preferred_skills: dict[str, int] = Field(default_factory=dict, max_length=50)
    min_experience_years: int = Field(default=0, ge=0, le=80)
    open_slots: int = Field(default=0, ge=0, le=10000)

    @field_validator("required_skills", "preferred_skills")
    @classmethod
    def skill_levels(cls, skills: dict[str, int]) -> dict[str, int]:
        if any(not 1 <= level <= 5 or not name.strip() or len(name) > 80 for name, level in skills.items()):
            raise ValueError("Skill levels must be 1..5")
        return skills


class UnitRecord(StrictRecord):
    name: str = Field(min_length=1, max_length=200)
    skills: list[str] = Field(default_factory=list, max_length=100)
    headcount_limit: int = Field(ge=0, le=100000)
    current_headcount: int = Field(ge=0, le=100000)
    capacity_hours: int = Field(ge=0, le=1000000)
    committed_hours: int = Field(ge=0, le=1000000)


class ResearchRecord(StrictRecord):
    title: str = Field(min_length=3, max_length=200)
    problem: str = Field(min_length=5, max_length=2000)
    context_tags: list[str] = Field(min_length=1, max_length=20)
    solution: str = Field(min_length=5, max_length=2000)
    benefits: list[str] = Field(min_length=1, max_length=10)
    risks: list[str] = Field(min_length=1, max_length=10)
    assumptions: list[str] = Field(min_length=1, max_length=10)
    evaluation_metrics: list[str] = Field(min_length=1, max_length=10)
    source_reference: str = Field(min_length=3, max_length=200)


class TaskRecord(StrictRecord):
    task_id: str = Field(min_length=1, max_length=100)
    hours: int = Field(ge=1, le=100000)
    required_skills: list[str] = Field(default_factory=list, max_length=20)
    depends_on: list[str] = Field(default_factory=list, max_length=30)
    preferred_units: list[str] = Field(default_factory=list, max_length=30)


class TaskPlanRecord(StrictRecord):
    objective: str = Field(min_length=3, max_length=1000)
    tasks: list[TaskRecord] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_tasks(self):
        ids = [task.task_id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("Task IDs must be unique")
        if any(task.task_id in task.depends_on for task in self.tasks):
            raise ValueError("Self-dependent task")
        return self


class DevelopmentProgressRecord(StrictRecord):
    employee_id: str = Field(min_length=1, max_length=100)
    position_id: str = Field(min_length=1, max_length=100)
    completed_skills: dict[str, int] = Field(default_factory=dict, max_length=50)

    @field_validator("completed_skills")
    @classmethod
    def progress_levels(cls, levels: dict[str, int]) -> dict[str, int]:
        if any(not 1 <= value <= 5 or not key.strip() for key, value in levels.items()):
            raise ValueError("Invalid progress level")
        return levels


RECORD_TYPES: dict[str, type[BaseModel]] = {
    "faq": FaqRecord,
    "personnel": PersonnelRecord,
    "position": PositionRecord,
    "unit": UnitRecord,
    "research": ResearchRecord,
    "task_plan": TaskPlanRecord,
    "development_progress": DevelopmentProgressRecord,
}


class MatchingInput(StrictRecord):
    position_id: str = Field(min_length=1, max_length=100)


class TalentInput(StrictRecord):
    employee_id: str = Field(min_length=1, max_length=100)


class TransferInput(StrictRecord):
    employee_id: str = Field(min_length=1, max_length=100)


class ResearchInput(StrictRecord):
    context_tags: list[str] = Field(default_factory=list, max_length=20)
    include_knowledge: bool = False


class DevelopmentInput(StrictRecord):
    employee_id: str = Field(min_length=1, max_length=100)
    target_position_id: str = Field(min_length=1, max_length=100)
    weeks: int = Field(default=8, ge=1, le=52)


class AllocationInput(StrictRecord):
    plan_id: str = Field(min_length=1, max_length=100)


SCENARIO_INPUTS: dict[str, type[BaseModel]] = {
    "personnel_matching": MatchingInput,
    "talent_discovery": TalentInput,
    "internal_transfers": TransferInput,
    "research_advice": ResearchInput,
    "personal_development": DevelopmentInput,
    "task_allocation": AllocationInput,
}



class SkillGap(StrictRecord):
    current: int = Field(ge=0, le=5)
    required: int = Field(ge=1, le=5)


class MatchingItem(StrictRecord):
    candidate_id: str = Field(min_length=1, max_length=100)
    satisfied_hard_requirements: list[str]
    matched_preferred: list[str]
    unmatched_preferred: list[str]
    preferred_match_count: int = Field(ge=0)
    limitations: list[str]

    @model_validator(mode="after")
    def count_matches(self):
        if self.preferred_match_count != len(self.matched_preferred):
            raise ValueError("Invalid preferred skill match count")
        return self


class TalentItem(StrictRecord):
    position_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    eligible: bool
    skill_gaps: dict[str, SkillGap]
    experience_gap_years: int = Field(ge=0)
    goal_alignment: list[str]
    limitations: list[str]


class TransferItem(StrictRecord):
    employee_id: str = Field(min_length=1, max_length=100)
    position_id: str = Field(min_length=1, max_length=100)
    destination_unit_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1)
    operational_change: Literal[False]


class ResearchItem(StrictRecord):
    experience_id: str = Field(min_length=1, max_length=100)
    title: str
    shared_context: list[str] = Field(min_length=1)
    different_context: list[str]
    proposal: str
    benefits: list[str]
    risks: list[str]
    assumptions: list[str]
    evaluation_metrics: list[str]
    uncertainty: str


class DevelopmentStep(StrictRecord):
    skill: str
    current_level: int = Field(ge=0, le=5)
    target_level: int = Field(ge=1, le=5)
    action: str
    target_week: int = Field(ge=1, le=52)
    evaluation: str
    completed: bool


class DevelopmentItem(StrictRecord):
    employee_id: str
    target_position_id: str
    duration_weeks: int = Field(ge=1, le=52)
    steps: list[DevelopmentStep]
    remaining_skill_gaps: dict[str, SkillGap]
    progress_recorded: bool
    operational_change: Literal[False]


class AllocationItem(StrictRecord):
    task_id: str
    unit_id: str
    hours: int = Field(ge=1)
    depends_on: list[str]
    reason: str
    operational_change: Literal[False]


SCENARIO_OUTPUTS: dict[str, type[BaseModel]] = {
    "personnel_matching": MatchingItem,
    "talent_discovery": TalentItem,
    "internal_transfers": TransferItem,
    "research_advice": ResearchItem,
    "personal_development": DevelopmentItem,
    "task_allocation": AllocationItem,
}


class ReligiousResult(StrictRecord):
    scenario: Literal["religious_qa"]
    response_type: Literal["verified_faq", "rag_generated", "insufficient_evidence"]
    sources: list[dict[str, Any]]
    pending_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def provenance_required(self):
        if self.response_type == "verified_faq":
            if (len(self.sources) != 1 or self.sources[0].get("type") != "approved_faq"
                    or not self.sources[0].get("expert_reference") or self.pending_id is not None):
                raise ValueError("Approved FAQ requires an expert source")
        elif self.response_type == "rag_generated":
            if not self.sources or any("document_id" not in item for item in self.sources):
                raise ValueError("RAG requires document evidence")
        elif self.sources or not self.pending_id:
            raise ValueError("Insufficient evidence requires a pending record")
        return self

class ScenarioResult(StrictRecord):
    scenario: Literal[
        "personnel_matching", "talent_discovery", "internal_transfers",
        "research_advice", "personal_development", "task_allocation",
    ]
    status: Literal["completed", "insufficient_data", "conflict"]
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    limitations: list[str] = Field(default_factory=list, max_length=50)
    sources: list[dict[str, Any]] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_items(self):
        schema = SCENARIO_OUTPUTS[self.scenario]
        self.items = [
            schema.model_validate(item).model_dump(mode="json") for item in self.items
        ]
        return self

