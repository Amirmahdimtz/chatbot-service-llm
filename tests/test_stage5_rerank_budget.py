"""Bounded, optional Stage 5 reranking budget without changing access or citation semantics."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.knowledge.knowledge_index_service import KnowledgeIndexService
from src.infrastructure.utils.config_reader import ConfigReader


class Config:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


class Embedding:
    model_version = "synthetic-v1"

    async def embed_async(self, texts):
        return [[0.5, 0.5, 0.5] for _ in texts]


class Vectors:
    def __init__(self, points):
        self.points = points
        self.queries = []

    async def query_async(self, audience, vector, using, filters, limit):
        self.queries.append((audience, using, limit, filters))
        return self.points[:limit]


class Documents:
    def __init__(self, points):
        self.docs = {}
        for point in points:
            payload = point["payload"]
            self.docs[payload["document_id"]] = SimpleNamespace(
                version=1, embedding_model_version="synthetic-v1",
                audience="public", chunk_ids=[point["id"]],
            )
        self.requested = None

    async def visible_async(self, document_ids, identity):
        self.requested = (document_ids, identity.audience)
        return {key: val for key, val in self.docs.items() if key in document_ids}


class Reranker:
    def __init__(self):
        self.requests = []

    async def rerank_async(self, query, texts):
        self.requests.append((query, texts))
        return [(i, 0.9 - 0.01 * i) for i in range(len(texts))]


def make_index(config):
    points = []
    for i in range(8):
        points.append({
            "id": f"chunk-{i}",
            "payload": {
                "document_id": f"doc-{i}",
                "version": 1,
                "embedding_model_version": "synthetic-v1",
                "audience": "public",
                "text": f"سند فارسی شماره {i}",
                "location": {"section": "text"},
                "title": f"عنوان {i}",
            },
        })
    docs, reranker, vectors = Documents(points), Reranker(), Vectors(points)
    index = KnowledgeIndexService(
        docs, object(), object(), Embedding(), reranker, vectors, Config(config)
    )
    return index, docs, reranker, vectors


@pytest.mark.asyncio
@pytest.mark.parametrize("budget,expected", [(5, 5), (8, 8), (None, 8)])
async def test_reranker_budget_preserves_authorized_rrf_ranking_and_full_citations(budget, expected):
    config = {} if budget is None else {"retrieval.rerank_candidates": budget}
    index, docs, reranker, vectors = make_index(config)
    identity = ChatIdentity("test", "public")
    result = await index.retrieve_async(identity, "سؤال فارسی")
    assert len(reranker.requests) == 1
    assert len(reranker.requests[0][1]) == expected
    assert reranker.requests[0][1][0] == "سند فارسی شماره 0"
    assert len(result) == 5
    assert [hit["document_id"] for hit in result] == [f"doc-{i}" for i in range(5)]
    assert result[0]["text"] == "سند فارسی شماره 0"
    assert result[0]["source_location"] == {"section": "text"}
    assert result[0]["score"] == pytest.approx(0.9)
    assert result[0]["rrf_score"] > 0
    assert docs.requested[1] == "public"
    assert set(audience for audience, _, _, _ in vectors.queries) == {"public"}
    assert len(vectors.queries) == 2
    assert all(limit == 20 for _, _, limit, _ in vectors.queries)


@pytest.mark.parametrize("budget", [0, 4, 21, -1, "not-an-integer"])
def test_reranker_candidate_budget_rejects_invalid_values(budget):
    with pytest.raises(ValueError):
        make_index({"retrieval.rerank_candidates": budget})


def test_config_reader_accepts_optional_environment_budget(monkeypatch):
    monkeypatch.setenv("CHATBOT_RERANK_CANDIDATES", "5")
    assert ConfigReader().get("retrieval.rerank_candidates", 20) == "5"
    monkeypatch.delenv("CHATBOT_RERANK_CANDIDATES")
    assert ConfigReader().get("retrieval.rerank_candidates", 20) == 20
