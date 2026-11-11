"""Real SQLite metadata/storage workflow with controlled local-model/Qdrant fakes."""
from __future__ import annotations

import asyncio
from collections import defaultdict

import pytest

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.errors import PermissionDenied, ResourceConflict, ResourceNotFound
from src.core.services.knowledge.knowledge_index_service import KnowledgeIndexService
from src.core.services.knowledge.knowledge_service import KnowledgeService
from src.infrastructure.alembic.model_discovery import load_models
from src.infrastructure.context.sql_db.psql_dbcontext import Base, PsqlDbContext
from src.infrastructure.providers.document.document_processor import DocumentProcessor
from src.infrastructure.providers.embedding.embedding_provider import EmbeddingError
from src.infrastructure.providers.storage.storage_provider import StorageProvider
from src.infrastructure.repositories.knowledge.knowledge_repository import KnowledgeRepository


class Config:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeEmbedding:
    dimension = 3
    model_version = "synthetic-test-v1"
    fail = False

    async def embed_async(self, texts):
        if self.fail:
            raise EmbeddingError("EMBEDDING_UNAVAILABLE")
        return [[0.5, 0.5, 0.5] for _ in texts]


class FakeReranker:
    async def rerank_async(self, query, texts):
        return [(i, 1.0 / (i + 1)) for i in range(len(texts))]


class FakeQdrant:
    def __init__(self):
        self.points = defaultdict(dict)
        self.scopes = []

    async def ensure_collection_async(self, audience, dimension, model_version):
        assert audience in ("public", "internal")
        assert dimension == 3 and model_version == "synthetic-test-v1"

    async def upsert_async(self, audience, points):
        for point in points:
            self.points[audience][point["id"]] = point

    async def query_async(self, audience, vector, using, filters, limit):
        self.scopes.append(audience)
        # Deliberately emulate an index leaking candidates; SQL remains authoritative.
        return [
            {"id": point["id"], "payload": point["payload"], "score": 1.0}
            for scope_points in self.points.values()
            for point in scope_points.values()
            if point["payload"]["active"]
        ][:limit]

    async def deactivate_version_async(self, audience, document_id, version):
        for point in self.points[audience].values():
            if point["payload"]["document_id"] == document_id and point["payload"]["version"] == version:
                point["payload"]["active"] = False

    async def set_publication_async(self, document_id, version):
        for point in self.points["public"].values():
            if point["payload"]["document_id"] == document_id and point["payload"]["version"] == version:
                point["payload"]["published"] = True


@pytest.fixture
async def system(tmp_path):
    config = Config({"database.url": f"sqlite+aiosqlite:///{(tmp_path / 'stage5.sqlite').as_posix()}",
                     "storage.path": str(tmp_path / "storage"), "ingestion.ocr_enabled": False})
    context = PsqlDbContext(config)
    load_models()
    async with context.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    repo = KnowledgeRepository(context)
    models = FakeEmbedding()
    vectors = FakeQdrant()
    index = KnowledgeIndexService(repo, DocumentProcessor(config), StorageProvider(config),
                                  models, FakeReranker(), vectors, config)
    try:
        yield KnowledgeService(repo), index, models, vectors, repo
    finally:
        await context.dispose_async()


