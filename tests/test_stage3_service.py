"""Core stream lifecycle and error mapping are independent of the HTTP layer."""

from uuid import uuid4

import pytest

from src.core.services.chat.chat_service import ChatService
from src.infrastructure.providers.llm.llama_cpp_provider import LlmStreamError


class Config:
    def get(self, key, default=None):
        return default


class StreamProvider:
    def __init__(self, deltas=(), code=None):
        self.deltas = deltas
        self.code = code

    async def stream_chat_async(self, message):
        assert message == "سلام"
        for delta in self.deltas:
            yield delta
        if self.code:
            raise LlmStreamError(self.code)


@pytest.mark.asyncio
async def test_service_generates_single_terminal_event_and_no_fake_sources():
    events = [event async for event in ChatService(StreamProvider(["سلام", " دنیا"]), Config()).stream_async(
        "سلام", uuid4(), uuid4()
    )]
    assert [event.name for event in events] == ["message_start", "delta", "delta", "message_end"]
    assert events[0].payload["conversation_id"] is None
    assert events[-1].payload["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["LLM_TIMEOUT", "LLM_BAD_RESPONSE", "LLM_UNAVAILABLE", "LLM_BUSY"])
async def test_service_failure_is_sanitized_and_terminal_once(code):
    events = [event async for event in ChatService(StreamProvider(["partial"], code), Config()).stream_async(
        "سلام", uuid4(), uuid4()
    )]
    assert [e.name for e in events] == ["message_start", "delta", "error", "message_end"]
    assert events[-2].payload["code"] == code
    assert events[-1].payload["status"] == "failed"


@pytest.mark.asyncio
async def test_empty_output_is_failure():
    events = [event async for event in ChatService(StreamProvider(), Config()).stream_async(
        "سلام", uuid4(), uuid4()
    )]
    assert [event.name for event in events] == ["message_start", "error", "message_end"]
    assert events[1].payload["code"] == "LLM_EMPTY_RESPONSE"


@pytest.mark.asyncio
async def test_output_limit_closes_underlying_generator():
    class SmallConfig:
        def get(self, key, default=None):
            return 2 if key == "llm.max_output_chars" else default

    events = [event async for event in ChatService(StreamProvider(["abc"]), SmallConfig()).stream_async(
        "سلام", uuid4(), uuid4()
    )]
    assert events[1].payload["code"] == "OUTPUT_LIMIT"
