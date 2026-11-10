"""Validated one-shot chat input and the documented SSE event payloads."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequestDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: str = Field(min_length=1, max_length=1000, description="One user message; no history in stage 3")
    conversation_id: UUID | None = Field(
        default=None, description="Reserved for stage 4; non-null IDs are rejected until ownership is enforced"
    )

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
    conversation_id: UUID | None = None
    role: Literal["assistant"] = "assistant"


class DeltaDto(BaseModel):
    text: str


class MessageEndDto(BaseModel):
    request_id: UUID
    message_id: UUID
    status: Literal["completed", "failed", "cancelled"]


class ChatErrorDto(BaseModel):
    code: str
    message: str
    request_id: UUID
    message_id: UUID | None = None


class SourceDto(BaseModel):
    """Future RAG event schema; stage 3 never emits a source."""

    document_id: UUID
    title: str
    page: int | None = Field(default=None, ge=1)
    version: int | None = Field(default=None, ge=1)


class SourcesDto(BaseModel):
    documents: list[SourceDto]
