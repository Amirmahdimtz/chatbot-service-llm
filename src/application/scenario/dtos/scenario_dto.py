"""Controlled scenario-data management and employee progression DTOs."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from src.core.services.scenarios.scenario_contracts import DevelopmentProgressRecord


class ScenarioRecordWriteDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    audience: Literal["public", "internal"] = "internal"
    payload: dict


class ScenarioRecordResponseDto(BaseModel):
    kind: str
    external_key: str
    audience: str
    version: int
    verified: bool
    payload: dict


class PendingStatusDto(BaseModel):
    pending_id: str
    status: Literal["insufficient_evidence", "reviewed"]


class DevelopmentProgressWriteDto(DevelopmentProgressRecord):
    pass