@pytest.mark.asyncio
async def test_ingestion_version_replacement_dedup_and_safety(system):
    metadata, index, models, vectors, repo = system
    owner = ChatIdentity("alice", "public", frozenset({"knowledge:write"}))
    doc = await metadata.register_async(owner, "Synthetic", "txt", None, "fa", None, "public")
    assert doc.status == "registered"
    fresh = await index.ingest_async(owner, doc.id, "synthetic.txt", "کتاب آموزشی فارسی".encode())
    assert fresh.status == "approved" and fresh.version == 1 and len(fresh.chunk_ids) == 1
    assert fresh.checksum and fresh.storage_key
    result = await index.retrieve_async(owner, "کتاب")
    assert len(result) == 1 and result[0]["document_id"] == doc.id
    with pytest.raises(ResourceConflict):
        await index.ingest_async(owner, doc.id, "synthetic.txt", "کتاب آموزشی فارسی".encode(), replace=True)
    updated = await index.ingest_async(owner, doc.id, "synthetic.txt", "مقاله جدید".encode(), replace=True)
    assert updated.version == 2 and updated.checksum != fresh.checksum
    assert all(point["payload"]["active"] is False for point in vectors.points["public"].values()
               if point["payload"]["version"] == 1)
    latest = await index.retrieve_async(owner, "مقاله")
    assert latest and all(x["version"] == 2 for x in latest)
    reindexed = await index.ingest_async(owner, doc.id, None, None, reindex=True)
    assert reindexed.version == 3 and reindexed.checksum == updated.checksum
    assert all(x["version"] == 3 for x in await index.retrieve_async(owner, "مقاله"))
    other = await metadata.register_async(owner, "Duplicate", "txt", None, "fa", None, "public")
    with pytest.raises(ResourceConflict):
        await index.ingest_async(owner, other.id, "duplicate.txt", "مقاله جدید".encode())
    foreign = ChatIdentity("bob", "public", frozenset({"knowledge:write"}))
    with pytest.raises(ResourceNotFound):
        await index.ingest_async(foreign, doc.id, "x.txt", "bad".encode())


@pytest.mark.asyncio
async def test_retry_after_model_failure_with_saved_file(system):
    metadata, index, models, vectors, repo = system
    owner = ChatIdentity("alice", "public", frozenset({"knowledge:write"}))
    doc = await metadata.register_async(owner, "Retry", "txt", None, "fa", None, "public")
    models.fail = True
    with pytest.raises(EmbeddingError):
        await index.ingest_async(owner, doc.id, "retry.txt", "سند آزمایشی".encode())
    failed = await metadata.get_async(doc.id, owner, "public")
    assert failed.status == "failed" and failed.pending_storage_key and not failed.processing_state
    models.fail = False
    completed = await index.ingest_async(owner, doc.id, None, None, retry=True)
    assert completed.status == "approved" and completed.pending_storage_key is None
    assert len(completed.chunk_ids) == 1


@pytest.mark.asyncio
async def test_publication_cannot_be_spoofed_and_internal_isolated(system):
    metadata, index, models, vectors, repo = system
    owner = ChatIdentity("alice", "public", frozenset({"knowledge:write"}))
    other = ChatIdentity("bob", "public", frozenset({"knowledge:write"}))
    doc = await metadata.register_async(owner, "Public", "txt", None, "fa", None, "public")
    await index.ingest_async(owner, doc.id, "public.txt", "آموزش برنامه نویسی".encode())
    assert await index.retrieve_async(other, "آموزش") == []
    with pytest.raises(PermissionDenied):
        await index.publish_async(owner, doc.id)
    publisher = ChatIdentity("alice", "public", frozenset({"knowledge:publish"}))
    visible = await index.publish_async(publisher, doc.id)
    assert visible.published
    assert len(await index.retrieve_async(other, "آموزش")) == 1
    internal = ChatIdentity("staff", "internal", frozenset({"knowledge:write", "knowledge:read_internal"}), "tenant-one")
    private = await metadata.register_async(internal, "Internal", "txt", None, "fa", "secret", "internal")
    await index.ingest_async(internal, private.id, "private.txt", "اطلاعات محرمانه".encode())
    vectors.scopes.clear()
    assert not any(x["document_id"] == private.id for x in await index.retrieve_async(other, "محرمانه"))
    assert vectors.scopes and set(vectors.scopes) == {"public"}
    outsider = ChatIdentity("other", "internal", frozenset({"knowledge:read_internal"}), "tenant-two")
    assert await index.retrieve_async(outsider, "محرمانه") == []
    assert len(await index.retrieve_async(internal, "محرمانه")) == 1
