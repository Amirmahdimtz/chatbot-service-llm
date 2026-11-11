"""Conversation request/response models with stable pagination semantics."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationCreateDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str | None = Field(default=None, max_length=200)

    @field_validator("title")
    @classmethod
    def trim_title(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class ConversationMessageDto(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sequence: int
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    status: Literal["streaming", "completed", "failed", "cancelled"]
    created_at: datetime


class ConversationResponseDto(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessageDto] = Field(default_factory=list)
    message_next_cursor: str | None = None


class ConversationListDto(BaseModel):
    items: list[ConversationResponseDto]
    next_cursor: str | None = None
