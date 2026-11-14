"""Validated Chat input and published SSE event payloads."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequestDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: str = Field(min_length=1, max_length=1000)
    conversation_id: UUID | None = Field(default=None, strict=False)
    scenario: Literal["general", "knowledge_qa"] = "general"

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
    scenario: Literal["general", "knowledge_qa"] = "general"
    route: Literal["direct_llm", "rag"] = "direct_llm"


class DeltaDto(BaseModel):
    text: str


class MessageEndDto(BaseModel):
    request_id: UUID
    message_id: UUID
    status: Literal["completed", "failed", "cancelled"]
    response_type: Literal["direct_generated", "rag_generated", "insufficient_evidence"] | None = None


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
