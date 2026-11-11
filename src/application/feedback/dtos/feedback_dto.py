"""Feedback may target only a completed assistant reply owned by the caller."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class FeedbackCreateDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message_id: UUID
    kind: Literal["positive", "negative", "incorrect"]
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("comment")
    @classmethod
    def trim_comment(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class FeedbackResponseDto(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    message_id: UUID
    kind: Literal["positive", "negative", "incorrect"]
    comment: str | None
    created_at: datetime
