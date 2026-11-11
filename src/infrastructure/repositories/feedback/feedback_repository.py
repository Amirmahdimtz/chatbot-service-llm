"""Validated feedback creation tied to a completed, owned assistant reply."""
from __future__ import annotations

from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.core.services.errors import ResourceConflict, ResourceNotFound
from src.infrastructure.context.sql_db.psql_dbcontext import PsqlDbContext
from src.infrastructure.di.inject import inject
from src.infrastructure.models.chat_message import ChatMessage
from src.infrastructure.models.conversation import Conversation
from src.infrastructure.models.feedback import Feedback
from src.infrastructure.repositories.base.base_repository import BaseRepository


@inject
class FeedbackRepository(BaseRepository[Feedback]):
    def __init__(self, db_context: PsqlDbContext):
        super().__init__(db_context, Feedback)

    async def create_scoped_async(
        self, message_id: str, actor_id: str, audience: str, kind: str, comment: str | None
    ) -> Feedback:
        async with self._db_context.session() as session:
            try:
                message = await session.scalar(
                    select(ChatMessage).join(Conversation, ChatMessage.conversation_id == Conversation.id)
                    .where(ChatMessage.id == message_id,
                           ChatMessage.role == "assistant", ChatMessage.status == "completed",
                           Conversation.owner_id == actor_id, Conversation.audience == audience)
                )
                if message is None:
                    raise ResourceNotFound("Completed assistant message not found")
                feedback = Feedback(id=str(uuid4()), message_id=message_id,
                                    actor_id=actor_id, kind=kind, comment=comment)
                session.add(feedback)
                await session.commit()
                await session.refresh(feedback)
                return feedback
            except IntegrityError as exc:
                await session.rollback()
                raise ResourceConflict("Feedback already exists") from exc
            except Exception:
                await session.rollback()
                raise
