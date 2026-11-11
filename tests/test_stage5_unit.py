"""Stage 5 parser, normalization, sparse lexical indexing and provider contracts."""
from __future__ import annotations

import csv
from io import BytesIO
import json
from pathlib import Path

import fitz
import httpx
import pytest
from docx import Document
from openpyxl import Workbook

from src.core.services.knowledge.knowledge_index_service import reciprocal_rank_fusion
from src.infrastructure.providers.document.document_processor import DocumentProcessor, DocumentProcessingError
from src.infrastructure.providers.document.text_pipeline import TextChunk, chunk_sections, normalize_persian, sparse_keywords
from src.infrastructure.providers.embedding.embedding_provider import EmbeddingProvider, EmbeddingError
from src.infrastructure.providers.reranking.reranking_provider import RerankingProvider, RerankingError
from src.infrastructure.providers.vector_db.qdrant_provider import QdrantProvider, VectorIndexError


class Config:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key, default=None):
        return self._values.get(key, default)


@pytest.fixture
def processor():
    return DocumentProcessor(Config({"ingestion.ocr_enabled": False}))


def documents():
    word = Document()
    word.add_paragraph("متن آزمایشی فارسی")
    table = word.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "ستون"
    table.cell(0, 1).text = "مقدار"
    word_file = BytesIO()
    word.save(word_file)

    book = Workbook()
    book.active.title = "آزمایش"
    book.active.append(["شناسه", "عنوان"])
    book.active.append([1, "دانش"])
    xlsx_file = BytesIO()
    book.save(xlsx_file)

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((60, 60), "Synthetic English PDF content for parsing.")
    pdf_content = pdf.tobytes()
    pdf.close()
    return {
        "txt": "منابع داده و دانش".encode(),
        "json": json.dumps({"text": "دانش فارسی"}, ensure_ascii=False).encode(),
        "csv": "title,value\nنام,داده\n".encode(),
        "docx": word_file.getvalue(),
        "xlsx": xlsx_file.getvalue(),
        "pdf": pdf_content,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["txt", "json", "csv", "docx", "xlsx", "pdf"])
async def test_parser_valid_formats_and_provenance(processor, kind):
    pieces = await processor.extract_async(documents()[kind], kind)
    assert pieces and any(x.text.strip() for x in pieces)
    assert all(isinstance(piece.location, dict) for piece in pieces)
    if kind == "xlsx":
        assert any(piece.location.get("sheet") == "آزمایش" for piece in pieces)
    if kind == "pdf":
        assert pieces[0].location["page"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["txt", "json", "csv", "doc", "docx", "xlsx", "pdf"])
async def test_invalid_files_are_rejected(processor, kind):
    with pytest.raises(DocumentProcessingError):
        await processor.extract_async(b"not a valid document\x00", kind)


@pytest.mark.asyncio
async def test_doc_requires_actual_local_converter(processor, monkeypatch):
    from src.infrastructure.providers.document import document_processor
    monkeypatch.setattr(document_processor.shutil, "which", lambda _: None)
    with pytest.raises(DocumentProcessingError, match="DOC_CONVERTER_UNAVAILABLE"):
        await processor.extract_async(bytes.fromhex("D0CF11E0A1B11AE1") + b"x" * 200, "doc")


def test_persian_and_chunk_boundaries():
    assert normalize_persian("  كتاب يكي\n\n\nآموزش‌ ها  ") == "کتاب یکی\n\nآموزش ها"
    paragraphs = [TextChunk("الف " * 90 + "\n\n" + "ب " * 90, {"page": 2}),
                  TextChunk("جدول | عنوان\n\nردیف | مقدار", {"sheet": "نمونه"})]
    result = chunk_sections(paragraphs, size=40, overlap=6)
    assert len(result) > 4
    assert all(item.text and item.location for item in result)
    assert {tuple(item.location.items()) for item in result} == {(("page", 2),), (("sheet", "نمونه"),)}
    assert chunk_sections([TextChunk("  ", {"page": 1})]) == []
    with pytest.raises(ValueError):
        chunk_sections(paragraphs, size=2)


