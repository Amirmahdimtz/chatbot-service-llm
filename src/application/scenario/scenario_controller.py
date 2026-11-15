"""Thin routes for managed scenario data and scoped pending/progress status."""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from src.application.auth import api_error, authenticate_request
from src.application.scenario.dtos.scenario_dto import (
    DevelopmentProgressWriteDto, PendingStatusDto, ScenarioRecordResponseDto,
    ScenarioRecordWriteDto,
)
from src.core.services.chat.chat_identity_service import ChatIdentityService
from src.core.services.errors import PermissionDenied, ResourceNotFound
from src.core.services.scenarios.scenario_service import ScenarioService
from src.infrastructure.di.inject import inject


@inject
class ScenarioController:
    def __init__(self, scenario_service: ScenarioService,
                 chat_identity_service: ChatIdentityService):
        self._scenarios = scenario_service
        self._identity = chat_identity_service

    def api(self) -> APIRouter:
        router = APIRouter(tags=["Scenario"])

        @router.put("/records/{kind}/{key}", response_model=ScenarioRecordResponseDto)
        async def upsert_record_async(kind: str, key: str, payload: ScenarioRecordWriteDto,
                                      request: Request):
            request_id = uuid4()
            identity = authenticate_request(request, self._identity, request_id)
            if isinstance(identity, JSONResponse):
                return identity
            try:
                record = await self._scenarios.upsert_record_async(
                    identity, kind, key, payload.payload, payload.audience)
                return ScenarioRecordResponseDto(
                    kind=record.kind, external_key=record.external_key, audience=record.audience,
                    version=record.version, verified=record.verified, payload=record.payload)
            except PermissionDenied:
                return api_error("FORBIDDEN", "Scenario data write denied.", 403, request_id)
            except (ValueError, ValidationError):
                return api_error("INVALID_RECORD", "Invalid scenario record.", 422, request_id)
            except Exception:
                return api_error("PERSISTENCE_UNAVAILABLE", "Scenario storage unavailable.", 503, request_id)

        @router.get("/records/{kind}/{key}", response_model=ScenarioRecordResponseDto)
        async def get_record_async(kind: str, key: str, request: Request,
                                   audience: str = "internal"):
            request_id = uuid4()
            identity = authenticate_request(request, self._identity, request_id)
            if isinstance(identity, JSONResponse):
                return identity
            try:
                record = await self._scenarios.get_record_async(identity, kind, key, audience)
                return ScenarioRecordResponseDto(
                    kind=record.kind, external_key=record.external_key, audience=record.audience,
                    version=record.version, verified=record.verified, payload=record.payload)
            except PermissionDenied:
                return api_error("FORBIDDEN", "Scenario data read denied.", 403, request_id)
            except (ResourceNotFound, ValueError):
                return api_error("NOT_FOUND", "Record not found.", 404, request_id)
            except Exception:
                return api_error("PERSISTENCE_UNAVAILABLE", "Scenario storage unavailable.", 503, request_id)

        @router.post("/progress", response_model=ScenarioRecordResponseDto)
        async def update_progress_async(payload: DevelopmentProgressWriteDto, request: Request):
            request_id = uuid4()
            identity = authenticate_request(request, self._identity, request_id)
            if isinstance(identity, JSONResponse):
                return identity
            try:
                record = await self._scenarios.upsert_record_async(
                    identity, "development_progress",
                    self._scenarios.progress_key(payload.employee_id, payload.position_id),
                    payload.model_dump(mode="json"))
                return ScenarioRecordResponseDto(
                    kind=record.kind, external_key=record.external_key, audience=record.audience,
                    version=record.version, verified=record.verified, payload=record.payload)
            except PermissionDenied:
                return api_error("FORBIDDEN", "Progress update denied.", 403, request_id)
            except (ValidationError, ValueError):
                return api_error("INVALID_RECORD", "Invalid progress record.", 422, request_id)
            except Exception:
                return api_error("PERSISTENCE_UNAVAILABLE", "Progress storage unavailable.", 503, request_id)

        @router.get("/pending/{pending_id}", response_model=PendingStatusDto)
        async def pending_status_async(pending_id: str, request: Request):
            request_id = uuid4()
            identity = authenticate_request(request, self._identity, request_id)
            if isinstance(identity, JSONResponse):
                return identity
            try:
                status = await self._scenarios.get_pending_async(identity, pending_id)
                return PendingStatusDto(pending_id=pending_id, status=status)
            except (PermissionDenied, ResourceNotFound):
                return api_error("NOT_FOUND", "Pending record not found.", 404, request_id)
            except Exception:
                return api_error("PERSISTENCE_UNAVAILABLE", "Scenario storage unavailable.", 503, request_id)

        return router
