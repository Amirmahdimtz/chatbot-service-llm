"""Metadata registration, not upload: registered documents have no indexed content."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


SourceType = Literal["pdf", "txt", "doc", "docx", "json", "csv", "xlsx"]
Audience = Literal["public", "internal"]


class KnowledgeRegisterDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=200)
    source_type: SourceType
    category: str | None = Field(default=None, max_length=100)
    classification: str | None = Field(default=None, max_length=100)
    language: str = Field(default="fa", min_length=2, max_length=16)
    audience: Audience

    @field_validator("title", "language")
    @classmethod
    def trim_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value must not be blank")
        return value

    @field_validator("category", "classification")
    @classmethod
    def trim_optional(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class KnowledgeResponseDto(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    source_type: SourceType
    category: str | None
    classification: str | None
    language: str
    audience: Audience
    version: int
    status: Literal["registered", "processing", "failed", "approved"]
    created_at: datetime
    updated_at: datetime


class KnowledgeListDto(BaseModel):
    items: list[KnowledgeResponseDto]
    next_cursor: str | None = None
