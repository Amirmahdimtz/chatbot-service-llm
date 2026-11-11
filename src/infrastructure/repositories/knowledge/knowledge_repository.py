"""Document metadata queries always enforce owner and trusted audience."""
from __future__ import annotations

from sqlalchemy import select
from src.infrastructure.context.sql_db.psql_dbcontext import PsqlDbContext
from src.infrastructure.di.inject import inject
from src.infrastructure.models.knowledge_document import KnowledgeDocument
from src.infrastructure.repositories.base.base_repository import BaseRepository


@inject
class KnowledgeRepository(BaseRepository[KnowledgeDocument]):
    def __init__(self, db_context: PsqlDbContext):
        super().__init__(db_context, KnowledgeDocument)

    async def get_scoped_async(self, document_id: str, owner_id: str, audience: str) -> KnowledgeDocument | None:
        async with self._db_context.session() as session:
            return await session.scalar(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.id == document_id,
                    KnowledgeDocument.owner_id == owner_id,
                    KnowledgeDocument.audience == audience
                )
            )

    async def list_scoped_async(
        self, owner_id: str, audience: str, limit: int, offset: int
    ) -> tuple[list[KnowledgeDocument], bool]:
        async with self._db_context.session() as session:
            records = list((await session.scalars(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.owner_id == owner_id, KnowledgeDocument.audience == audience
                ).order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id.desc())
                .limit(limit + 1).offset(offset)
            )).all())
        return records[:limit], len(records) > limit
