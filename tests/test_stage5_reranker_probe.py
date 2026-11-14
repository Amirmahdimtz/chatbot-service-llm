"""Stage 5 read-only reranker probe contracts and safety regression tests."""
from __future__ import annotations

import base64
import json

import pytest

from src.infrastructure.scripts.probe_stage5_reranking import (
    candidate_lengths, document_order, main_async, parse_query_base64,
    probe_retrieve_async, relevant_rank,
)


def test_probe_input_decoding_and_validation():
    encoded = base64.b64encode("سؤال فارسی".encode("utf-8")).decode("ascii")
    assert parse_query_base64(encoded) == "سؤال فارسی"
    for raw in ("not base64!", "", base64.b64encode(b"\xff").decode("ascii")):
        with pytest.raises(ValueError):
            parse_query_base64(raw)
    with pytest.raises(ValueError):
        parse_query_base64(base64.b64encode(("q" * 2049).encode()).decode())


def test_candidate_lengths_are_bounded_no_raw_texts_and_tokens_are_estimated():
    result = candidate_lengths(["سلام دنیا", "الف" * 170], 120)
    assert result[0]["characters"] == 9
    assert result[0]["approx_lexical_tokens"] == 2
    assert result[0]["prefix_characters"] == 9
    assert result[1]["prefix_characters"] == 120
    assert "سلام" not in json.dumps(result, ensure_ascii=False)


def test_document_order_rejects_ambiguous_candidate_text_mappings():
    hits = [{"text": "first", "document_id": "a"}]
    assert document_order(hits, ["first", "second"], [(0, 1.0), (1, 0.0)]) is None
    assert document_order([hits[0], hits[0]], ["first", "first"], [(0, 1.0), (1, 0.0)]) is None
    assert document_order(hits, ["first"], [(0, 1.0)]) == ["a"]
    assert relevant_rank(["a", "b"], "b") == 2
    assert relevant_rank(["a", "b"], "c") is None
    assert relevant_rank(None, "a") is None
    with pytest.raises(ValueError, match="Invalid reranking permutation"):
        document_order(hits, ["first"], [(2, 1.0)])


class FakeReranker:
    def __init__(self):
        self.requests = []

    async def rerank_async(self, query, texts):
        self.requests.append((query, list(texts)))
        return sorted(((index, 0.9 if text.endswith("TARGET") else 0.1)
                       for index, text in enumerate(texts)),
                      key=lambda pair: (-pair[1], pair[0]))


class FakeIndex:
    def __init__(self):
        self._reranking = FakeReranker()
        self.texts = ["الف" * 170, "ب" * 170 + "TARGET"]

    async def retrieve_async(self, identity, query):
        ranking = await self._reranking.rerank_async(query, self.texts)
        return [{"document_id": f"doc-{index}", "text": self.texts[index], "score": score}
                for index, score in ranking]


@pytest.mark.asyncio
async def test_probe_comparison_uses_same_candidates_and_preserves_original_results():
    service = FakeIndex()
    original = service._reranking.rerank_async
    report = await probe_retrieve_async(service, object(), "question", 100)
    assert service._reranking.rerank_async == original
    assert len(service._reranking.requests) == 2
    assert [len(x) for x in service._reranking.requests[0][1]] == [510, 176]
    assert [len(x) for x in service._reranking.requests[1][1]] == [100, 100]
    assert report["candidate_count"] == 2
    assert report["result_count"] == 2
    assert report["baseline_document_order"] == ["doc-1", "doc-0"]
    assert report["comparison"]["prefix_document_order"] == ["doc-0", "doc-1"]
    assert report["comparison"]["top_document_unchanged"] is False
    assert report["comparison"]["rank_comparison_supported"] is True
    assert report["baseline_rerank_ms"] >= 0
    assert report["comparison"]["prefix_rerank_ms"] >= 0
    assert "TARGET" not in json.dumps(report, ensure_ascii=False)


@pytest.mark.asyncio
async def test_probe_lengths_only_calls_reranker_once_and_restores_method():
    service = FakeIndex()
    original = service._reranking.rerank_async
    report = await probe_retrieve_async(service, object(), "question", None)
    assert len(service._reranking.requests) == 1
    assert service._reranking.rerank_async == original
    assert report["comparison"] is None
    assert report["lengths"][0]["prefix_characters"] is None


@pytest.mark.asyncio
async def test_probe_restores_provider_after_failure():
    service = FakeIndex()
    original = service._reranking.rerank_async

    async def broken(query, texts):
        raise RuntimeError("synthetic reranker failure")

    service._reranking.rerank_async = broken
    with pytest.raises(RuntimeError, match="synthetic reranker failure"):
        await probe_retrieve_async(service, object(), "question", 100)
    assert service._reranking.rerank_async == broken
    service._reranking.rerank_async = original


@pytest.mark.asyncio
async def test_probe_rejects_production_identity_before_bootstrap(monkeypatch):
    monkeypatch.setenv("ENV_TYPE", "production")
    with pytest.raises(RuntimeError, match="Development mode required"):
        await main_async("test", None, None)
