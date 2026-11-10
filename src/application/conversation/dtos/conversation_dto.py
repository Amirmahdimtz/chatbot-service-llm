"""Stage 4 persistence contracts only; no fictitious conversation routes in stage 3."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreateDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str | None = Field(default=None, max_length=200)


class ConversationMessageDto(BaseModel):
    id: UUID
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    status: Literal["completed", "failed", "cancelled"]
    created_at: datetime


class ConversationResponseDto(BaseModel):
    id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessageDto] = Field(default_factory=list)


class ConversationListDto(BaseModel):
    items: list[ConversationResponseDto]
    next_cursor: str | None = None
