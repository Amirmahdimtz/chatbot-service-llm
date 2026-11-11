"""Atomic exchange allocation and durable streaming outcome updates."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from src.core.services.errors import ResourceNotFound
from src.infrastructure.context.sql_db.psql_dbcontext import PsqlDbContext
from src.infrastructure.di.inject import inject
from src.infrastructure.models.chat_message import ChatMessage
from src.infrastructure.models.conversation import Conversation
from src.infrastructure.repositories.base.base_repository import BaseRepository


@inject
class ChatMessageRepository(BaseRepository[ChatMessage]):
    def __init__(self, db_context: PsqlDbContext):
        super().__init__(db_context, ChatMessage)

    async def append_exchange_async(
        self, conversation_id: str, owner_id: str, audience: str, message: str
    ) -> ChatMessage:
        """Lock the parent to allocate two unique ordered messages in one transaction."""
        async with self._db_context.session() as session:
            try:
                parent = await session.scalar(
                    select(Conversation).where(
                        Conversation.id == conversation_id,
                        Conversation.owner_id == owner_id,
                        Conversation.audience == audience
                    ).with_for_update()
                )
                if parent is None:
                    raise ResourceNotFound("Conversation not found")
                seq = parent.next_sequence
                user = ChatMessage(id=str(uuid4()), conversation_id=conversation_id,
                                   sequence=seq, role="user", content=message, status="completed")
                assistant = ChatMessage(id=str(uuid4()), conversation_id=conversation_id,
                                        sequence=seq + 1, role="assistant", content="", status="streaming")
                parent.next_sequence = seq + 2
                parent.updated_at = datetime.now(timezone.utc)
                session.add_all([user, assistant])
                await session.commit()
                return assistant
            except Exception:
                await session.rollback()
                raise

    async def finalize_async(
        self, message_id: str, owner_id: str, audience: str, status: str, content: str
    ) -> bool:
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError("Invalid terminal status")
        async with self._db_context.session() as session:
            try:
                message = await session.scalar(
                    select(ChatMessage).join(Conversation, ChatMessage.conversation_id == Conversation.id)
                    .where(ChatMessage.id == message_id, ChatMessage.role == "assistant",
                           Conversation.owner_id == owner_id, Conversation.audience == audience)
                    .with_for_update()
                )
                if message is None or message.status != "streaming":
                    return False
                now = datetime.now(timezone.utc)
                message.content = content
                message.status = status
                message.updated_at = now
                parent = await session.get(Conversation, message.conversation_id)
                parent.updated_at = now
                await session.commit()
                return True
            except Exception:
                await session.rollback()
                raise

    async def get_prior_context_async(
        self, message_id: str, owner_id: str, audience: str, limit: int = 10
    ) -> list[dict[str, str]]:
        async with self._db_context.session() as session:
            current = await session.scalar(
                select(ChatMessage).join(Conversation, ChatMessage.conversation_id == Conversation.id)
                .where(ChatMessage.id == message_id, ChatMessage.role == "assistant",
                       Conversation.owner_id == owner_id, Conversation.audience == audience)
            )
            if current is None:
                raise ResourceNotFound("Message not found")
            # The current user input sits immediately before the reserved assistant slot.
            previous = list((await session.scalars(
                select(ChatMessage).where(
                    ChatMessage.conversation_id == current.conversation_id,
                    ChatMessage.sequence < current.sequence - 1,
                    ChatMessage.status == "completed",
                    ChatMessage.role.in_(("user", "assistant"))
                ).order_by(ChatMessage.sequence.desc()).limit(limit)
            )).all())
            return [{"role": item.role, "content": item.content} for item in reversed(previous)]

    async def list_scoped_async(
        self, conversation_id: str, owner_id: str, audience: str, limit: int, offset: int
    ) -> tuple[list[ChatMessage], bool]:
        async with self._db_context.session() as session:
            parent = await session.scalar(
                select(Conversation.id).where(Conversation.id == conversation_id,
                    Conversation.owner_id == owner_id, Conversation.audience == audience)
            )
            if parent is None:
                raise ResourceNotFound("Conversation not found")
            records = list((await session.scalars(
                select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.sequence.asc()).limit(limit + 1).offset(offset)
            )).all())
            return records[:limit], len(records) > limit
