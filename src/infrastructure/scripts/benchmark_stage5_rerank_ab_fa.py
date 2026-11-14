"""Read-only Persian Stage 5 A/B: reverse-order corpus and synthetic tail evidence.

Run ONLY inside the isolated development app container. Corpus mode consumes
20 synthetic questions/expected UUIDs on stdin; tail mode fabricates longer
documents with the identifying facts beyond the prefix. No storage writes,
no new endpoint, and no production retrieval configuration changes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from uuid import UUID

from src.core.services.chat.chat_identity_service import ChatIdentityService
from src.core.services.knowledge.knowledge_index_service import KnowledgeIndexService
from src.infrastructure.di.bootstrap import bootstrap_di
from src.infrastructure.di.inject import resolve
from src.infrastructure.providers.reranking.reranking_provider import RerankingProvider
from src.infrastructure.scripts.probe_stage5_reranking import parse_query_base64, probe_retrieve_async


class RerankBenchmarkError(RuntimeError):
    """Invalid benchmark input, mapping, mode or authorization."""


# The distinctive evidence is exclusively in the suffix. Every first 120
# characters are identical: prefix-only ranking is an intentional negative
# control, not a recommendation for production retrieval.
TAIL_COMMON = (
    "این یک سند کاملاً ساختگی برای آزمایش رتبه‌بندی فارسی است. "
    "مقدمه همه سندها یکسان است و در آن هیچ شناسه، پاسخ یا نشانه اختصاصی وجود ندارد. "
    "اطلاعات متمایزکننده فقط در بخش انتهایی هر سند نوشته می‌شود. "
    "تمام اشخاص و فرایندهای این مثال خیالی هستند. "
) * 2

TAIL_FACTS = (
    ("درخواست مرخصی آزمایشی", "فرم آبی ۲۱"),
    ("ثبت پژوهش خیالی", "شناسه سبز ۴۸"),
    ("رزرو سالن آموزشی", "برگه نارنجی ۷۳"),
    ("ارجاع درخواست پشتیبانی", "کد بنفش ۹۵"),
    ("تمدید عضویت کتابخانه", "رسید نقره‌ای ۶۲"),
)


def tail_cases(max_characters: int) -> tuple[list[str], list[tuple[str, int]]]:
    """Five longer fictional documents, each answer appearing after the cut."""
    documents = [
        f"{TAIL_COMMON}\n\nفرایند اختصاصی «{topic}»: شناسه ثبت نهایی «{answer}» است."
        for topic, answer in TAIL_FACTS
    ]
    if (len(TAIL_COMMON) <= max_characters or
            len({text[:max_characters] for text in documents}) != 1 or
            not all(len(text) > max_characters + 20 for text in documents)):
        raise RerankBenchmarkError("Tail fixture no longer challenges the selected prefix")
    questions = [
        (f"شناسه ثبت نهایی فرایند «{topic}» چیست؟", index)
        for index, (topic, _) in enumerate(TAIL_FACTS)
    ]
    return documents, questions


def load_corpus_input(data: bytes) -> tuple[str, list[tuple[str, str]]]:
    """Validate allowlisted 20-question synthetic benchmark, no raw text output."""
    if not 0 < len(data) <= 65536:
        raise RerankBenchmarkError("Expected a bounded JSON corpus on stdin")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RerankBenchmarkError("Invalid UTF-8 JSON corpus") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "run_id", "document_count", "query_count", "shared_corpus_warning", "cases"
    }:
        raise RerankBenchmarkError("Invalid corpus report fields")
    run_id = payload["run_id"]
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{5,31}", run_id):
        raise RerankBenchmarkError("Invalid run ID")
    if (type(payload["document_count"]) is not int or payload["document_count"] != 10
            or type(payload["query_count"]) is not int or payload["query_count"] != 20
            or payload["shared_corpus_warning"] is not False):
        raise RerankBenchmarkError("Expected isolated 10-document / 20-question corpus")
    cases = payload["cases"]
    if not isinstance(cases, list) or len(cases) != 20:
        raise RerankBenchmarkError("Exactly 20 question records required")
    parsed: list[tuple[str, str]] = []
    questions: set[str] = set()
    expected: set[str] = set()
    for row in cases:
        if not isinstance(row, dict) or set(row) != {"query_base64", "expected_document_id"}:
            raise RerankBenchmarkError("Invalid question record")
        if not isinstance(row["query_base64"], str) or not isinstance(row["expected_document_id"], str):
            raise RerankBenchmarkError("Invalid question or UUID type")
        question = parse_query_base64(row["query_base64"])
        try:
            expected_id = str(UUID(row["expected_document_id"]))
        except (ValueError, AttributeError) as exc:
            raise RerankBenchmarkError("Invalid expected document UUID") from exc
        if question in questions:
            raise RerankBenchmarkError("Duplicate benchmark question")
        questions.add(question)
        expected.add(expected_id)
        parsed.append((question, expected_id))
    if len(expected) != 10:
        raise RerankBenchmarkError("Expected exactly 10 unique synthetic document IDs")
    return run_id, parsed


def pair_order(requested: str, index: int) -> str:
    if requested == "alternating":
        return "prefix-first" if index % 2 == 0 else "baseline-first"
    if requested not in {"baseline-first", "prefix-first"}:
        raise ValueError("Invalid comparison order")
    return requested


def rank_at_5(ranking: list[tuple[int, float]], expected_index: int, count: int) -> int | None:
    if (len(ranking) != count or
            sorted(index for index, _ in ranking) != list(range(count))):
        raise RerankBenchmarkError("Invalid full reranker ranking")
    return next((i for i, (index, _) in enumerate(ranking, 1) if index == expected_index), None)


def summarize(rows: list[dict]) -> dict:
    if not rows:
        raise RerankBenchmarkError("Cannot summarize an empty benchmark")
    baseline = [row["baseline_rerank_ms"] for row in rows]
    prefix = [row["prefix_rerank_ms"] for row in rows]
    return {
        "question_count": len(rows),
        "baseline_hit_rate_at_5": round(sum(row["baseline_rank"] is not None for row in rows) / len(rows), 6),
        "prefix_hit_rate_at_5": round(sum(row["prefix_rank"] is not None for row in rows) / len(rows), 6),
        "baseline_mrr_at_5": round(sum(1 / row["baseline_rank"] if row["baseline_rank"] else 0
                                       for row in rows) / len(rows), 6),
        "prefix_mrr_at_5": round(sum(1 / row["prefix_rank"] if row["prefix_rank"] else 0
                                     for row in rows) / len(rows), 6),
        "baseline_top1": sum(row["baseline_rank"] == 1 for row in rows),
        "prefix_top1": sum(row["prefix_rank"] == 1 for row in rows),
        "changed_top": sum(row["top_changed"] for row in rows),
        "mean_baseline_rerank_ms": round(statistics.mean(baseline), 2),
        "mean_prefix_rerank_ms": round(statistics.mean(prefix), 2),
        "median_baseline_rerank_ms": round(statistics.median(baseline), 2),
        "median_prefix_rerank_ms": round(statistics.median(prefix), 2),
        "mean_latency_reduction_percent": round(
            (1 - statistics.mean(prefix) / statistics.mean(baseline)) * 100, 2
        ) if statistics.mean(baseline) > 0 else None,
        "order_counts": {
            name: sum(row["order"] == name for row in rows)
            for name in ("baseline-first", "prefix-first")
        },
    }


def require_development_async_services() -> tuple[object, object, object]:
    """Fail closed before resolving any provider or contacting a local model."""
    if os.getenv("ENV_TYPE", "production").lower() != "development":
        raise RerankBenchmarkError("Development mode required")
    token = os.getenv("CHATBOT_DEV_API_TOKEN", "")
    if len(token) < 32:
        raise RerankBenchmarkError("Development token unavailable")
    bootstrap_di()
    identity = resolve(ChatIdentityService).authenticate("Bearer " + token)
    if identity is None or identity.audience != "public":
        raise RerankBenchmarkError("Authorized synthetic public identity required")
    return identity, resolve(KnowledgeIndexService), resolve(RerankingProvider)


async def benchmark_corpus_async(
    service, identity, cases: list[tuple[str, str]], max_characters: int, order: str,
) -> list[dict]:
    if service._rerank_candidates != 5 or service._final != 5:
        raise RerankBenchmarkError("Corpus A/B requires isolated five-candidate/five-result configuration")
    records = []
    for index, (question, expected_id) in enumerate(cases):
        selected_order = pair_order(order, index)
        probe = await probe_retrieve_async(
            service, identity, question, max_characters, comparison_order=selected_order
        )
        comparison = probe["comparison"]
        if (probe["candidate_count"] != 5 or comparison is None
                or not comparison["rank_comparison_supported"]
                or comparison["baseline_document_order"] is None
                or comparison["prefix_document_order"] is None):
            raise RerankBenchmarkError(f"Ambiguous candidate-to-document mapping at case {index + 1}")
        base_docs = comparison["baseline_document_order"]
        prefix_docs = comparison["prefix_document_order"]
        baseline_rank = base_docs.index(expected_id) + 1 if expected_id in base_docs else None
        prefix_rank = prefix_docs.index(expected_id) + 1 if expected_id in prefix_docs else None
        records.append({
            "case": index + 1,
            "order": selected_order,
            "baseline_rank": baseline_rank,
            "prefix_rank": prefix_rank,
            "top_changed": base_docs[0] != prefix_docs[0],
            "candidate_count": probe["candidate_count"],
            "total_characters": probe["total_characters"],
            "baseline_rerank_ms": probe["baseline_rerank_ms"],
            "prefix_rerank_ms": comparison["prefix_rerank_ms"],
        })
        print(f"Corpus {index + 1}/{len(cases)}: baseline_rank={baseline_rank}, "
              f"prefix_rank={prefix_rank}, order={selected_order}", file=sys.stderr, flush=True)
    return records


async def rerank_pair_async(
    reranker, question: str, texts: list[str], max_characters: int, order: str,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]], float, float]:
    async def timed(candidate_texts: list[str]) -> tuple[list[tuple[int, float]], float]:
        start = time.perf_counter()
        ranking = await reranker.rerank_async(question, candidate_texts)
        return ranking, round((time.perf_counter() - start) * 1000, 2)

    if order == "prefix-first":
        prefix_ranking, prefix_ms = await timed([text[:max_characters] for text in texts])
        baseline_ranking, baseline_ms = await timed(texts)
    elif order == "baseline-first":
        baseline_ranking, baseline_ms = await timed(texts)
        prefix_ranking, prefix_ms = await timed([text[:max_characters] for text in texts])
    else:
        raise ValueError("Invalid comparison order")
    return baseline_ranking, prefix_ranking, baseline_ms, prefix_ms


async def benchmark_tail_async(reranker, max_characters: int, order: str) -> list[dict]:
    documents, questions = tail_cases(max_characters)
    records = []
    for case_index, (question, expected_index) in enumerate(questions):
        selected_order = pair_order(order, case_index)
        base, prefix, base_ms, prefix_ms = await rerank_pair_async(
            reranker, question, documents, max_characters, selected_order
        )
        baseline_rank = rank_at_5(base, expected_index, len(documents))
        prefix_rank = rank_at_5(prefix, expected_index, len(documents))
        records.append({
            "case": case_index + 1,
            "order": selected_order,
            "baseline_rank": baseline_rank,
            "prefix_rank": prefix_rank,
            "top_changed": base[0][0] != prefix[0][0],
            "candidate_count": len(documents),
            "total_characters": sum(len(text) for text in documents),
            "baseline_rerank_ms": base_ms,
            "prefix_rerank_ms": prefix_ms,
        })
        print(f"Tail {case_index + 1}/{len(questions)}: baseline_rank={baseline_rank}, "
              f"prefix_rank={prefix_rank}, order={selected_order}",
              file=sys.stderr, flush=True)
    return records


async def execute_async(
    mode: str, max_characters: int, order: str, input_bytes: bytes | None = None
) -> dict:
    if not 64 <= max_characters <= 2048:
        raise ValueError("Prefix budget must be within 64..2048 characters")
    if order not in {"baseline-first", "prefix-first", "alternating"}:
        raise ValueError("Invalid comparison order")
    run_id = None
    cases = None
    if mode == "corpus":
        run_id, cases = load_corpus_input(input_bytes or b"")
    elif mode != "tail":
        raise ValueError("Invalid benchmark mode")
    identity, service, reranker = require_development_async_services()
    if mode == "corpus":
        rows = await benchmark_corpus_async(service, identity, cases, max_characters, order)
    else:
        rows = await benchmark_tail_async(reranker, max_characters, order)
    return {
        "benchmark": "stage5-reranking-ab-v1",
        "mode": mode,
        "run_id": run_id,
        "comparison_order": order,
        "prefix_characters": max_characters,
        "scope": "reranker-only; corpus additionally invokes unchanged authorized retrieval",
        "metrics": summarize(rows),
        "cases": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("corpus", "tail"), required=True)
    parser.add_argument("--order", choices=("baseline-first", "prefix-first", "alternating"),
                        default="alternating")
    parser.add_argument("--max-characters", type=int, default=120)
    args = parser.parse_args(argv)
    try:
        input_bytes = sys.stdin.buffer.read(65537) if args.mode == "corpus" else None
        result = asyncio.run(execute_async(args.mode, args.max_characters, args.order, input_bytes))
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0
    except (RerankBenchmarkError, RuntimeError, ValueError, OSError) as exc:
        print(f"Stage 5 A/B failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
