"""Opt-in PostgreSQL integration; never run against an unapproved live database."""
from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.conversation.conversation_service import ConversationService
from src.core.services.errors import ResourceNotFound, ResourceConflict
from src.core.services.feedback.feedback_service import FeedbackService
from src.infrastructure.context.sql_db.psql_dbcontext import PsqlDbContext
from src.infrastructure.repositories.chat_message.chat_message_repository import ChatMessageRepository
from src.infrastructure.repositories.conversation.conversation_repository import ConversationRepository
from src.infrastructure.repositories.feedback.feedback_repository import FeedbackRepository


class IsolatedDatabaseConfig:
    def __init__(self, url):
        self.url = url

    def get(self, key):
        assert key == "database.url"
        return self.url


@pytest.mark.asyncio
async def test_postgres_owner_scoping_concurrent_sequence_and_feedback():
    url = os.getenv("CHATBOT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("No dedicated PostgreSQL integration-test URL")
    if os.getenv("CHATBOT_TEST_DATABASE_ISOLATED") != "1" or not url.startswith("postgresql+asyncpg://"):
        pytest.skip("PostgreSQL test requires explicitly designated isolated database")
    context = PsqlDbContext(IsolatedDatabaseConfig(url))
    try:
        conversation_service = ConversationService(ConversationRepository(context), ChatMessageRepository(context))
        feedback_service = FeedbackService(FeedbackRepository(context))
        principal = ChatIdentity("test-stage4-" + str(uuid4()), "public")
        foreign = ChatIdentity("foreign-stage4-" + str(uuid4()), "public")
        parent = await conversation_service.create_async(principal)
        exchanges = await asyncio.gather(*[
            conversation_service.start_exchange_async("synthetic", principal, parent.id)
            for _ in range(4)
        ])
        assert all(conversation_id == parent.id for conversation_id, _ in exchanges)
        history, more = await conversation_service.history_async(parent.id, principal, 100, 0)
        assert not more
        assert [message.sequence for message in history] == list(range(1, 9))
        reply_id = exchanges[0][1]
        assert await conversation_service.finalize_async(reply_id, principal, "completed", "synthetic reply")
        assert (await feedback_service.create_async(reply_id, principal, "positive", None)).message_id == reply_id
        with pytest.raises(ResourceConflict):
            await feedback_service.create_async(reply_id, principal, "incorrect", None)
        with pytest.raises(ResourceNotFound):
            await conversation_service.get_async(parent.id, foreign)
        with pytest.raises(ResourceNotFound):
            await feedback_service.create_async(reply_id, foreign, "positive", None)
    finally:
        await context.dispose_async()
