"""ASGI Stage 5 API and security regression on real SQLite and filesystem."""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
import pytest

from src.application.web import WebService
from src.core.services.chat.chat_identity_service import ChatIdentity, ChatIdentityService
from src.infrastructure.alembic.model_discovery import load_models
from src.infrastructure.context.sql_db.psql_dbcontext import Base, PsqlDbContext
from src.infrastructure.di.inject import install_providers, resolve
from src.infrastructure.di.reflection import discover_providers
from src.infrastructure.providers.embedding.embedding_provider import EmbeddingProvider
from src.infrastructure.providers.reranking.reranking_provider import RerankingProvider
from src.infrastructure.providers.vector_db.qdrant_provider import QdrantProvider
from src.infrastructure.utils.config_reader import ConfigReader


TOKEN = "stage5-synthetic-" + "x" * 40
HEADERS = {"Authorization": "Bearer " + TOKEN}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV_TYPE", "development")
    monkeypatch.setenv("CHATBOT_DEV_API_TOKEN", TOKEN)
    monkeypatch.setenv("CHATBOT_STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setenv("CHATBOT_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'test.sqlite').as_posix()}")
    install_providers(discover_providers())
    load_models()
    app = WebService(ConfigReader()).create_app()
    context = resolve(PsqlDbContext)
    async def init():
        async with context.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(init())
    points = {}

    async def embedding(self, texts):
        return [[0.1] * 1024 for _ in texts]

    async def rerank(self, query, texts):
        return [(i, 0.9 - i * 0.01) for i in range(len(texts))]

    async def ensure(self, audience, dimension, version):
        assert dimension == 1024

    async def upsert(self, audience, entries):
        for entry in entries:
            points[entry["id"]] = entry

    async def query(self, audience, vector, using, filters, limit):
        return [{"id": id_, "payload": point["payload"], "score": 0.8}
                for id_, point in points.items() if point["payload"]["audience"] == audience
                and point["payload"]["active"]][:limit]

    async def deactivate(self, audience, document_id, version):
        for point in points.values():
            p = point["payload"]
            if p["document_id"] == document_id and p["version"] == version:
                p["active"] = False

    async def publish(self, document_id, version):
        for point in points.values():
            if point["payload"]["document_id"] == document_id:
                point["payload"]["published"] = True

    monkeypatch.setattr(EmbeddingProvider, "embed_async", embedding)
    monkeypatch.setattr(RerankingProvider, "rerank_async", rerank)
    monkeypatch.setattr(QdrantProvider, "ensure_collection_async", ensure)
    monkeypatch.setattr(QdrantProvider, "upsert_async", upsert)
    monkeypatch.setattr(QdrantProvider, "query_async", query)
    monkeypatch.setattr(QdrantProvider, "deactivate_version_async", deactivate)
    monkeypatch.setattr(QdrantProvider, "set_publication_async", publish)
    with TestClient(app) as client:
        yield client, points


def test_api_upload_search_replace_retry_and_auth(client, monkeypatch):
    http, points = client
    routes = http.app.openapi()["paths"]
    for path in ("/api/v1/knowledge/{document_id}/upload",
                 "/api/v1/knowledge/{document_id}/retry",
                 "/api/v1/knowledge/{document_id}/reindex",
                 "/api/v1/knowledge/{document_id}/replace",
                 "/api/v1/knowledge/{document_id}/publish", "/api/v1/knowledge/search"):
        assert path in routes
    metadata = http.post("/api/v1/knowledge/", json={
        "title": "Synthetic", "source_type": "txt", "audience": "public",
    }, headers=HEADERS)
    assert metadata.status_code == 201, metadata.text
    id_ = metadata.json()["id"]
    assert http.post(f"/api/v1/knowledge/{id_}/upload", files={
        "file": ("synthetic.txt", "فایل آزمایشی فارسی".encode(), "text/plain")
    }).status_code == 401
    response = http.post(f"/api/v1/knowledge/{id_}/upload", headers=HEADERS, files={
        "file": ("synthetic.txt", "فایل آزمایشی فارسی".encode(), "text/plain")
    })
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved" and response.json()["checksum"]
    search = http.post("/api/v1/knowledge/search", headers=HEADERS, json={"query": "آزمایشی"})
    assert search.status_code == 200, search.text
    assert search.json()["items"][0]["document_id"] == id_
    replace = http.post(f"/api/v1/knowledge/{id_}/replace", headers=HEADERS, files={
        "file": ("synthetic.txt", "نسخه دوم سند".encode(), "text/plain")
    })
    assert replace.status_code == 200, replace.text
    assert replace.json()["version"] == 2
    reindexed = http.post(f"/api/v1/knowledge/{id_}/reindex", headers=HEADERS)
    assert reindexed.status_code == 200 and reindexed.json()["version"] == 3
    assert http.post(f"/api/v1/knowledge/{id_}/retry", headers=HEADERS).status_code == 409
    assert http.post(f"/api/v1/knowledge/{id_}/publish", headers=HEADERS).status_code == 403
    assert http.post("/api/v1/knowledge/search", headers={**HEADERS, "X-Audience": "internal"},
                     json={"query": "آزمایشی"}).status_code == 403
    assert http.post("/api/v1/knowledge/search", headers=HEADERS,
                     json={"query": "x", "audience": "internal"}).status_code == 422


def test_upload_type_validation_and_idor(client, monkeypatch):
    http, points = client
    id_ = http.post("/api/v1/knowledge/", headers=HEADERS, json={
        "title": "PDF", "source_type": "pdf", "audience": "public",
    }).json()["id"]
    invalid = http.post(f"/api/v1/knowledge/{id_}/upload", headers=HEADERS, files={
        "file": ("something.pdf", b"not a PDF", "application/pdf")
    })
    assert invalid.status_code == 422
    foreign = ChatIdentity("bob", "public", frozenset({"knowledge:write"}))
    old = ChatIdentityService.authenticate
    def impersonate(self, authorization):
        if authorization == "Bearer bob":
            return foreign
        return old(self, authorization)
    monkeypatch.setattr(ChatIdentityService, "authenticate", impersonate)
    response = http.post(f"/api/v1/knowledge/{id_}/upload", headers={
        "Authorization": "Bearer bob"
    }, files={"file": ("something.pdf", b"%PDF-not-real", "application/pdf")})
    assert response.status_code == 404
    assert http.get(f"/api/v1/knowledge/{id_}", headers={"Authorization": "Bearer bob"}).status_code == 404
