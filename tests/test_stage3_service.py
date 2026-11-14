"""Regression tests: stream lifecycle, sanitized failures and durable terminal state."""
from uuid import uuid4

import anyio
import pytest

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.chat.chat_service import ChatService
from src.core.services.scenario_router.scenario_router_service import ScenarioRouterService
from src.infrastructure.providers.llm.llama_cpp_provider import LlmStreamError


class Config:
    def get(self, key, default=None):
        return default


class StreamProvider:
    def __init__(self, deltas=(), code=None):
        self.deltas = deltas
        self.code = code

    async def stream_chat_async(self, message, history=None):
        assert message == "سلام"
        for delta in self.deltas:
            yield delta
        if self.code:
            raise LlmStreamError(self.code)


class ConversationStub:
    def __init__(self):
        self.results = []

    async def prior_context_async(self, message_id, identity):
        return []

    async def finalize_async(self, message_id, identity, status, content):
        self.results.append((status, content))
        return True


IDENTITY = ChatIdentity("synthetic", "public")


async def get_events_async(provider, config=None):
    conversations = ConversationStub()
    events = [event async for event in ChatService(provider, config or Config(), conversations).stream_async(
        "سلام", uuid4(), uuid4(), uuid4(), IDENTITY
    )]
    return events, conversations


@pytest.mark.asyncio
async def test_completed_stream_is_durable_and_contains_real_conversation_id():
    events, conversations = await get_events_async(StreamProvider(["سلام", " دنیا"]))
    assert [event.name for event in events] == ["message_start", "delta", "delta", "message_end"]
    assert events[0].payload["conversation_id"] is not None
    assert events[-1].payload["status"] == "completed"
    assert conversations.results == [("completed", "سلام دنیا")]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["LLM_TIMEOUT", "LLM_BAD_RESPONSE", "LLM_UNAVAILABLE", "LLM_BUSY"])
async def test_service_failure_is_sanitized_and_terminal_once(code):
    events, conversations = await get_events_async(StreamProvider(["partial"], code))
    assert [e.name for e in events] == ["message_start", "delta", "error", "message_end"]
    assert events[-2].payload["code"] == code
    assert events[-1].payload["status"] == "failed"
    assert conversations.results == [("failed", "partial")]


@pytest.mark.asyncio
async def test_empty_output_is_failure():
    events, conversations = await get_events_async(StreamProvider())
    assert [event.name for event in events] == ["message_start", "error", "message_end"]
    assert events[1].payload["code"] == "LLM_EMPTY_RESPONSE"
    assert conversations.results == [("failed", "")]


@pytest.mark.asyncio
async def test_output_limit_never_completes_a_partial_response():
    class SmallConfig:
        def get(self, key, default=None):
            return 2 if key == "llm.max_output_chars" else default
    events, conversations = await get_events_async(StreamProvider(["abc"]), SmallConfig())
    assert events[1].payload["code"] == "OUTPUT_LIMIT"
    assert conversations.results == [("failed", "")]


@pytest.mark.asyncio
async def test_close_after_delta_marks_cancelled_and_preserves_partial_text():
    conversations = ConversationStub()
    stream = ChatService(StreamProvider(["سلام", " دنیا"]), Config(), conversations, ScenarioRouterService(), None).stream_async(
        "سلام", uuid4(), uuid4(), uuid4(), IDENTITY
    )
    assert (await anext(stream)).name == "message_start"
    assert (await anext(stream)).name == "delta"
    await stream.aclose()
    assert conversations.results == [("cancelled", "سلام")]


@pytest.mark.asyncio
async def test_cancel_scope_does_not_interrupt_terminal_db_cleanup():
    """Real disconnect cancellation must not abort persistence at an await."""
    class SlowConversationStub(ConversationStub):
        async def finalize_async(self, message_id, identity, status, content):
            await anyio.sleep(0)  # Cancellation checkpoint, like an async DB commit.
            return await super().finalize_async(message_id, identity, status, content)

    conversations = SlowConversationStub()
    stream = ChatService(StreamProvider(["سلام", " دنیا"]), Config(), conversations, ScenarioRouterService(), None).stream_async(
        "سلام", uuid4(), uuid4(), uuid4(), IDENTITY
    )
    async with anyio.create_task_group() as group:
        async def disconnect_async():
            assert (await anext(stream)).name == "message_start"
            assert (await anext(stream)).name == "delta"
            group.cancel_scope.cancel()
            await stream.aclose()

        group.start_soon(disconnect_async)
    assert conversations.results == [("cancelled", "سلام")]
