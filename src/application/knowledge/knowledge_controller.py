"""Metadata registration and scoped retrieval; document ingestion belongs to stage 5."""
from __future__ import annotations

from uuid import UUID, uuid4
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from src.application.auth import api_error, authenticate_request
from src.application.knowledge.dtos.knowledge_dto import (
    KnowledgeListDto, KnowledgeRegisterDto, KnowledgeResponseDto
)
from src.core.services.chat.chat_identity_service import ChatIdentityService
from src.core.services.errors import PermissionDenied, ResourceNotFound
from src.core.services.knowledge.knowledge_service import KnowledgeService
from src.infrastructure.di.inject import inject


@inject
class KnowledgeController:
    def __init__(self, knowledge_service: KnowledgeService, chat_identity_service: ChatIdentityService):
        self._knowledge = knowledge_service
        self._identity = chat_identity_service

    def api(self) -> APIRouter:
        router = APIRouter(tags=["Knowledge"])

        @router.post("/", response_model=KnowledgeResponseDto, status_code=201,
                     summary="Register document metadata only (no upload or indexing)")
        async def register_document_async(payload: KnowledgeRegisterDto, request: Request):
            request_id = uuid4()
            principal = authenticate_request(request, self._identity, request_id)
            if isinstance(principal, JSONResponse):
                return principal
            try:
                document = await self._knowledge.register_async(
                    principal, payload.title, payload.source_type, payload.category,
                    payload.language, payload.classification, payload.audience
                )
                return KnowledgeResponseDto.model_validate(document)
            except PermissionDenied:
                return api_error("FORBIDDEN", "Knowledge registration not permitted.", 403, request_id)
            except Exception:
                return api_error("PERSISTENCE_UNAVAILABLE", "Knowledge storage unavailable.", 503, request_id)

        @router.get("/", response_model=KnowledgeListDto)
        async def list_documents_async(
            request: Request, limit: int = Query(default=20, ge=1, le=100),
            offset: int = Query(default=0, ge=0, le=1000000),
        ):
            request_id = uuid4()
            principal = authenticate_request(request, self._identity, request_id)
            if isinstance(principal, JSONResponse):
                return principal
            try:
                documents, has_more = await self._knowledge.list_async(principal, limit, offset)
                return KnowledgeListDto(
                    items=[KnowledgeResponseDto.model_validate(item) for item in documents],
                    next_cursor=str(offset + limit) if has_more else None
                )
            except Exception:
                return api_error("PERSISTENCE_UNAVAILABLE", "Knowledge storage unavailable.", 503, request_id)

        @router.get("/{document_id}", response_model=KnowledgeResponseDto)
        async def get_document_async(document_id: UUID, request: Request):
            request_id = uuid4()
            principal = authenticate_request(request, self._identity, request_id)
            if isinstance(principal, JSONResponse):
                return principal
            try:
                # The trusted identity determines the only accessible audience.
                document = await self._knowledge.get_async(str(document_id), principal, principal.audience)
                return KnowledgeResponseDto.model_validate(document)
            except ResourceNotFound:
                return api_error("NOT_FOUND", "Document not found.", 404, request_id)
            except Exception:
                return api_error("PERSISTENCE_UNAVAILABLE", "Knowledge storage unavailable.", 503, request_id)

        return router
