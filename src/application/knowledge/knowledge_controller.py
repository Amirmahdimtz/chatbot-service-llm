"""Scoped Knowledge API: registration, safe upload, retry, publication and hybrid search."""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from src.application.auth import api_error, authenticate_request
from src.application.knowledge.dtos.knowledge_dto import (
    KnowledgeHitDto, KnowledgeListDto, KnowledgeRegisterDto,
    KnowledgeResponseDto, KnowledgeSearchDto, KnowledgeSearchResultDto,
)
from src.core.services.chat.chat_identity_service import ChatIdentityService
from src.core.services.errors import PermissionDenied, ResourceConflict, ResourceNotFound
from src.core.services.knowledge.knowledge_service import KnowledgeService
from src.core.services.knowledge.knowledge_index_service import KnowledgeIndexService
from src.infrastructure.di.inject import inject
from src.infrastructure.providers.document.document_processor import DocumentProcessingError, DocumentProcessor
from src.infrastructure.providers.embedding.embedding_provider import EmbeddingError
from src.infrastructure.providers.reranking.reranking_provider import RerankingError
from src.infrastructure.providers.storage.storage_provider import StorageError
from src.infrastructure.providers.vector_db.qdrant_provider import VectorIndexError


@inject
class KnowledgeController:
    def __init__(
        self, knowledge_service: KnowledgeService, chat_identity_service: ChatIdentityService,
        knowledge_index_service: KnowledgeIndexService, document_processor: DocumentProcessor,
    ):
        self._knowledge = knowledge_service
        self._identity = chat_identity_service
        self._index = knowledge_index_service
        self._processor = document_processor

    def api(self) -> APIRouter:
        router = APIRouter(tags=["Knowledge"])

        def error_response(exc: Exception, request_id: UUID) -> JSONResponse:
            if isinstance(exc, ResourceNotFound):
                return api_error("NOT_FOUND", "Document not found.", 404, request_id)
            if isinstance(exc, PermissionDenied):
                return api_error("FORBIDDEN", "Knowledge access forbidden.", 403, request_id)
            if isinstance(exc, ResourceConflict):
                return api_error("CONFLICT", "Document is busy, duplicate or in a conflicting state.", 409, request_id)
            if isinstance(exc, DocumentProcessingError):
                code = str(exc)
                status = 413 if code in ("DOCUMENT_TOO_LARGE", "ZIP_LIMIT_EXCEEDED") else 422
                return api_error(code, "Document validation or extraction failed.", status, request_id)
            if isinstance(exc, (EmbeddingError, RerankingError, VectorIndexError, StorageError)):
                return api_error("DEPENDENCY_UNAVAILABLE", "Knowledge processing dependency unavailable.", 503, request_id)
            return api_error("PERSISTENCE_UNAVAILABLE", "Knowledge storage unavailable.", 503, request_id)

        @router.post("/", response_model=KnowledgeResponseDto, status_code=201,
                     summary="Register document metadata (no content indexed yet)")
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
            except Exception as exc:
                return error_response(exc, request_id)

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
            except Exception as exc:
                return error_response(exc, request_id)

        async def read_upload_async(file: UploadFile) -> bytes:
            parts = []
            length = 0
            while True:
                block = await file.read(1024 * 1024)
                if not block:
                    break
                length += len(block)
                if length > self._processor.max_upload_bytes:
                    raise DocumentProcessingError("DOCUMENT_TOO_LARGE")
                parts.append(block)
            return b"".join(parts)

        @router.post("/search", response_model=KnowledgeSearchResultDto)
        async def search_documents_async(payload: KnowledgeSearchDto, request: Request):
            request_id = uuid4()
            principal = authenticate_request(request, self._identity, request_id)
            if isinstance(principal, JSONResponse):
                return principal
            try:
                results = await self._index.retrieve_async(principal, payload.query)
                return KnowledgeSearchResultDto(items=[KnowledgeHitDto.model_validate(x) for x in results])
            except Exception as exc:
                return error_response(exc, request_id)

        @router.post("/{document_id}/upload", response_model=KnowledgeResponseDto)
        async def upload_document_async(document_id: UUID, request: Request, file: UploadFile = File(...)):
            request_id = uuid4()
            principal = authenticate_request(request, self._identity, request_id)
            if isinstance(principal, JSONResponse):
                return principal
            try:
                content = await read_upload_async(file)
                doc = await self._index.ingest_async(principal, str(document_id), file.filename, content)
                return KnowledgeResponseDto.model_validate(doc)
            except Exception as exc:
                return error_response(exc, request_id)
            finally:
                await file.close()

        @router.post("/{document_id}/replace", response_model=KnowledgeResponseDto)
        async def replace_document_async(document_id: UUID, request: Request, file: UploadFile = File(...)):
            request_id = uuid4()
            principal = authenticate_request(request, self._identity, request_id)
            if isinstance(principal, JSONResponse):
                return principal
            try:
                content = await read_upload_async(file)
                doc = await self._index.ingest_async(principal, str(document_id), file.filename, content, replace=True)
                return KnowledgeResponseDto.model_validate(doc)
            except Exception as exc:
                return error_response(exc, request_id)
            finally:
                await file.close()

        @router.post("/{document_id}/retry", response_model=KnowledgeResponseDto)
        async def retry_document_async(document_id: UUID, request: Request):
            request_id = uuid4()
            principal = authenticate_request(request, self._identity, request_id)
            if isinstance(principal, JSONResponse):
                return principal
            try:
                doc = await self._index.ingest_async(principal, str(document_id), None, None, retry=True)
                return KnowledgeResponseDto.model_validate(doc)
            except Exception as exc:
                return error_response(exc, request_id)

        @router.post("/{document_id}/publish", response_model=KnowledgeResponseDto)
        async def publish_document_async(document_id: UUID, request: Request):
            request_id = uuid4()
            principal = authenticate_request(request, self._identity, request_id)
            if isinstance(principal, JSONResponse):
                return principal
            try:
                doc = await self._index.publish_async(principal, str(document_id))
                return KnowledgeResponseDto.model_validate(doc)
            except Exception as exc:
                return error_response(exc, request_id)

        @router.get("/{document_id}", response_model=KnowledgeResponseDto)
        async def get_document_async(document_id: UUID, request: Request):
            request_id = uuid4()
            principal = authenticate_request(request, self._identity, request_id)
            if isinstance(principal, JSONResponse):
                return principal
            try:
                doc = await self._knowledge.get_async(str(document_id), principal, principal.audience)
                return KnowledgeResponseDto.model_validate(doc)
            except Exception as exc:
                return error_response(exc, request_id)

        return router
