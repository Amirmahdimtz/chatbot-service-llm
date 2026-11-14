"""Read-only Stage 5 CPU diagnostic over authorized, real retrieval candidates.

Runs INSIDE the isolated development app container using its configured DI.
No documents are ingested or modified; no query or chunk text is printed.
Optional prefix-only A/B invokes the same local reranker twice, while the
normal service result is always computed from the unmodified baseline texts.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import json
import os
import sys
import time
from uuid import UUID

from src.core.services.chat.chat_identity_service import ChatIdentityService
from src.core.services.knowledge.knowledge_index_service import KnowledgeIndexService
from src.infrastructure.di.bootstrap import bootstrap_di
from src.infrastructure.di.inject import resolve
from src.infrastructure.providers.document.text_pipeline import token_count


def candidate_lengths(texts: list[str], max_characters: int | None = None) -> list[dict]:
    """Lexical token counts are estimates, NOT llama.cpp model token counts."""
    return [
        {
            "candidate_index": index,
            "characters": len(text),
            "approx_lexical_tokens": token_count(text),
            "prefix_characters": min(len(text), max_characters) if max_characters else None,
        }
        for index, text in enumerate(texts)
    ]


def document_order(hits: list[dict], texts: list[str], ranking: list[tuple[int, float]]) -> list[str] | None:
    """Only map indices to documents if the service returned all unique texts.

    A top-5 service response cannot reconstruct candidate-document identities if
    the configured reranking budget exceeds five; never infer this mapping.
    """
    if len(hits) != len(texts) or len(set(texts)) != len(texts):
        return None
    by_text = {hit["text"]: hit["document_id"] for hit in hits}
    if len(by_text) != len(texts) or any(text not in by_text for text in texts):
        return None
    if sorted(i for i, _ in ranking) != list(range(len(texts))):
        raise ValueError("Invalid reranking permutation")
    seen: set[str] = set()
    order = []
    for index, _ in ranking:
        doc_id = by_text[texts[index]]
        if doc_id not in seen:
            order.append(doc_id)
            seen.add(doc_id)
    return order


def relevant_rank(document_ids: list[str] | None, expected_id: str | None) -> int | None:
    if document_ids is None or expected_id is None:
        return None
    return document_ids.index(expected_id) + 1 if expected_id in document_ids else None


async def probe_retrieve_async(
    service, identity, query: str, max_characters: int | None,
    comparison_order: str = "baseline-first",
) -> dict:
    """Instrument only this process's injected provider; return baseline hits."""
    if comparison_order not in {"baseline-first", "prefix-first"}:
        raise ValueError("Invalid reranking comparison order")
    if comparison_order == "prefix-first" and max_characters is None:
        raise ValueError("Prefix-first requires max_characters")
    provider = service._reranking
    original = provider.rerank_async
    captured: dict = {}

    async def measured_rerank(user_query: str, texts: list[str]):
        if captured:
            raise RuntimeError("Expected exactly one reranking call")
        originals = list(texts)
        captured["lengths"] = candidate_lengths(originals, max_characters)
        captured["total_characters"] = sum(len(text) for text in originals)
        async def timed_rerank(candidate_texts: list[str]) -> tuple[list[tuple[int, float]], float]:
            started = time.perf_counter()
            ranking = await original(user_query, candidate_texts)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            return ranking, elapsed_ms

        if max_characters is not None and comparison_order == "prefix-first":
            shortened = [text[:max_characters] for text in originals]
            reduced, captured["prefix_ms"] = await timed_rerank(shortened)
            baseline, captured["baseline_ms"] = await timed_rerank(originals)
        else:
            baseline, captured["baseline_ms"] = await timed_rerank(originals)
            if max_characters is not None:
                shortened = [text[:max_characters] for text in originals]
                reduced, captured["prefix_ms"] = await timed_rerank(shortened)
        captured["baseline_rankings"] = baseline
        captured["originals"] = originals
        if max_characters is not None:
            captured["prefix_rankings"] = reduced
        return baseline

    provider.rerank_async = measured_rerank
    try:
        started = time.perf_counter()
        hits = await service.retrieve_async(identity, query)
        elapsed = round((time.perf_counter() - started) * 1000, 2)
    finally:
        provider.rerank_async = original

    if not captured:
        return {"candidate_count": 0, "result_count": len(hits), "request_ms": elapsed,
                "baseline_document_order": [], "lengths": [],
                "baseline_rerank_ms": None, "comparison": None}

    texts = captured["originals"]
    baseline_order = document_order(hits, texts, captured["baseline_rankings"])
    prefix_order = (document_order(hits, texts, captured["prefix_rankings"])
                    if max_characters is not None else None)
    baseline_docs = list(dict.fromkeys(hit["document_id"] for hit in hits))
    if baseline_order is not None and baseline_order != baseline_docs:
        raise RuntimeError("Baseline candidate mapping differs from service results")
    return {
        "candidate_count": len(texts),
        "result_count": len(hits),
        "baseline_document_order": baseline_docs,
        "request_ms": elapsed,
        "total_characters": captured["total_characters"],
        "lengths": captured["lengths"],
        "baseline_rerank_ms": captured["baseline_ms"],
        "comparison": None if max_characters is None else {
            "max_characters": max_characters,
            "comparison_order": comparison_order,
            "prefix_rerank_ms": captured["prefix_ms"],
            "rank_comparison_supported": baseline_order is not None and prefix_order is not None,
            "baseline_document_order": baseline_order,
            "prefix_document_order": prefix_order,
            "top_document_unchanged": (baseline_order[0] == prefix_order[0]
                                       if baseline_order and prefix_order else None),
        },
    }


