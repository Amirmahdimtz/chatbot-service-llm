"""Stage 5 A/B test harness: no writes, reverse order, and suffix-evidence safety."""
from __future__ import annotations

import base64
import json
from uuid import uuid4

import pytest

from src.infrastructure.scripts.benchmark_stage5_rerank_ab_fa import (
    RerankBenchmarkError, TAIL_FACTS, benchmark_corpus_async, benchmark_tail_async,
    execute_async, load_corpus_input, pair_order, rank_at_5, summarize, tail_cases,
)
from src.infrastructure.scripts.probe_stage5_reranking import probe_retrieve_async


def make_corpus():
    ids = [str(uuid4()) for _ in range(10)]
    return {
        "run_id": "fa20261114125025",
        "document_count": 10,
        "query_count": 20,
        "shared_corpus_warning": False,
        "cases": [
            {
                "query_base64": base64.b64encode(f"سؤال آزمایشی {index}".encode()).decode(),
                "expected_document_id": ids[index // 2],
            }
            for index in range(20)
        ],
    }


def test_valid_corpus_and_scope_validation():
    sample = make_corpus()
    run_id, cases = load_corpus_input(json.dumps(sample).encode("utf-8"))
    assert run_id == sample["run_id"]
    assert len(cases) == 20
    assert len(set(identifier for _, identifier in cases)) == 10
    assert cases[0][0] == "سؤال آزمایشی 0"

    for key, value in (
        ("shared_corpus_warning", True),
        ("document_count", 9),
        ("query_count", 19),
        ("run_id", "../untrusted"),
    ):
        changed = make_corpus()
        changed[key] = value
        with pytest.raises(RerankBenchmarkError):
            load_corpus_input(json.dumps(changed).encode("utf-8"))

    malformed = make_corpus()
    malformed["cases"][0]["query_base64"] = "!!!"
    with pytest.raises(ValueError):
        load_corpus_input(json.dumps(malformed).encode("utf-8"))
    malformed = make_corpus()
    malformed["cases"][0]["expected_document_id"] = "not-a-uuid"
    with pytest.raises(RerankBenchmarkError):
        load_corpus_input(json.dumps(malformed).encode("utf-8"))
    with pytest.raises(RerankBenchmarkError):
        load_corpus_input(b"x" * 65537)


def test_tail_fixture_facts_only_after_identical_prefix():
    documents, questions = tail_cases(120)
    assert len(documents) == len(questions) == len(TAIL_FACTS) == 5
    assert len({item[:120] for item in documents}) == 1
    assert all(len(item) > 300 for item in documents)
    for index, ((topic, answer), text) in enumerate(zip(TAIL_FACTS, documents)):
        assert topic in questions[index][0]
        assert topic in text and answer in text
        assert topic not in text[:120] and answer not in text[:120]
    with pytest.raises(RerankBenchmarkError):
        tail_cases(len(documents[0]))


def test_alternating_order_and_ranking_checks():
    assert [pair_order("alternating", i) for i in range(4)] == [
        "prefix-first", "baseline-first", "prefix-first", "baseline-first"
    ]
    assert pair_order("prefix-first", 0) == "prefix-first"
    with pytest.raises(ValueError):
        pair_order("invalid", 0)
    assert rank_at_5([(2, 1.0), (0, 0.4), (1, 0.2)], 2, 3) == 1
    with pytest.raises(RerankBenchmarkError):
        rank_at_5([(1, 0.2), (1, 0.1), (2, 0.1)], 1, 3)


class SyntheticReranker:
    def __init__(self):
        self.requests = []

    async def rerank_async(self, question, texts):
        self.requests.append(list(texts))
        # Scores reflect evidence ONLY when it survives truncation.
        return sorted(
            ((index, 0.9 if any(topic in question and topic in text and answer in text
                                  for topic, answer in TAIL_FACTS) else 0.1)
             for index, text in enumerate(texts)),
            key=lambda entry: (-entry[1], entry[0]),
        )


@pytest.mark.asyncio
async def test_tail_real_shape_mocked_model_proves_prefix_negative_control():
    reranker = SyntheticReranker()
    rows = await benchmark_tail_async(reranker, 120, "alternating")
    metrics = summarize(rows)
    assert metrics["baseline_top1"] == 5
    assert metrics["prefix_top1"] == 1
    assert metrics["baseline_mrr_at_5"] == 1
    assert metrics["prefix_mrr_at_5"] < 1
    assert metrics["changed_top"] == 4
    assert metrics["order_counts"] == {"baseline-first": 2, "prefix-first": 3}
    assert len(reranker.requests) == 10
    assert all(len(item) == 5 for item in reranker.requests)
    assert all(len(text) == 120 for text in reranker.requests[0])  # prefix first
    assert all(len(text) > 120 for text in reranker.requests[1])
    assert all(len(text) > 120 for text in reranker.requests[2])  # baseline first
    assert all(len(text) == 120 for text in reranker.requests[3])


class FakeCorpusReranker:
    def __init__(self):
        self.requests = []

    async def rerank_async(self, question, texts):
        self.requests.append(list(texts))
        # Target distinguishing evidence is at the end of document index 3.
        return sorted(
            ((i, 1.0 if value.endswith("TARGET") else 0.1) for i, value in enumerate(texts)),
            key=lambda item: (-item[1], item[0]),
        )


class FakeCorpusIndex:
    _rerank_candidates = 5
    _final = 5

    def __init__(self):
        self._reranking = FakeCorpusReranker()
        self.texts = [("متن یکسان و ساختگی " * 10) + f"متن تمایز {i}" for i in range(5)]
        self.texts[3] += "TARGET"

    async def retrieve_async(self, identity, query):
        ranking = await self._reranking.rerank_async(query, self.texts)
        return [
            {"document_id": f"doc-{index}", "text": self.texts[index], "score": score}
            for index, score in ranking
        ]


@pytest.mark.asyncio
async def test_reverse_order_preserves_full_baseline_and_citation_text():
    service = FakeCorpusIndex()
    original = service._reranking.rerank_async
    report = await probe_retrieve_async(service, object(), "یک سؤال", 120, "prefix-first")
    assert service._reranking.rerank_async == original
    assert len(service._reranking.requests) == 2
    assert all(len(text) == 120 for text in service._reranking.requests[0])
    assert all(len(text) > 120 for text in service._reranking.requests[1])
    assert report["baseline_document_order"][0] == "doc-3"
    assert report["comparison"]["prefix_document_order"][0] == "doc-0"
    assert report["comparison"]["comparison_order"] == "prefix-first"
    assert report["comparison"]["top_document_unchanged"] is False


@pytest.mark.asyncio
async def test_corpus_reverse_order_uses_existing_authorized_retrieval_and_fails_closed():
    service = FakeCorpusIndex()
    records = await benchmark_corpus_async(
        service, object(), [("یک سؤال", "doc-3")], 120, "prefix-first"
    )
    assert len(records) == 1
    assert records[0]["baseline_rank"] == 1
    assert records[0]["prefix_rank"] == 4
    assert records[0]["top_changed"] is True
    assert records[0]["order"] == "prefix-first"
    assert service._reranking.requests[0] == [
        text[:120] for text in service.texts
    ]
    service._rerank_candidates = 20
    with pytest.raises(RerankBenchmarkError, match="five-candidate"):
        await benchmark_corpus_async(service, object(), [("سؤال", "doc-3")], 120, "prefix-first")


@pytest.mark.asyncio
async def test_failure_restores_reranking_method_and_rejects_invalid_order():
    service = FakeCorpusIndex()
    original = service._reranking.rerank_async
    with pytest.raises(ValueError, match="order"):
        await probe_retrieve_async(service, object(), "question", 120, "invalid")
    assert service._reranking.rerank_async == original
    with pytest.raises(ValueError, match="requires max_characters"):
        await probe_retrieve_async(service, object(), "question", None, "prefix-first")


@pytest.mark.asyncio
async def test_production_mode_refused_before_any_provider_resolution(monkeypatch):
    monkeypatch.setenv("ENV_TYPE", "production")
    with pytest.raises(RerankBenchmarkError, match="Development mode"):
        await execute_async("tail", 120, "alternating")
    with pytest.raises(ValueError, match="Prefix budget"):
        await execute_async("tail", 4, "alternating")
