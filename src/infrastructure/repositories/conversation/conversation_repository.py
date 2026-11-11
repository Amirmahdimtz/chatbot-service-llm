"""Owner/audience-scoped conversation queries; no unscoped HTTP data access."""
from __future__ import annotations

from sqlalchemy import select
from src.infrastructure.context.sql_db.psql_dbcontext import PsqlDbContext
from src.infrastructure.di.inject import inject
from src.infrastructure.models.conversation import Conversation
from src.infrastructure.repositories.base.base_repository import BaseRepository


@inject
class ConversationRepository(BaseRepository[Conversation]):
    def __init__(self, db_context: PsqlDbContext):
        super().__init__(db_context, Conversation)

    async def get_scoped_async(self, conversation_id: str, owner_id: str, audience: str) -> Conversation | None:
        async with self._db_context.session() as session:
            return await session.scalar(
                select(Conversation).where(Conversation.id == conversation_id,
                                           Conversation.owner_id == owner_id,
                                           Conversation.audience == audience)
            )

    async def list_scoped_async(
        self, owner_id: str, audience: str, limit: int, offset: int
    ) -> tuple[list[Conversation], bool]:
        async with self._db_context.session() as session:
            records = list((await session.scalars(
                select(Conversation).where(
                    Conversation.owner_id == owner_id, Conversation.audience == audience
                ).order_by(Conversation.updated_at.desc(), Conversation.id.desc())
                .limit(limit + 1).offset(offset)
            )).all())
        return records[:limit], len(records) > limit
