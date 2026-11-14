"""Conversation lifecycle and scoped, paginated history."""
from __future__ import annotations

from src.core.services.chat.chat_identity_service import ChatIdentity, scoped_conversation_owner
from src.core.services.errors import ResourceNotFound
from src.infrastructure.di.inject import inject
from src.infrastructure.models.chat_message import ChatMessage
from src.infrastructure.models.conversation import Conversation
from src.infrastructure.repositories.chat_message.chat_message_repository import ChatMessageRepository
from src.infrastructure.repositories.conversation.conversation_repository import ConversationRepository


@inject
class ConversationService:
    def __init__(
        self, conversation_repository: ConversationRepository,
        chat_message_repository: ChatMessageRepository
    ) -> None:
        self._conversations = conversation_repository
        self._messages = chat_message_repository

    async def create_async(self, identity: ChatIdentity, title: str | None = None) -> Conversation:
        return await self._conversations.insert_async(
            Conversation(owner_id=scoped_conversation_owner(identity), audience=identity.audience, title=title)
        )

    async def get_async(self, conversation_id: str, identity: ChatIdentity) -> Conversation:
        conversation = await self._conversations.get_scoped_async(
            conversation_id, scoped_conversation_owner(identity), identity.audience
        )
        if conversation is None:
            raise ResourceNotFound("Conversation not found")
        return conversation

    async def list_async(
        self, identity: ChatIdentity, limit: int, offset: int
    ) -> tuple[list[Conversation], bool]:
        return await self._conversations.list_scoped_async(scoped_conversation_owner(identity), identity.audience, limit, offset)

    async def history_async(
        self, conversation_id: str, identity: ChatIdentity, limit: int, offset: int
    ) -> tuple[list[ChatMessage], bool]:
        return await self._messages.list_scoped_async(
            conversation_id, scoped_conversation_owner(identity), identity.audience, limit, offset
        )

    async def start_exchange_async(
        self, message: str, identity: ChatIdentity, conversation_id: str | None
    ) -> tuple[str, str]:
        if conversation_id is None:
            conversation = await self.create_async(identity)
            conversation_id = conversation.id
        reserved = await self._messages.append_exchange_async(
            conversation_id, scoped_conversation_owner(identity), identity.audience, message
        )
        return conversation_id, reserved.id

    async def prior_context_async(self, message_id: str, identity: ChatIdentity) -> list[dict[str, str]]:
        return await self._messages.get_prior_context_async(
            message_id, scoped_conversation_owner(identity), identity.audience
        )

    async def finalize_async(
        self, message_id: str, identity: ChatIdentity, status: str, content: str
    ) -> bool:
        return await self._messages.finalize_async(
            message_id, scoped_conversation_owner(identity), identity.audience, status, content
        )
