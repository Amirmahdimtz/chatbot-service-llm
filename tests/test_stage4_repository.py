"""Async persistence, ownership isolation, ordering, constraints and rollback."""
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.conversation.conversation_service import ConversationService
from src.core.services.errors import ResourceConflict, ResourceNotFound
from src.core.services.feedback.feedback_service import FeedbackService
from src.core.services.knowledge.knowledge_service import KnowledgeService
from src.infrastructure.alembic.model_discovery import load_models
from src.infrastructure.context.sql_db.psql_dbcontext import Base, PsqlDbContext
from src.infrastructure.models.chat_message import ChatMessage
from src.infrastructure.repositories.chat_message.chat_message_repository import ChatMessageRepository
from src.infrastructure.repositories.conversation.conversation_repository import ConversationRepository
from src.infrastructure.repositories.feedback.feedback_repository import FeedbackRepository
from src.infrastructure.repositories.knowledge.knowledge_repository import KnowledgeRepository


class Config:
    def __init__(self, url):
        self.url = url

    def get(self, key):
        assert key == "database.url"
        return self.url


@pytest.fixture
async def persistence(tmp_path):
    context = PsqlDbContext(Config(f"sqlite+aiosqlite:///{(tmp_path / 'stage4.sqlite').as_posix()}"))
    load_models()
    @event.listens_for(context.engine.sync_engine, "connect")
    def enable_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
    async with context.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    conversation = ConversationService(ConversationRepository(context), ChatMessageRepository(context))
    feedback = FeedbackService(FeedbackRepository(context))
    knowledge = KnowledgeService(KnowledgeRepository(context))
    try:
        yield context, conversation, feedback, knowledge
    finally:
        await context.dispose_async()


@pytest.mark.asyncio
async def test_create_continue_paginate_and_isolate(persistence):
    ctx, service, _, _ = persistence
    alice = ChatIdentity("alice", "public")
    bob = ChatIdentity("bob", "public")
    internal = ChatIdentity("alice", "internal")
    item = await service.create_async(alice, "Synthetic")
    id_, first_reply = await service.start_exchange_async("اول", alice, item.id)
    assert id_ == item.id
    assert await service.finalize_async(first_reply, alice, "completed", "پاسخ اول")
    _, second_reply = await service.start_exchange_async("دوم", alice, item.id)
    context = await service.prior_context_async(second_reply, alice)
    assert context == [{"role": "user", "content": "اول"}, {"role": "assistant", "content": "پاسخ اول"}]
    assert await service.finalize_async(second_reply, alice, "failed", "ناتمام")
    messages, more = await service.history_async(item.id, alice, 2, 0)
    assert more and [(x.sequence, x.role) for x in messages] == [(1, "user"), (2, "assistant")]
    messages2, more2 = await service.history_async(item.id, alice, 2, 2)
    assert not more2 and [x.status for x in messages2] == ["completed", "failed"]
    assert (await service.list_async(alice, 10, 0))[0][0].id == item.id
    for other in (bob, internal):
        with pytest.raises(ResourceNotFound):
            await service.get_async(item.id, other)
        with pytest.raises(ResourceNotFound):
            await service.start_exchange_async("forbidden", other, item.id)
        with pytest.raises(ResourceNotFound):
            await service.history_async(item.id, other, 10, 0)
    assert await service.finalize_async(first_reply, alice, "failed", "overwrite") is False
    async with ctx.session() as session:
        saved = await session.get(ChatMessage, first_reply)
        assert saved.content == "پاسخ اول" and saved.status == "completed"


@pytest.mark.asyncio
async def test_feedback_is_owned_completed_and_unique(persistence):
    _, conversations, feedback, _ = persistence
    alice = ChatIdentity("alice", "public")
    bob = ChatIdentity("bob", "public")
    conversation_id, message_id = await conversations.start_exchange_async("synthetic", alice, None)
    with pytest.raises(ResourceNotFound):
        await feedback.create_async(message_id, alice, "incorrect", "early")
    assert await conversations.finalize_async(message_id, alice, "completed", "reply")
    with pytest.raises(ResourceNotFound):
        await feedback.create_async(message_id, bob, "incorrect", None)
    with pytest.raises(ResourceNotFound):
        await feedback.create_async(str(uuid4()), alice, "positive", None)
    item = await feedback.create_async(message_id, alice, "incorrect", "wrong answer")
    assert item.kind == "incorrect"
    with pytest.raises(ResourceConflict):
        await feedback.create_async(message_id, alice, "negative", None)


@pytest.mark.asyncio
async def test_knowledge_registration_only_and_audience_isolation(persistence):
    _, _, _, knowledge = persistence
    alice = ChatIdentity("alice", "public", frozenset({"knowledge:write"}))
    bob = ChatIdentity("bob", "public", frozenset({"knowledge:write"}))
    internal = ChatIdentity("alice", "internal", frozenset({"knowledge:write"}))
    document = await knowledge.register_async(alice, "Sample", "pdf", "religious_qa", "fa", None, "public")
    assert document.status == "registered" and document.storage_key is None
    assert (await knowledge.get_async(document.id, alice, "public")).id == document.id
    for other in (bob, internal):
        with pytest.raises(ResourceNotFound):
            await knowledge.get_async(document.id, other, other.audience)
    from src.core.services.errors import PermissionDenied
    with pytest.raises(PermissionDenied):
        await knowledge.register_async(alice, "Injected", "pdf", None, "fa", None, "internal")
    with pytest.raises(PermissionDenied):
        await knowledge.register_async(ChatIdentity("no-priv", "public"), "Unauthorized", "pdf", None, "fa", None, "public")
    docs, more = await knowledge.list_async(alice, 1, 0)
    assert [d.id for d in docs] == [document.id] and not more


@pytest.mark.asyncio
async def test_message_fk_unique_sequence_and_transaction_rollback(persistence):
    ctx, service, _, _ = persistence
    identity = ChatIdentity("owner", "public")
    conversation = await service.create_async(identity)
    async with ctx.session() as session:
        session.add(ChatMessage(id=str(uuid4()), conversation_id=str(uuid4()),
                                sequence=1, role="user", content="orphan", status="completed"))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
    _, assistant_id = await service.start_exchange_async("valid", identity, conversation.id)
    messages, _ = await service.history_async(conversation.id, identity, 10, 0)
    async with ctx.session() as session:
        session.add(ChatMessage(id=str(uuid4()), conversation_id=conversation.id,
                                sequence=1, role="user", content="duplicate", status="completed"))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
    assert len((await service.history_async(conversation.id, identity, 10, 0))[0]) == 2
