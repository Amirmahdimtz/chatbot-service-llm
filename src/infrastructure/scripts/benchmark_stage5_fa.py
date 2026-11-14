"""Opt-in real Stage 5 Persian retrieval benchmark using the existing public API.

Never deletes data or touches internal knowledge. This is an evaluation CLI, not
an application provider or a new endpoint.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx


FIXTURE_PATH = Path(__file__).resolve().parents[3] / "benchmarks" / "stage5_fa_fixture.json"
SMOKE_KEYS = frozenset({"religious-qa", "hr-leave", "task-assignment"})
RUN_ID_PATTERN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{5,31}\Z")


class BenchmarkError(RuntimeError):
    """An invalid benchmark contract or failed local API operation."""


def load_fixture(path: Path = FIXTURE_PATH) -> tuple[list[dict], str]:
    raw = path.read_bytes()
    fixture = json.loads(raw.decode("utf-8"))
    if fixture.get("schema_version") != 1 or not isinstance(fixture.get("documents"), list):
        raise BenchmarkError("Unsupported benchmark fixture schema")
    documents = fixture["documents"]
    if len(documents) != 10:
        raise BenchmarkError("Full fixture must contain exactly ten documents")
    keys: set[str] = set()
    questions: set[str] = set()
    for doc in documents:
        if not isinstance(doc, dict) or set(doc) != {"key", "category", "title", "text", "questions"}:
            raise BenchmarkError("Invalid document fields")
        key = doc["key"]
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9-]{2,40}", key) or key in keys:
            raise BenchmarkError("Invalid or duplicate fixture document key")
        keys.add(key)
        for field in ("category", "title", "text"):
            if not isinstance(doc[field], str) or not doc[field].strip():
                raise BenchmarkError(f"Invalid document {field}")
        if not isinstance(doc["questions"], list) or len(doc["questions"]) != 2:
            raise BenchmarkError("Exactly two questions are required per document")
        for question in doc["questions"]:
            if not isinstance(question, str) or not question.strip() or question in questions:
                raise BenchmarkError("Empty or duplicate benchmark question")
            questions.add(question)
    if not SMOKE_KEYS.issubset(keys):
        raise BenchmarkError("Smoke documents not present in fixture")
    return documents, sha256(raw).hexdigest()


def require_local_url(url: str) -> str:
    parts = urlsplit(url)
    if (parts.scheme != "http" or parts.hostname not in {"localhost", "127.0.0.1"}
            or not parts.port or parts.username or parts.password or parts.path not in ("", "/")
            or parts.query or parts.fragment):
        raise BenchmarkError("Only an HTTP loopback API URL with an explicit port is allowed")
    return url.rstrip("/")


def require_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise BenchmarkError("API returned a non-string UUID")
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise BenchmarkError("API returned an invalid UUID") from exc


def response_json(response: httpx.Response) -> dict:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise BenchmarkError(f"API returned HTTP {response.status_code} on {response.request.url.path}") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise BenchmarkError("API returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise BenchmarkError("API returned an unexpected JSON structure")
    return payload


def existing_documents(client: httpx.Client) -> list[dict]:
    """Read the scoped development owner's documents for safe same-run resume."""
    documents: list[dict] = []
    offset = 0
    for _ in range(100):  # No unbounded pagination on a potentially corrupted API.
        payload = response_json(client.get("/knowledge/", params={"offset": offset, "limit": 100}))
        items = payload.get("items")
        if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
            raise BenchmarkError("Invalid knowledge listing")
        documents.extend(items)
        if not payload.get("next_cursor"):
            return documents
        if len(items) != 100:
            raise BenchmarkError("Invalid knowledge pagination")
        offset += 100
    raise BenchmarkError("Too many scoped documents; cannot safely resume")


