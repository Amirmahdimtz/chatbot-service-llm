"""Register metadata without claiming files have been uploaded or indexed."""
from __future__ import annotations

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.errors import PermissionDenied, ResourceNotFound
from src.infrastructure.di.inject import inject
from src.infrastructure.models.knowledge_document import KnowledgeDocument
from src.infrastructure.repositories.knowledge.knowledge_repository import KnowledgeRepository


@inject
class KnowledgeService:
    def __init__(self, knowledge_repository: KnowledgeRepository):
        self._documents = knowledge_repository

    async def register_async(
        self, identity: ChatIdentity, title: str, source_type: str,
        category: str | None, language: str, classification: str | None,
        audience: str
    ) -> KnowledgeDocument:
        if "knowledge:write" not in identity.permissions:
            raise PermissionDenied("Knowledge registration not permitted")
        if audience != identity.audience:
            raise PermissionDenied("Knowledge audience not permitted")
        return await self._documents.insert_async(KnowledgeDocument(
            owner_id=identity.subject, audience=audience, title=title,
            source_type=source_type, category=category, language=language,
            classification=classification, status="registered", version=1,
        ))

    async def get_async(
        self, document_id: str, identity: ChatIdentity, audience: str
    ) -> KnowledgeDocument:
        if audience != identity.audience:
            raise ResourceNotFound("Document not found")
        document = await self._documents.get_scoped_async(document_id, identity.subject, audience)
        if document is None:
            raise ResourceNotFound("Document not found")
        return document

    async def list_async(
        self, identity: ChatIdentity, limit: int, offset: int
    ) -> tuple[list[KnowledgeDocument], bool]:
        return await self._documents.list_scoped_async(
            identity.subject, identity.audience, limit, offset
        )
