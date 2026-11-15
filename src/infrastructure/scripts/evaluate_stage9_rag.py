"""Read-only Stage 9 Persian RAG evidence evaluation on an isolated Stage 5 corpus.

Requires a real Stage 5 full benchmark report from the SAME isolated instance.
This evaluates retrieved evidence, never claims to grade generated answer semantics.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import statistics
import sys
import time

import httpx

from src.infrastructure.scripts.benchmark_stage5_fa import (
    BenchmarkError, evaluate_hits, load_fixture as load_stage5,
    require_local_url, response_json,
)

DATASET = Path(__file__).resolve().parents[3] / "benchmarks" / "stage9_rag_qa_fa.json"


def load_dataset(path: Path = DATASET) -> tuple[dict, str]:
    raw = path.read_bytes()
    try:
        dataset = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise BenchmarkError("Invalid Persian evaluation JSON") from exc
    if (not isinstance(dataset, dict) or set(dataset) != {
        "schema_version", "dataset_id", "source_fixture", "description",
        "cases", "negative_controls",
    } or dataset["schema_version"] != 1
            or dataset["dataset_id"] != "stage9-rag-persian-support-v1"
            or dataset["source_fixture"] != "stage5_fa_fixture.json"):
        raise BenchmarkError("Invalid RAG dataset contract")
    stage5, _ = load_stage5()
    expected = {(doc["key"], question): doc["text"]
                for doc in stage5 for question in doc["questions"]}
    covered = set()
    for case in dataset["cases"]:
        if not isinstance(case, dict) or set(case) != {
            "id", "question", "source_key", "reference_answer"
        }:
            raise BenchmarkError("Invalid RAG evaluation case")
        key = (case["source_key"], case["question"])
        if (key not in expected or key in covered
                or not isinstance(case["reference_answer"], str)
                or not case["reference_answer"].strip()
                or case["reference_answer"] not in expected[key]):
            raise BenchmarkError("Unsupported or duplicate reference answer")
        covered.add(key)
    if covered != set(expected):
        raise BenchmarkError("Dataset must cover every Stage 5 reference question")
    if (not isinstance(dataset["negative_controls"], list)
            or len(dataset["negative_controls"]) != 2
            or not all(isinstance(x, str) and x.strip() for x in dataset["negative_controls"])):
        raise BenchmarkError("Invalid negative controls")
    return dataset, sha256(raw).hexdigest()


def evaluate_response(items: list, *, expected_document_id: str, answer_anchor: str,
                      documents: dict) -> dict:
    retrieval = evaluate_hits(items, expected_document_id, documents)
    supported = [
        hit for hit in items[:5]
        if isinstance(hit, dict) and hit.get("document_id") == expected_document_id
        and isinstance(hit.get("text"), str) and answer_anchor in hit["text"]
    ]
    retrieval["reference_answer_in_expected_source_at_5"] = bool(supported)
    retrieval["reference_answer_support_count_at_5"] = len(supported)
    return retrieval


def run_evaluation(client: httpx.Client, dataset: dict, report: dict, digest: str) -> dict:
    stage5, fixture_hash = load_stage5()
    if (report.get("benchmark") != "stage5-fa-v1" or report.get("mode") != "full"
            or report.get("fixture_sha256") != fixture_hash
            or report.get("shared_corpus_warning") is not False
            or report.get("document_count") != len(stage5)
            or not isinstance(report.get("documents"), dict)):
        raise BenchmarkError("A full clean Stage 5 isolated report from the same corpus is required")
    documents = report["documents"]
    if set(documents) != {doc["key"] for doc in stage5}:
        raise BenchmarkError("Stage 5 report has incomplete document references")
    results = []
    for case in dataset["cases"]:
        t0 = time.perf_counter()
        payload = response_json(client.post("/knowledge/search", json={"query": case["question"]}))
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        metrics = evaluate_response(
            payload.get("items"), expected_document_id=documents[case["source_key"]]["id"],
            answer_anchor=case["reference_answer"], documents=documents,
        )
        results.append({
            "id": case["id"], "source_key": case["source_key"],
            "latency_ms": elapsed, **metrics,
        })
    negatives = []
    for query in dataset["negative_controls"]:
        response = response_json(client.post("/knowledge/search", json={"query": query}))
        hits = response.get("items")
        if not isinstance(hits, list):
            raise BenchmarkError("Invalid negative-control response")
        negatives.append({"returned_hits": len(hits),
                          "requires_human_relevance_review": bool(hits)})
    total = len(results)
    return {
        "report_version": 1, "evaluation": "stage9-rag-evidence-v1",
        "measurement_type": "live_public_retrieval_not_mock",
        "dataset_sha256": digest, "stage5_fixture_sha256": fixture_hash,
        "query_count": total, "negative_control_count": len(negatives),
        "metrics": {
            "recall_at_5": round(sum(x["recall_at_5"] for x in results) / total, 6),
            "mrr_at_5": round(sum(x["reciprocal_rank_at_5"] for x in results) / total, 6),
            "reference_answer_source_coverage_at_5": round(
                sum(x["reference_answer_in_expected_source_at_5"] for x in results) / total, 6),
            "citation_structure_issues_at_5": sum(x["citation_issues_at_5"] for x in results),
            "median_search_latency_ms": round(statistics.median(x["latency_ms"] for x in results), 2),
        },
        "results": results, "negative_controls": negatives,
        "limitations": [
            "Reference-answer substring support is retrieval evidence, NOT semantic citation precision of LLM answers.",
            "Negative control may return nearest unrelated documents; review their relevance manually.",
            "End-to-end generated response correctness, unsupported claim rate and RAG/Agent latency require model evaluation.",
            "Dense-only versus hybrid and reranker A/B are not exposed by this read-only API measurement.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18031")
    parser.add_argument("--stage5-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args()
    try:
        base = require_local_url(args.base_url)
        if not 5 <= args.timeout_seconds <= 900:
            raise BenchmarkError("Invalid timeout")
        if args.output.exists():
            raise BenchmarkError("Output file exists; refuse overwrite")
        import os
        token = os.getenv("CHATBOT_DEV_API_TOKEN", "")
        if len(token) < 32:
            raise BenchmarkError("CHATBOT_DEV_API_TOKEN must be set privately")
        dataset, digest = load_dataset()
        report = json.loads(args.stage5_report.read_text(encoding="utf-8"))
        with httpx.Client(
            base_url=base + "/api/v1", trust_env=False,
            headers={"Authorization": "Bearer " + token},
            timeout=httpx.Timeout(args.timeout_seconds, connect=5.0),
        ) as client:
            outcome = run_evaluation(client, dataset, report, digest)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(outcome, file, ensure_ascii=False, indent=2)
            file.write("\n")
        print(json.dumps(outcome["metrics"], ensure_ascii=False))
        return 0
    except (BenchmarkError, ValueError, OSError, httpx.HTTPError) as exc:
        print("RAG evaluation failed: " + exc.__class__.__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
