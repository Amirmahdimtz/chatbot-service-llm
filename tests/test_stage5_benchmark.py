"""Deterministic Stage 5 Persian benchmark contracts; no real model or network needed."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid5, NAMESPACE_DNS

import httpx
import pytest

from src.infrastructure.scripts.benchmark_stage5_fa import (
    BenchmarkError, SMOKE_KEYS, build_report, evaluate_hits, load_fixture,
    main, prepare_documents, require_local_url,
)


def test_fixture_contains_ten_unique_synthetic_documents_and_twenty_questions():
    docs, digest = load_fixture()
    assert len(docs) == 10
    assert sum(len(doc["questions"]) for doc in docs) == 20
    assert len(digest) == 64
    assert {doc["category"] for doc in docs} == {
        "religious_qa", "human_resources", "research_advice",
        "personal_development", "task_allocation",
    }
    assert len(SMOKE_KEYS) == 3


def test_fixture_rejects_invalid_or_duplicate_question(tmp_path):
    docs, _ = load_fixture()
    docs[1]["questions"][0] = docs[0]["questions"][0]
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"schema_version": 1, "documents": docs}), encoding="utf-8")
    with pytest.raises(BenchmarkError, match="duplicate"):
        load_fixture(fixture)


def test_only_loopback_api_is_accepted():
    assert require_local_url("http://127.0.0.1:18000/") == "http://127.0.0.1:18000"
    assert require_local_url("http://localhost:18000") == "http://localhost:18000"
    for url in ("https://localhost:18000", "http://192.168.0.1:18000", "http://localhost:18000/api/v1",
                "http://localhost:18000/?secret=1", "http://user:pass@localhost:18000", "http://localhost"):
        with pytest.raises((BenchmarkError, ValueError)):
            require_local_url(url)


def _hit(document_id, chunk_id, title, *, version=1, location=None):
    return {
        "document_id": document_id, "chunk_id": chunk_id,
        "title": title, "version": version, "text": "متن فارسی آزمایشی",
        "source_location": location if location is not None else {"section": "text"},
        "score": -0.4, "rrf_score": 0.016,
    }


def test_recall_mrr_citation_and_external_docs_are_separate():
    expected = "00000000-0000-0000-0000-000000000001"
    other = "00000000-0000-0000-0000-000000000002"
    foreign = "00000000-0000-0000-0000-000000000099"
    chunk = "00000000-0000-0000-0000-000000000010"
    prepared = {"a": {"id": expected, "title": "A", "version": 1},
                "b": {"id": other, "title": "B", "version": 1}}
    hits = [_hit(foreign, chunk, "Foreign"), _hit(other, chunk, "B"),
            _hit(expected, chunk, "A")]
    result = evaluate_hits(hits, expected, prepared)
    assert result["relevant_rank"] == 3
    assert result["recall_at_5"] == 1.0
    assert result["reciprocal_rank_at_5"] == pytest.approx(1 / 3, abs=1e-6)
    assert result["external_hits_at_5"] == 1
    assert result["citation_issues_at_5"] == 0
    not_found = evaluate_hits(hits[:2], expected, prepared)
    assert not_found["relevant_rank"] is None and not_found["recall_at_5"] == 0
    broken = evaluate_hits([_hit(expected, chunk, "A", version=99)], expected, prepared)
    assert broken["citation_issues_at_5"] == 1


def test_invalid_result_structure_fails_closed():
    with pytest.raises(BenchmarkError):
        evaluate_hits([{"document_id": "bad", "chunk_id": "bad"}], "x", {})
    with pytest.raises(BenchmarkError):
        evaluate_hits("not-list", "x", {})


class FakeKnowledgeAPI:
    """Exercise the real HTTP contract with httpx's in-process transport."""

    def __init__(self, fixture):
        self.records = {}
        self.by_question = {q: doc["key"] for doc in fixture for q in doc["questions"]}
        self.registers = 0
        self.uploads = 0

    def handle(self, request):
        path = request.url.path
        if request.headers.get("authorization") != "Bearer " + "x" * 40:
            return httpx.Response(401, json={"error": {"code": "UNAUTHENTICATED"}})
        if request.method == "GET" and path == "/api/v1/knowledge/":
            return httpx.Response(200, json={"items": list(self.records.values()), "next_cursor": None})
        if request.method == "POST" and path == "/api/v1/knowledge/":
            payload = json.loads(request.content)
            identifier = str(uuid5(NAMESPACE_DNS, payload["title"]))
            doc = {**payload, "id": identifier, "version": 1, "status": "registered"}
            self.records[identifier] = doc
            self.registers += 1
            return httpx.Response(201, json=doc)
        if request.method == "POST" and path.endswith("/upload"):
            identifier = path.split("/")[-2]
            doc = self.records[identifier]
            doc["status"] = "approved"
            self.uploads += 1
            return httpx.Response(200, json=doc)
        if request.method == "POST" and path == "/api/v1/knowledge/search":
            question = json.loads(request.content)["query"]
            key = self.by_question[question]
            matching = next(d for d in reversed(list(self.records.values()))
                            if d["title"].endswith("-" + key))
            chunk = str(uuid5(NAMESPACE_DNS, matching["id"] + "-chunk"))
            return httpx.Response(200, json={"items": [_hit(matching["id"], chunk, matching["title"])]})
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})


def test_smoke_api_benchmark_and_safe_resume_without_duplicate_writes():
    fixture, digest = load_fixture()
    api = FakeKnowledgeAPI(fixture)
    with httpx.Client(base_url="http://127.0.0.1:18000/api/v1",
                      headers={"Authorization": "Bearer " + "x" * 40},
                      transport=httpx.MockTransport(api.handle)) as client:
        report = build_report(client, fixture, "test-run-0001", digest, "smoke",
                              "http://127.0.0.1:18000")
        assert report["document_count"] == 3
        assert report["query_count"] == 6
        assert report["metrics"]["recall_at_5"] == 1.0
        assert report["metrics"]["mrr_at_5"] == 1.0
        assert report["metrics"]["citation_issues_at_5"] == 0
        assert report["shared_corpus_warning"] is False
        assert api.registers == api.uploads == 3
        resumed = build_report(client, fixture, "test-run-0001", digest, "smoke",
                               "http://127.0.0.1:18000")
        assert resumed["preexisting_owned_documents"] == 3
        assert resumed["shared_corpus_warning"] is False
        assert api.registers == api.uploads == 3
        complete = build_report(client, fixture, "test-full-0001", digest, "full",
                                "http://127.0.0.1:18000")
        assert complete["document_count"] == 10
        assert complete["query_count"] == 20
        assert complete["metrics"]["recall_at_5"] == 1.0
        assert complete["metrics"]["mrr_at_5"] == 1.0
        assert complete["shared_corpus_warning"] is True
        assert api.registers == api.uploads == 13


def test_cli_rejects_unsafe_usage_without_issuing_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATBOT_DEV_API_TOKEN", "x" * 40)
    assert main(["--output", str(tmp_path / "result.json")]) == 1
    assert main(["--confirm-write", "--base-url", "http://example.com:18000",
                 "--output", str(tmp_path / "result.json")]) == 1
    assert main(["--confirm-write", "--output", str(tmp_path / "result.json"),
                 "--run-id", "../bad"]) == 1
    assert not (tmp_path / "result.json").exists()