def parse_query_base64(encoded: str) -> str:
    try:
        text = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("Invalid UTF-8 base64 query") from exc
    if not text.strip() or len(text) > 2048:
        raise ValueError("Query must contain between 1 and 2048 characters")
    return text


async def main_async(
    query: str, max_characters: int | None, expected_id: str | None,
    comparison_order: str = "baseline-first",
) -> dict:
    if os.environ.get("ENV_TYPE", "production").lower() != "development":
        raise RuntimeError("Development mode required")
    token = os.environ.get("CHATBOT_DEV_API_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("Development authentication unavailable")
    bootstrap_di()
    identity = resolve(ChatIdentityService).authenticate("Bearer " + token)
    if identity is None or identity.audience != "public":
        raise RuntimeError("Authorized synthetic public development identity required")
    service = resolve(KnowledgeIndexService)
    report = await probe_retrieve_async(
        service, identity, query, max_characters, comparison_order=comparison_order
    )
    report["expected_document_rank_baseline"] = relevant_rank(
        report["baseline_document_order"], expected_id
    )
    comparison = report["comparison"]
    report["expected_document_rank_prefix"] = (
        relevant_rank(comparison["prefix_document_order"], expected_id)
        if comparison is not None and comparison["rank_comparison_supported"] else None
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query-base64", required=True, help="UTF-8 base64 query; not printed")
    parser.add_argument("--max-characters", type=int, default=None,
                        help="Optional in-memory prefix-only A/B; 64..2048 characters")
    parser.add_argument("--expected-document-id", default=None,
                        help="Known relevant synthetic fixture UUID, if available")
    parser.add_argument("--order", choices=("baseline-first", "prefix-first"),
                        default="baseline-first", help="A/B invocation order; baseline-first by default")
    args = parser.parse_args(argv)
    try:
        query = parse_query_base64(args.query_base64)
        if args.max_characters is not None and not 64 <= args.max_characters <= 2048:
            raise ValueError("--max-characters must be in range 64..2048")
        if args.expected_document_id is not None:
            args.expected_document_id = str(UUID(args.expected_document_id))
        report = asyncio.run(main_async(
            query, args.max_characters, args.expected_document_id, comparison_order=args.order
        ))
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        return 0
    except (RuntimeError, ValueError) as exc:
        print(f"Stage 5 reranker probe failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
