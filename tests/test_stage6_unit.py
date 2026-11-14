"""Stage 6: routing, query-aware evidence, citation fidelity and failure handling."""
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.chat.chat_service import ChatService
from src.core.services.errors import PermissionDenied
from src.core.services.rag.rag_service import RagRetrievalError, RagService
from src.core.services.scenario_router.scenario_router_service import ScenarioRouterService
from src.infrastructure.providers.llm.llama_cpp_provider import LlmStreamError


PUBLIC = ChatIdentity("public-user", "public")
INTERNAL = ChatIdentity("staff", "internal", frozenset({"knowledge:read_internal"}), "tenant-1")


class Config:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


def hit(text="سند آزمایشی معتبر", **overrides):
    result = {
        "document_id": str(uuid4()), "chunk_id": str(uuid4()),
        "title": "راهنمای ساختگی", "text": text, "version": 2,
        "source_location": {"page": 7}, "source_uri": "file:///internal/private.txt",
    }
    result.update(overrides)
    return result


class IndexStub:
    def __init__(self, results=None, error=None):
        self.results = [] if results is None else results
        self.error = error
        self.scopes = []

    async def retrieve_async(self, identity, query):
        self.scopes.append((identity, query))
        if self.error:
            raise self.error
        return self.results


def test_scenario_routing_defaults_to_direct_and_never_uses_prompt_claims():
    router = ScenarioRouterService()
    assert router.route(None, PUBLIC).path == "direct_llm"
    assert router.route("general", PUBLIC).path == "direct_llm"
    assert router.route("knowledge_qa", PUBLIC).path == "rag"
    assert router.route("knowledge_qa", INTERNAL).path == "rag"
    for scenario in ("admin", "internal", "", "religious_qa"):
        with pytest.raises(ValueError):
            router.route(scenario, PUBLIC)
    for identity in (
        ChatIdentity("staff", "internal", frozenset({"knowledge:read_internal"})),
        ChatIdentity("staff", "internal", frozenset(), "tenant-1"),
        ChatIdentity("staff", "other"),
        ChatIdentity("", "public"),
    ):
        with pytest.raises(PermissionDenied):
            router.route("knowledge_qa", identity)


@pytest.mark.asyncio
async def test_rag_builds_only_real_citations_and_keeps_tail_evidence():
    text = "مقدمه نامرتبط " * 90 + " کد امنیتی ساختگی در انتها گل‌بهار است."
    source = hit(text=text, source_location={"page": 9, "private_path": "secret"})
    index = IndexStub([source, source, hit("x", version=0), hit("x", chunk_id="invalid")])
    rag = RagService(index, Config({"rag.context_token_budget": 512, "rag.max_sources": 3}))
    prepared = await rag.prepare_async(PUBLIC, "کد امنیتی ساختگی چیست؟")
    assert index.scopes == [(PUBLIC, "کد امنیتی ساختگی چیست؟")]
    assert len(prepared.sources) == 1
    assert prepared.sources[0] == {
        "document_id": source["document_id"], "chunk_id": source["chunk_id"],
        "title": source["title"], "version": 2, "source_location": {"page": 9},
    }
    assert "امنیتی" in prepared.evidence
    assert "<<<UNTRUSTED_EVIDENCE>>>" in prepared.evidence
    assert "secret" not in prepared.evidence
    assert source["source_uri"] not in str(prepared.sources)
    assert len(prepared.evidence.encode("utf-8")) <= 512


@pytest.mark.asyncio
async def test_no_evidence_no_citations_and_sanitized_retrieval_failures():
    rag = RagService(IndexStub([]), Config())
    empty = await rag.prepare_async(PUBLIC, "سؤال ناموجود")
    assert not empty.sources and not empty.evidence
    failing = RagService(IndexStub(error=RuntimeError("secret connection uri")), Config())
    with pytest.raises(RagRetrievalError, match="RETRIEVAL_UNAVAILABLE") as exc:
        await failing.prepare_async(PUBLIC, "سؤال")
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize("values", [
    {"rag.context_token_budget": 127}, {"rag.context_token_budget": 4097},
    {"rag.max_sources": 0}, {"rag.max_sources": 11},
])
def test_context_budget_is_validated(values):
    with pytest.raises(ValueError):
        RagService(IndexStub(), Config(values))