def test_lexical_vectors_are_real_repeatable_and_sensitive_to_words():
    a = sparse_keywords("آموزش آموزش تحصیل")
    b = sparse_keywords("آموزش آموزش تحصیل")
    c = sparse_keywords("اتومبیل")
    assert a == b and len(a["indices"]) == 2
    assert a["indices"] != c["indices"]
    assert a["indices"] == sorted(a["indices"])


def test_rrf_deduplicates_and_reorders():
    first = [{"id": "a"}, {"id": "b"}]
    second = [{"id": "b"}, {"id": "c"}, {"id": "b"}]
    result = reciprocal_rank_fusion([first, second], k=60)
    assert [item["id"] for item in result] == ["b", "a", "c"]
    assert result[0]["rrf_score"] > result[1]["rrf_score"]
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([], k=0)


@pytest.mark.asyncio
async def test_local_embedding_validates_dimensions_and_finite_scores(monkeypatch):
    from src.infrastructure.providers.embedding import embedding_provider
    original = httpx.AsyncClient
    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={"data": [
            {"index": i, "embedding": [0.3, 0.4, 0.5]} for i, _ in enumerate(body["input"])
        ]})
    monkeypatch.setattr(embedding_provider.httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw))
    provider = EmbeddingProvider(Config({"embedding.base_url": "http://localhost:8081", "embedding.dimension": 3}))
    assert len(await provider.embed_async(["الف", "ب"])) == 2
    provider.dimension = 4
    with pytest.raises(EmbeddingError, match="DIMENSION"):
        await provider.embed_async(["الف"])


@pytest.mark.asyncio
async def test_local_reranker_validates_output(monkeypatch):
    from src.infrastructure.providers.reranking import reranking_provider
    original = httpx.AsyncClient
    def handler(request):
        return httpx.Response(200, json={"results": [
            {"index": 1, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.2},
        ]})
    monkeypatch.setattr(reranking_provider.httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw))
    provider = RerankingProvider(Config({"reranking.base_url": "http://localhost:8082"}))
    assert (await provider.rerank_async("q", ["a", "b"]))[0] == (1, 0.9)


@pytest.mark.asyncio
async def test_qdrant_collection_schema_and_queries(monkeypatch):
    from src.infrastructure.providers.vector_db import qdrant_provider
    original = httpx.AsyncClient
    state = {"created": False, "upserts": 0}
    def handler(request):
        path = request.url.path
        if request.method == "GET" and path == "/collections/knowledge_public":
            if not state["created"]:
                return httpx.Response(404)
            return httpx.Response(200, json={"result": {"config": {"params": {
                "vectors": {"dense": {"size": 3, "distance": "Cosine"}},
                "sparse_vectors": {"lexical": {}},
            }}}})
        if request.method == "PUT" and path == "/collections/knowledge_public":
            state["created"] = True
            return httpx.Response(200, json={"result": True})
        if path.endswith("/points/scroll"):
            return httpx.Response(200, json={"result": {"points": []}})
        if path.endswith("/points/query"):
            return httpx.Response(200, json={"result": {"points": [{"id": "synthetic", "payload": {}}]}})
        if path.endswith("/points"):
            state["upserts"] += 1
            return httpx.Response(200, json={"result": {"status": "completed"}})
        return httpx.Response(404)
    monkeypatch.setattr(qdrant_provider.httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw))
    provider = QdrantProvider(Config({"vector.url": "http://localhost:6333"}))
    await provider.ensure_collection_async("public", 3, "test-version")
    assert state["created"]
    await provider.upsert_async("public", [{"id": "synthetic", "vector": {}, "payload": {}}])
    assert state["upserts"] == 1
    assert len(await provider.query_async("public", [1, 2, 3], "dense", {"must": []}, 5)) == 1
    with pytest.raises(VectorIndexError):
        provider.collection("unknown")
