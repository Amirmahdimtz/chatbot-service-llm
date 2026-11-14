"""Stage 6 cross-layer integration: SQL ownership, real Stage 5 retrieval, Chat/SSE.

The embedding, vector and local LLM transports are controlled fakes; SQLAlchemy,
storage, ingestion, retrieval policy, RRF and chat persistence execute for real.
"""
from __future__ import annotations

from collections import defaultdict
from uuid import UUID, uuid4

import pytest

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.chat.chat_service import ChatService
from src.core.services.conversation.conversation_service import ConversationService
from src.core.services.knowledge.knowledge_index_service import KnowledgeIndexService
from src.core.services.knowledge.knowledge_service import KnowledgeService
from src.core.services.rag.rag_service import RagService
from src.core.services.scenario_router.scenario_router_service import ScenarioRouterService
from src.infrastructure.alembic.model_discovery import load_models
from src.infrastructure.context.sql_db.psql_dbcontext import Base, PsqlDbContext
from src.infrastructure.providers.document.document_processor import DocumentProcessor
from src.infrastructure.providers.storage.storage_provider import StorageProvider
from src.infrastructure.repositories.chat_message.chat_message_repository import ChatMessageRepository
from src.infrastructure.repositories.conversation.conversation_repository import ConversationRepository
from src.infrastructure.repositories.knowledge.knowledge_repository import KnowledgeRepository


class Config:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class Embedded:
    dimension = 3
    model_version = "stage6-synthetic"

    async def embed_async(self, texts):
        return [[0.1, 0.3, 0.6] for _ in texts]


class Reranker:
    async def rerank_async(self, query, texts):
        return [(i, 1.0 / (i + 1)) for i in range(len(texts))]


class LeakyQdrant:
    """Deliberately ignores Qdrant filters so SQL authorization must reject leaks."""

    def __init__(self):
        self.points = defaultdict(dict)
        self.scopes = []

    async def ensure_collection_async(self, audience, dimension, model_version):
        assert dimension == 3 and model_version == "stage6-synthetic"

    async def upsert_async(self, audience, points):
        for point in points:
            self.points[audience][point["id"]] = point

    async def query_async(self, audience, vector, using, filters, limit):
        self.scopes.append(audience)
        return [
            {"id": point["id"], "payload": point["payload"], "score": 1.0}
            for group in self.points.values()
            for point in group.values()
        ][:limit]


class LocalLlm:
    def __init__(self):
        self.calls = []

    async def stream_chat_async(self, message, history=None, system_prompt=None, evidence=None):
        self.calls.append((message, system_prompt, evidence))
        yield "پاسخ آزمایشی مستند"


@pytest.fixture
async def stack(tmp_path):
    config = Config({
        "database.url": f"sqlite+aiosqlite:///{(tmp_path / 'stage6.sqlite').as_posix()}",
        "storage.path": str(tmp_path / "documents"), "ingestion.ocr_enabled": False,
    })
    db = PsqlDbContext(config)
    load_models()
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    documents = KnowledgeRepository(db)
    vectors = LeakyQdrant()
    index = KnowledgeIndexService(
        documents, DocumentProcessor(config), StorageProvider(config),
        Embedded(), Reranker(), vectors, config,
    )
    history = ConversationService(ConversationRepository(db), ChatMessageRepository(db))
    llm = LocalLlm()
    chat = ChatService(llm, config, history, ScenarioRouterService(), RagService(index, config))
    try:
        yield KnowledgeService(documents), index, vectors, history, llm, chat
    finally:
        await db.dispose_async()


@pytest.mark.asyncio
async def test_chat_real_sql_retrieval_citations_and_cross_audience_isolation(stack):
    knowledge, index, vectors, history, llm, chat = stack
    public = ChatIdentity("alice", "public", frozenset({"knowledge:write"}))
    internal = ChatIdentity(
        "staff", "internal", frozenset({"knowledge:write", "knowledge:read_internal"}), "tenant-a"
    )
    doc = await knowledge.register_async(public, "Public fake manual", "txt", None, "fa", None, "public")
    await index.ingest_async(public, doc.id, "public.txt", "راهنمای عمومی ساختگی درباره درخواست مرخصی.".encode())
    secret = await knowledge.register_async(internal, "Private fake manual", "txt", None, "fa", "secret", "internal")
    await index.ingest_async(internal, secret.id, "secret.txt", "عبارت محرمانه ساختگی".encode())

    # Even with an intentionally leaky vector stub, SQL metadata is authoritative.
    conversation_id, message_id = await chat.start_async("مرخصی", public, None, "knowledge_qa")
    events = [x async for x in chat.stream_async(
        "مرخصی", uuid4(), UUID(message_id), UUID(conversation_id), public, "knowledge_qa",
    )]
    assert [x.name for x in events] == ["message_start", "sources", "delta", "message_end"]
    assert events[1].payload["documents"][0]["document_id"] == doc.id
    assert all(s["document_id"] != secret.id for s in events[1].payload["documents"])
    assert secret.title not in str(events)
    assert secret.id not in llm.calls[0][2]
    assert "internal" not in vectors.scopes
    assert events[-1].payload["response_type"] == "rag_generated"
    saved, more = await history.history_async(conversation_id, public, 10, 0)
    assert not more
    assert [(item.role, item.status) for item in saved] == [
        ("user", "completed"), ("assistant", "completed"),
    ]
    assert saved[-1].content == "پاسخ آزمایشی مستند"

    # Same internal subject, different trusted tenant: no private sources.
    outsider = ChatIdentity("staff", "internal", frozenset({"knowledge:read_internal"}), "tenant-b")
    assert not (await index.retrieve_async(outsider, "محرمانه"))
    assert not (await chat._rag.prepare_async(outsider, "محرمانه")).sources
    assert len(await index.retrieve_async(internal, "محرمانه")) == 1