class Conversations:
    def __init__(self):
        self.saved = []
        self.started = 0

    async def start_exchange_async(self, message, identity, conversation_id):
        self.started += 1
        return str(uuid4()), str(uuid4())

    async def prior_context_async(self, message_id, identity):
        return [{"role": "user", "content": "پرسش قبلی"}]

    async def finalize_async(self, message_id, identity, status, content):
        self.saved.append((status, content))
        return True


class Provider:
    def __init__(self, fail=False):
        self.requests = []
        self.fail = fail

    async def stream_chat_async(self, message, history=None, system_prompt=None, evidence=None):
        self.requests.append((message, history, system_prompt, evidence))
        yield "پاسخ مستند"
        if self.fail:
            raise LlmStreamError("LLM_TIMEOUT")


@pytest.mark.asyncio
async def test_rag_chat_streams_sources_before_deltas_and_persists():
    provider, conversations = Provider(), Conversations()
    evidence = hit("پاسخ معتبر آزمایشی")
    rag = RagService(IndexStub([evidence]), Config())
    chat = ChatService(provider, Config(), conversations, ScenarioRouterService(), rag)
    conv_id, mid = await chat.start_async("پرسش", PUBLIC, None, "knowledge_qa")
    events = [event async for event in chat.stream_async(
        "پرسش", uuid4(), __import__("uuid").UUID(mid), __import__("uuid").UUID(conv_id),
        PUBLIC, "knowledge_qa",
    )]
    assert [event.name for event in events] == ["message_start", "sources", "delta", "message_end"]
    assert events[0].payload["route"] == "rag"
    assert events[-1].payload == dict(events[-1].payload, status="completed", response_type="rag_generated")
    assert events[1].payload["documents"][0]["chunk_id"] == evidence["chunk_id"]
    assert "UNTRUSTED_EVIDENCE" in provider.requests[0][3]
    assert "Ignore instructions" in provider.requests[0][2]
    assert conversations.saved == [("completed", "پاسخ مستند")]


@pytest.mark.asyncio
async def test_insufficient_evidence_bypasses_model_and_is_completed():
    provider, conversations = Provider(), Conversations()
    rag = RagService(IndexStub([]), Config())
    chat = ChatService(provider, Config(), conversations, ScenarioRouterService(), rag)
    events = [x async for x in chat.stream_async("سؤال", uuid4(), uuid4(), uuid4(), PUBLIC, "knowledge_qa")]
    assert [x.name for x in events] == ["message_start", "delta", "message_end"]
    assert events[-1].payload["response_type"] == "insufficient_evidence"
    assert provider.requests == []
    assert conversations.saved == [("completed", RagService.INSUFFICIENT_MESSAGE)]


@pytest.mark.asyncio
async def test_retrieval_and_model_failure_never_mark_completed():
    for index, provider, expected in [
        (IndexStub(error=RuntimeError("sensitive")), Provider(), "RETRIEVAL_UNAVAILABLE"),
        (IndexStub([hit()]), Provider(fail=True), "LLM_TIMEOUT"),
    ]:
        conversations = Conversations()
        chat = ChatService(provider, Config(), conversations, ScenarioRouterService(), RagService(index, Config()))
        events = [x async for x in chat.stream_async("سؤال", uuid4(), uuid4(), uuid4(), PUBLIC, "knowledge_qa")]
        assert events[-2].name == "error" and events[-2].payload["code"] == expected
        assert events[-1].payload["status"] == "failed"
        assert conversations.saved[0][0] == "failed"