def prepare_documents(
    client: httpx.Client, fixture: list[dict], run_id: str, fixture_hash: str,
) -> tuple[dict[str, dict], int, int]:
    current = existing_documents(client)
    existing_count = len(current)
    run_prefix = f"FA-BENCH-{run_id}-{fixture_hash[:8]}-"
    external_count = sum(not str(item.get("title", "")).startswith(run_prefix)
                         for item in current)
    by_title: dict[str, list[dict]] = {}
    for item in current:
        by_title.setdefault(str(item.get("title")), []).append(item)
    prepared: dict[str, dict] = {}
    for doc in fixture:
        title = f"FA-BENCH-{run_id}-{fixture_hash[:8]}-{doc['key']}"
        if len(title) > 200:
            raise BenchmarkError("Benchmark title exceeds API limit")
        matches = by_title.get(title, [])
        if len(matches) > 1:
            raise BenchmarkError("Duplicate benchmark title; manual review required")
        if matches:
            registered = matches[0]
            require_uuid(registered.get("id"))
            print(f"Reuse: {doc['key']} ({registered.get('status')})", flush=True)
        else:
            registered = response_json(client.post("/knowledge/", json={
                "title": title,
                "source_type": "txt",
                "category": doc["category"],
                "language": "fa",
                "audience": "public",
            }))
            require_uuid(registered.get("id"))
            print(f"Registered: {doc['key']}", flush=True)
        status = registered.get("status")
        document_id = registered["id"]
        if status == "approved":
            pass
        elif status == "registered":
            text = doc["text"] + f"\n\nشناسه اجرای ساختگی: {run_id}"
            registered = response_json(client.post(
                f"/knowledge/{document_id}/upload",
                files={"file": (f"{doc['key']}.txt", text.encode("utf-8"), "text/plain")},
            ))
        elif status == "failed" and registered.get("checksum") is None:
            # A failed ingestion might have a saved pending file; retry it first.
            registered = response_json(client.post(f"/knowledge/{document_id}/retry"))
        else:
            raise BenchmarkError(f"Unsafe resume status for {doc['key']}: {status}")
        if registered.get("status") != "approved" or registered.get("audience") != "public":
            raise BenchmarkError(f"Document {doc['key']} was not approved as public")
        prepared[doc["key"]] = {
            "id": require_uuid(registered["id"]),
            "title": title,
            "version": registered.get("version"),
            "embedding_model_version": registered.get("embedding_model_version"),
        }
        print(f"Approved: {doc['key']}", flush=True)
    return prepared, existing_count, external_count


def evaluate_hits(hits: object, expected_id: str, prepared: dict[str, dict]) -> dict:
    if not isinstance(hits, list):
        raise BenchmarkError("Search result items must be a list")
    known = {item["id"]: item for item in prepared.values()}
    seen: set[str] = set()
    document_ranks: list[str] = []
    invalid_citations = 0
    external_hits = 0
    for hit in hits[:5]:
        if not isinstance(hit, dict):
            raise BenchmarkError("Search result item is not an object")
        document_id = require_uuid(hit.get("document_id"))
        chunk_id = require_uuid(hit.get("chunk_id"))
        location = hit.get("source_location")
        valid = (type(hit.get("version")) is int and hit["version"] > 0
                 and isinstance(location, dict)
                 and isinstance(hit.get("text"), str) and bool(hit["text"].strip())
                 and all(type(hit.get(k)) in (float, int) and math.isfinite(hit[k])
                         for k in ("score", "rrf_score")))
        if document_id in known:
            record = known[document_id]
            valid = valid and (hit.get("version") == record["version"]
                               and hit.get("title") == record["title"]
                               and isinstance(location, dict) and location.get("section") == "text")
        else:
            external_hits += 1
        if not valid:
            invalid_citations += 1
        if document_id not in seen:
            seen.add(document_id)
            document_ranks.append(document_id)
    rank = document_ranks.index(expected_id) + 1 if expected_id in document_ranks else None
    return {
        "relevant_rank": rank,
        "recall_at_5": 1.0 if rank is not None else 0.0,
        "reciprocal_rank_at_5": round(1.0 / rank, 6) if rank else 0.0,
        "returned_hits": len(hits),
        "unique_document_ids_at_5": document_ranks,
        "external_hits_at_5": external_hits,
        "citation_issues_at_5": invalid_citations,
    }


