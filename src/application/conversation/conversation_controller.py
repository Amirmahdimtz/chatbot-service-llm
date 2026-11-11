"""Thin, authenticated conversation and history endpoints."""
from __future__ import annotations

from uuid import UUID, uuid4
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from src.application.auth import api_error, authenticate_request
from src.application.conversation.dtos.conversation_dto import (
    ConversationCreateDto, ConversationListDto, ConversationMessageDto, ConversationResponseDto
)
from src.core.services.chat.chat_identity_service import ChatIdentityService
from src.core.services.conversation.conversation_service import ConversationService
from src.core.services.errors import ResourceNotFound
from src.infrastructure.di.inject import inject


@inject
class ConversationController:
    def __init__(
        self, conversation_service: ConversationService, chat_identity_service: ChatIdentityService
    ) -> None:
        self._conversations = conversation_service
        self._identity = chat_identity_service

    def api(self) -> APIRouter:
        router = APIRouter(tags=["Conversation"])

        @router.post("/", response_model=ConversationResponseDto, status_code=201)
        async def create_conversation_async(payload: ConversationCreateDto, request: Request):
            request_id = uuid4()
            principal = authenticate_request(request, self._identity, request_id)
            if isinstance(principal, JSONResponse):
                return principal
            try:
                conversation = await self._conversations.create_async(principal, payload.title)
                return ConversationResponseDto.model_validate(conversation)
            except Exception:
                return api_error("PERSISTENCE_UNAVAILABLE", "Conversation storage unavailable.", 503, request_id)

        @router.get("/", response_model=ConversationListDto)
        async def list_conversations_async(
            request: Request, limit: int = Query(default=20, ge=1, le=100),
            offset: int = Query(default=0, ge=0, le=1000000),
        ):
            request_id = uuid4()
            principal = authenticate_request(request, self._identity, request_id)
            if isinstance(principal, JSONResponse):
                return principal
            try:
                conversations, has_more = await self._conversations.list_async(principal, limit, offset)
                return ConversationListDto(
                    items=[ConversationResponseDto.model_validate(item) for item in conversations],
                    next_cursor=str(offset + limit) if has_more else None,
                )
            except Exception:
                return api_error("PERSISTENCE_UNAVAILABLE", "Conversation storage unavailable.", 503, request_id)

        @router.get("/{conversation_id}", response_model=ConversationResponseDto)
        async def get_conversation_async(
            conversation_id: UUID, request: Request,
            limit: int = Query(default=50, ge=1, le=100),
            offset: int = Query(default=0, ge=0, le=1000000),
        ):
            request_id = uuid4()
            principal = authenticate_request(request, self._identity, request_id)
            if isinstance(principal, JSONResponse):
                return principal
            try:
                conversation = await self._conversations.get_async(str(conversation_id), principal)
                messages, has_more = await self._conversations.history_async(
                    str(conversation_id), principal, limit, offset
                )
                response = ConversationResponseDto.model_validate(conversation)
                response.messages = [ConversationMessageDto.model_validate(item) for item in messages]
                response.message_next_cursor = str(offset + limit) if has_more else None
                return response
            except ResourceNotFound:
                return api_error("NOT_FOUND", "Conversation not found.", 404, request_id)
            except Exception:
                return api_error("PERSISTENCE_UNAVAILABLE", "Conversation storage unavailable.", 503, request_id)

        return router
