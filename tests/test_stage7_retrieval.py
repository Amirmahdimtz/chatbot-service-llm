"""Stage 7: missing collections are empty only if SQL holds no approved documents."""
from __future__ import annotations

import httpx
import pytest

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.knowledge.knowledge_index_service import KnowledgeIndexService
from src.core.services.rag.rag_service import RagService, RagRetrievalError
from src.infrastructure.providers.vector_db import qdrant_provider
from src.infrastructure.providers.vector_db.qdrant_provider import QdrantProvider, VectorIndexError


class Config:
    def get(self, key, default=None):
        return {"vector.url": "http://localhost:6333"}.get(key, default)


class Embedding:
    model_version = "synthetic-version"
    async def embed_async(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class Documents:
    def __init__(self, approved=False):
        self.approved = approved
        self.audiences = []
    async def has_approved_index_async(self, audience):
        self.audiences.append(audience)
        return self.approved
    async def visible_async(self, ids, identity):
        assert not ids
        return {}


class MissingVectors:
    def __init__(self, exists=False):
        self.exists = exists
        self.queries = []
    async def query_async(self, scope, vector, using, filters, limit):
        self.queries.append((scope, using, filters))
        raise VectorIndexError("VECTOR_NOT_FOUND")
    async def collection_exists_async(self, audience):
        return self.exists


def make_rag(documents, vectors):
    index = KnowledgeIndexService(
        documents, object(), object(), Embedding(), object(), vectors, Config()
    )
    return RagService(index, Config())


@pytest.mark.asyncio
async def test_no_indexed_documents_and_no_collection_returns_empty_authorized_result():
    documents, vectors = Documents(), MissingVectors()
    result = await make_rag(documents, vectors).prepare_async(
        ChatIdentity("synthetic-public", "public"), "leave policy",
    )
    assert result.evidence == "" and result.sources == ()
    assert documents.audiences == ["public"]
    assert [x[1] for x in vectors.queries] == ["dense"]
    assert vectors.queries[0][2]["should"][1]["match"]["value"] == "synthetic-public"


@pytest.mark.asyncio
@pytest.mark.parametrize("approved,exists", [(True, False), (False, True), (True, True)])
async def test_missing_index_with_metadata_or_existing_collection_does_not_hide_error(approved, exists):
    documents, vectors = Documents(approved), MissingVectors(exists)
    with pytest.raises(RagRetrievalError) as failure:
        await make_rag(documents, vectors).prepare_async(
            ChatIdentity("synthetic-public", "public"), "leave policy",
        )
    assert isinstance(failure.value.__cause__, VectorIndexError)


@pytest.mark.asyncio
async def test_collection_probe_is_read_only(monkeypatch):
    original = httpx.AsyncClient
    visited = []
    def handler(request):
        visited.append((request.method, request.url.path))
        if request.url.path.endswith("knowledge_public"):
            return httpx.Response(404)
        if request.url.path.endswith("knowledge_internal"):
            return httpx.Response(200, json={"result": {"status": "green"}})
        raise AssertionError("Unexpected endpoint")
    monkeypatch.setattr(qdrant_provider.httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw,
    ))
    provider = QdrantProvider(Config())
    assert not await provider.collection_exists_async("public")
    assert await provider.collection_exists_async("internal")
    assert visited == [("GET", "/collections/knowledge_public"),
                       ("GET", "/collections/knowledge_internal")]


@pytest.mark.asyncio
async def test_other_vector_failure_is_not_downgraded_to_empty_evidence():
    class Broken(MissingVectors):
        async def query_async(self, *args):
            raise VectorIndexError("VECTOR_UNAVAILABLE")
    documents = Documents()
    with pytest.raises(RagRetrievalError) as failure:
        await make_rag(documents, Broken()).prepare_async(
            ChatIdentity("synthetic-public", "public"), "leave policy",
        )
    assert isinstance(failure.value.__cause__, VectorIndexError)
    assert documents.audiences == []
