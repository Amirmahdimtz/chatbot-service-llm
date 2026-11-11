"""Opt-in genuine Qdrant REST integration, never against a populated user collection."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from src.infrastructure.providers.vector_db.qdrant_provider import QdrantProvider, VectorIndexError
from src.infrastructure.providers.document.text_pipeline import sparse_keywords


class Config:
    def __init__(self, url, public, internal):
        self.values = {
            "vector.url": url, "vector.public_collection": public,
            "vector.internal_collection": internal, "vector.timeout_seconds": 30,
        }

    def get(self, key, default=None):
        return self.values.get(key, default)


@pytest.mark.asyncio
async def test_real_qdrant_hybrid_dense_sparse_and_non_destructive_schema_guard():
    url = os.getenv("CHATBOT_TEST_QDRANT_URL")
    if not url or os.getenv("CHATBOT_TEST_QDRANT_ISOLATED") != "1":
        pytest.skip("Only run against explicitly isolated Qdrant test instance")
    scope = uuid4().hex
    provider = QdrantProvider(Config(url, f"test_stage5_public_{scope}", f"test_stage5_internal_{scope}"))
    await provider.ensure_collection_async("public", 3, "synthetic-stage5-only")
    ids = [str(uuid4()), str(uuid4())]
    points = [
        {"id": ids[0], "vector": {
            "dense": [1.0, 0.0, 0.0], "lexical": sparse_keywords("پژوهش و آموزش")
        }, "payload": {"document_id": str(uuid4()), "audience": "public",
                        "active": True, "published": True,
                        "embedding_model_version": "synthetic-stage5-only"}},
        {"id": ids[1], "vector": {
            "dense": [0.0, 1.0, 0.0], "lexical": sparse_keywords("منابع مالی")
        }, "payload": {"document_id": str(uuid4()), "audience": "public",
                        "active": True, "published": True,
                        "embedding_model_version": "synthetic-stage5-only"}},
    ]
    await provider.upsert_async("public", points)
    scope_filter = {"must": [
        {"key": "audience", "match": {"value": "public"}},
        {"key": "active", "match": {"value": True}},
    ]}
    dense = await provider.query_async("public", [1.0, 0.0, 0.0], "dense", scope_filter, 5)
    sparse = await provider.query_async("public", sparse_keywords("پژوهش"), "lexical", scope_filter, 5)
    assert dense and dense[0]["id"] == ids[0]
    assert sparse and sparse[0]["id"] == ids[0]
    with pytest.raises(VectorIndexError, match="VECTOR_SCHEMA_MISMATCH"):
        await provider.ensure_collection_async("public", 4, "synthetic-stage5-only")
    with pytest.raises(VectorIndexError, match="VECTOR_MODEL_MISMATCH"):
        await provider.ensure_collection_async("public", 3, "other-embedding-version")
    # Do not delete collections; disposable runner is responsible for teardown.
