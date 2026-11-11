"""Authenticated feedback registration without leaking foreign message existence."""
from __future__ import annotations

from uuid import uuid4
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.application.auth import api_error, authenticate_request
from src.application.feedback.dtos.feedback_dto import FeedbackCreateDto, FeedbackResponseDto
from src.core.services.chat.chat_identity_service import ChatIdentityService
from src.core.services.errors import ResourceConflict, ResourceNotFound
from src.core.services.feedback.feedback_service import FeedbackService
from src.infrastructure.di.inject import inject


@inject
class FeedbackController:
    def __init__(self, feedback_service: FeedbackService, chat_identity_service: ChatIdentityService):
        self._feedback = feedback_service
        self._identity = chat_identity_service

    def api(self) -> APIRouter:
        router = APIRouter(tags=["Feedback"])

        @router.post("/", response_model=FeedbackResponseDto, status_code=201)
        async def create_feedback_async(payload: FeedbackCreateDto, request: Request):
            request_id = uuid4()
            principal = authenticate_request(request, self._identity, request_id)
            if isinstance(principal, JSONResponse):
                return principal
            try:
                feedback = await self._feedback.create_async(
                    str(payload.message_id), principal, payload.kind, payload.comment
                )
                return FeedbackResponseDto.model_validate(feedback)
            except ResourceNotFound:
                return api_error("NOT_FOUND", "Completed assistant message not found.", 404, request_id)
            except ResourceConflict:
                return api_error("ALREADY_EXISTS", "Feedback already exists.", 409, request_id)
            except Exception:
                return api_error("PERSISTENCE_UNAVAILABLE", "Feedback storage unavailable.", 503, request_id)

        return router
