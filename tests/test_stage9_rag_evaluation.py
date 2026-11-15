"""Stage 9 Persian RAG reference coverage: pure validation and simulated HTTP tests."""
from __future__ import annotations

import json
from uuid import NAMESPACE_DNS, uuid5

import httpx
import pytest

from src.infrastructure.scripts.benchmark_stage5_fa import BenchmarkError, load_fixture
from src.infrastructure.scripts.evaluate_stage9_rag import (
    evaluate_response, load_dataset, run_evaluation,
)


def test_versioned_persian_reference_data_matches_known_source_text():
    dataset, digest = load_dataset()
    documents, _ = load_fixture()
    assert len(digest) == 64
    assert len(dataset["cases"]) == sum(len(doc["questions"]) for doc in documents) == 20
    assert len(dataset["negative_controls"]) == 2
    source_by_key = {doc["key"]: doc for doc in documents}
    assert all(
        case["reference_answer"] in source_by_key[case["source_key"]]["text"]
        for case in dataset["cases"]
    )


def test_invalid_answer_anchor_cannot_be_claimed_as_supported(tmp_path):
    dataset, _ = load_dataset()
    dataset["cases"][0]["reference_answer"] = "پاسخ جعلی کاملاً ناموجود"
    file = tmp_path / "invalid.json"
    file.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(BenchmarkError, match="Unsupported"):
        load_dataset(file)


def _synthetic_results():
    fixture, fixture_hash = load_fixture()
    by_key = {doc["key"]: doc for doc in fixture}
    prepared = {
        key: {
            "id": str(uuid5(NAMESPACE_DNS, "stage9-source-" + key)),
            "title": doc["title"],
            "version": 1,
        }
        for key, doc in by_key.items()
    }
    reference = {
        question: (key, doc)
        for key, doc in by_key.items()
        for question in doc["questions"]
    }
    report = {
        "benchmark": "stage5-fa-v1",
        "mode": "full",
        "fixture_sha256": fixture_hash,
        "shared_corpus_warning": False,
        "document_count": len(fixture),
        "documents": prepared,
    }
    return prepared, reference, report


def test_simulated_http_reference_retrieval_is_not_real_model_benchmark():
    dataset, digest = load_dataset()
    prepared, reference, report = _synthetic_results()

    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/api/v1/knowledge/search"
        query = json.loads(request.content)["query"]
        if query not in reference:
            return httpx.Response(200, json={"items": []})
        key, doc = reference[query]
        return httpx.Response(200, json={"items": [{
            "document_id": prepared[key]["id"],
            "chunk_id": str(uuid5(NAMESPACE_DNS, "stage9-chunk-" + key)),
            "title": doc["title"], "version": 1,
            "text": doc["text"], "source_location": {"section": "text"},
            "score": -0.4, "rrf_score": 0.016,
        }]})

    with httpx.Client(
        base_url="http://127.0.0.1:18031/api/v1",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = run_evaluation(client, dataset, report, digest)
    assert result["measurement_type"] == "live_public_retrieval_not_mock"
    # The identifier above describes the intended production runner; here the
    # injected MockTransport explicitly simulates results, never real model quality.
    assert result["query_count"] == 20
    assert result["negative_control_count"] == 2
    assert result["metrics"]["recall_at_5"] == 1.0
    assert result["metrics"]["mrr_at_5"] == 1.0
    assert result["metrics"]["reference_answer_source_coverage_at_5"] == 1.0
    assert result["metrics"]["citation_structure_issues_at_5"] == 0
    assert all(x["returned_hits"] == 0 for x in result["negative_controls"])


def test_retrieval_hit_does_not_imply_answer_text_support():
    prepared, _, _ = _synthetic_results()
    key = "religious-qa"
    hit = {
        "document_id": prepared[key]["id"],
        "chunk_id": str(uuid5(NAMESPACE_DNS, "stage9-chunk-" + key)),
        "title": prepared[key]["title"],
        "version": 1,
        "text": "متن آزمایشی بدون پاسخ مرجع",
        "source_location": {"section": "text"},
        "score": 0.1, "rrf_score": 0.02,
    }
    measured = evaluate_response(
        [hit], expected_document_id=prepared[key]["id"],
        answer_anchor="به کارشناس ارجاع شود", documents=prepared,
    )
    assert measured["recall_at_5"] == 1.0
    assert measured["reference_answer_in_expected_source_at_5"] is False
    assert measured["reference_answer_support_count_at_5"] == 0


def test_shared_corpus_or_wrong_dataset_report_is_rejected():
    dataset, digest = load_dataset()
    _, _, report = _synthetic_results()
    report["shared_corpus_warning"] = True
    with httpx.Client(
        base_url="http://127.0.0.1:18031/api/v1",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"items": []})),
    ) as client:
        with pytest.raises(BenchmarkError, match="isolated"):
            run_evaluation(client, dataset, report, digest)
