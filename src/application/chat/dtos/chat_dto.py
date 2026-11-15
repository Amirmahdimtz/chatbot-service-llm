"""Validated Chat input and published SSE event payloads."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, ValidationError

from src.core.services.scenarios.scenario_contracts import SCENARIO_INPUTS, ScenarioResult, ReligiousResult


class ChatRequestDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: str = Field(min_length=1, max_length=1000)
    conversation_id: UUID | None = Field(default=None, strict=False)
    scenario: Literal[
        "general", "knowledge_qa", "agent_qa", "religious_qa",
        "personnel_matching", "talent_discovery", "internal_transfers",
        "research_advice", "personal_development", "task_allocation",
    ] = "general"
    scenario_input: dict | None = None

    @model_validator(mode="after")
    def validate_scenario_input(self):
        if self.scenario in SCENARIO_INPUTS:
            if self.scenario_input is None:
                raise ValueError("Structured scenario_input is required")
            self.scenario_input = SCENARIO_INPUTS[self.scenario].model_validate(
                self.scenario_input).model_dump(mode="json")
        elif self.scenario_input is not None:
            raise ValueError("scenario_input not supported for this scenario")
        return self

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class MessageStartDto(BaseModel):
    request_id: UUID
    message_id: UUID
    conversation_id: UUID
    role: Literal["assistant"] = "assistant"
    scenario: Literal[
        "general", "knowledge_qa", "agent_qa", "religious_qa",
        "personnel_matching", "talent_discovery", "internal_transfers",
        "research_advice", "personal_development", "task_allocation",
    ] = "general"
    route: Literal["direct_llm", "rag", "agent"] = "direct_llm"


class DeltaDto(BaseModel):
    text: str


class MessageEndDto(BaseModel):
    request_id: UUID
    message_id: UUID
    status: Literal["completed", "failed", "cancelled"]
    response_type: Literal[
        "direct_generated", "rag_generated", "insufficient_evidence",
        "agent_generated", "verified_faq",
    ] | None = None


class ChatErrorDto(BaseModel):
    code: str
    message: str
    request_id: UUID
    message_id: UUID | None = None


class SourceDto(BaseModel):
    document_id: UUID
    title: str
    chunk_id: UUID
    source_location: dict = Field(default_factory=dict)
    page: int | None = Field(default=None, ge=1)
    version: int = Field(ge=1)


class SourcesDto(BaseModel):
    documents: list[SourceDto]


class ToolStartDto(BaseModel):
    tool: str = Field(min_length=1, max_length=64)
    call_id: UUID


class ToolResultDto(BaseModel):
    tool: str = Field(min_length=1, max_length=64)
    call_id: UUID
    status: Literal["completed"]
    item_count: int = Field(ge=0)


class ScenarioResultEventDto(BaseModel):
    result: ScenarioResult | ReligiousResult = Field(discriminator="scenario")