def build_report(
    client: httpx.Client, fixture: list[dict], run_id: str, fixture_hash: str,
    mode: str, base_url: str,
) -> dict:
    selected = [doc for doc in fixture if mode == "full" or doc["key"] in SMOKE_KEYS]
    prepared, existing_count, external_count = prepare_documents(client, selected, run_id, fixture_hash)
    records = []
    for doc in selected:
        for question in doc["questions"]:
            started = time.perf_counter()
            payload = response_json(client.post("/knowledge/search", json={"query": question}))
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            metrics = evaluate_hits(payload.get("items"), prepared[doc["key"]]["id"], prepared)
            records.append({"question": question, "expected_key": doc["key"],
                            "expected_document_id": prepared[doc["key"]]["id"],
                            "latency_ms": latency_ms, **metrics})
            print(f"Query {len(records)}/{2 * len(selected)}: "
                  f"rank={metrics['relevant_rank']} latency_ms={latency_ms}", flush=True)
    latencies = sorted(item["latency_ms"] for item in records)
    count = len(records)
    citation_issues = sum(item["citation_issues_at_5"] for item in records)
    return {
        "benchmark": "stage5-fa-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "mode": mode,
        "fixture_sha256": fixture_hash,
        "base_url": base_url,
        "preexisting_owned_documents": existing_count,
        "preexisting_non_run_documents": external_count,
        "shared_corpus_warning": external_count > 0,
        "document_count": len(selected),
        "query_count": count,
        "metrics": {
            "recall_at_5": round(sum(x["recall_at_5"] for x in records) / count, 6),
            "mrr_at_5": round(sum(x["reciprocal_rank_at_5"] for x in records) / count, 6),
            "mean_latency_ms": round(statistics.mean(latencies), 2),
            "median_latency_ms": round(statistics.median(latencies), 2),
            "p95_latency_ms": latencies[math.ceil(0.95 * count) - 1],
            "max_latency_ms": latencies[-1],
            "citation_issues_at_5": citation_issues,
            "external_hits_at_5": sum(x["external_hits_at_5"] for x in records),
        },
        "documents": prepared,
        "questions": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18000",
                        help="Local FastAPI host URL; no /api/v1 path")
    parser.add_argument("--mode", choices=("smoke", "full"), default="smoke")
    parser.add_argument("--run-id", default=None, help="Stable run identifier for safe resume")
    parser.add_argument("--output", type=Path, required=True, help="New UTF-8 JSON report file")
    parser.add_argument("--confirm-write", action="store_true",
                        help="Explicitly authorize writing synthetic public documents")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args(argv)
    try:
        if not args.confirm_write:
            raise BenchmarkError("--confirm-write required: the benchmark persists synthetic documents")
        base_url = require_local_url(args.base_url)
        run_id = args.run_id or uuid4().hex[:12]
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise BenchmarkError("Run ID must be 6-32 ASCII letters, digits, '-' or '_'")
        if not 5 <= args.timeout_seconds <= 900:
            raise BenchmarkError("Timeout must be 5-900 seconds")
        token = os.environ.get("CHATBOT_DEV_API_TOKEN", "")
        if len(token) < 32:
            raise BenchmarkError("CHATBOT_DEV_API_TOKEN must be set as a secret environment variable")
        if args.output.exists():
            raise BenchmarkError("Output already exists; choose a new filename (no overwrite)")
        fixture, fixture_hash = load_fixture()
        print(f"Run ID: {run_id}; mode: {args.mode}; synthetic public writes only", flush=True)
        timeout = httpx.Timeout(args.timeout_seconds, connect=5.0)
        with httpx.Client(base_url=f"{base_url}/api/v1", timeout=timeout,
                          headers={"Authorization": f"Bearer {token}"}, trust_env=False) as client:
            report = build_report(client, fixture, run_id, fixture_hash, args.mode, base_url)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as out:
            json.dump(report, out, ensure_ascii=False, indent=2)
            out.write("\n")
        print(json.dumps(report["metrics"], ensure_ascii=False), flush=True)
        if report["shared_corpus_warning"]:
            print("WARNING: existing owner documents were present; quality metrics are not isolated.",
                  flush=True)
        print(f"Report: {args.output}", flush=True)
        return 0
    except (BenchmarkError, httpx.HTTPError, OSError, ValueError) as exc:
        print(f"Benchmark failed: {exc.__class__.__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
