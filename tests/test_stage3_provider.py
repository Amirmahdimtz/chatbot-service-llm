"""MockTransport exercises actual HTTP streaming, cleanup, protocol failures and capacity."""

import asyncio
import json

import httpx
import pytest

from src.infrastructure.providers.llm import llama_cpp_provider
from src.infrastructure.providers.llm.llama_cpp_provider import LlamaCppProvider, LlmStreamError


class StubConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


def provider():
    return LlamaCppProvider(StubConfig({"llm.base_url": "http://localhost:8080", "llm.timeout_seconds": 0.25}))


def configure_transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(llama_cpp_provider.httpx, "AsyncClient",
                        lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


def content(text):
    return 'data: ' + json.dumps({"choices": [{"delta": {"content": text}}]}, ensure_ascii=False) + '\n\n'


@pytest.mark.asyncio
async def test_openai_stream_parses_utf8_and_does_not_buffer_until_done(monkeypatch):
    release = asyncio.Event()
    observed = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield content("سلام").encode("utf-8")
            await release.wait()
            yield content(" دنیا").encode("utf-8") + b"data: [DONE]\n\n"

    def handler(request):
        observed.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, stream=Stream(), headers={"content-type": "text/event-stream"})

    configure_transport(monkeypatch, handler)
    stream = provider().stream_chat_async("درود")
    assert await asyncio.wait_for(anext(stream), 0.5) == "سلام"
    assert not release.is_set()
    release.set()
    assert [delta async for delta in stream] == [" دنیا"]
    assert observed[0][0] == "/v1/chat/completions"
    body = observed[0][1]
    assert body["stream"] is True and body["max_tokens"] == 256
    assert body["messages"][-1] == {"role": "user", "content": "درود"}
    assert "model" not in body
    assert "chat_template_kwargs" not in body  # Default for other models is unchanged.


@pytest.mark.asyncio
@pytest.mark.parametrize("status,response", [
    (503, ""),
    (200, 'data: not-json\n\ndata: [DONE]\n\n'),
    (200, content("partial")),
    (200, 'data: {"choices":[{"delta":{"content":4}}]}\n\ndata: [DONE]\n\n'),
])
async def test_stream_errors_are_sanitized(monkeypatch, status, response):
    configure_transport(monkeypatch, lambda request: httpx.Response(status, text=response))
    with pytest.raises(LlmStreamError) as exc:
        _ = [x async for x in provider().stream_chat_async("synthetic")]
    assert exc.value.code in {"LLM_UNAVAILABLE", "LLM_BAD_RESPONSE"}
    assert "synthetic" not in str(exc.value)


@pytest.mark.asyncio
async def test_stream_connection_failure(monkeypatch):
    def fail(request):
        raise httpx.ConnectError("secret host address", request=request)

    configure_transport(monkeypatch, fail)
    with pytest.raises(LlmStreamError, match="LLM_UNAVAILABLE"):
        _ = [x async for x in provider().stream_chat_async("synthetic")]


@pytest.mark.asyncio
async def test_stream_timeout(monkeypatch):
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(1)
            yield b"data: [DONE]\n\n"

    configure_transport(monkeypatch, lambda req: httpx.Response(200, stream=Stream()))
    with pytest.raises(LlmStreamError, match="LLM_TIMEOUT"):
        _ = [x async for x in provider().stream_chat_async("synthetic")]


@pytest.mark.asyncio
async def test_concurrency_rejects_busy_then_releases_slot(monkeypatch):
    release = asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield content("first").encode()
            await release.wait()
            yield b"data: [DONE]\n\n"

    configure_transport(monkeypatch, lambda req: httpx.Response(200, stream=Stream()))
    instance = provider()
    first = instance.stream_chat_async("first")
    assert await anext(first) == "first"
    second = instance.stream_chat_async("second")
    with pytest.raises(LlmStreamError, match="LLM_BUSY"):
        await anext(second)
    await first.aclose()
    release.set()
    assert [x async for x in instance.stream_chat_async("third")] == ["first"]


@pytest.mark.asyncio
async def test_cancellation_releases_connection_and_slot(monkeypatch):
    started = asyncio.Event()
    closed = asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            started.set()
            try:
                await asyncio.sleep(10)
                yield b"data: [DONE]\n\n"
            finally:
                closed.set()

    configure_transport(monkeypatch, lambda req: httpx.Response(200, stream=Stream()))
    instance = provider()
    generator = instance.stream_chat_async("cancel")
    task = asyncio.create_task(anext(generator))
    await asyncio.wait_for(started.wait(), 0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    assert instance._slots._value == 1


@pytest.mark.asyncio
async def test_qwen3_nonthinking_mode_requests_final_answer_not_reasoning(monkeypatch):
    observed = []

    def handler(request):
        observed.append(json.loads(request.content))
        # A reasoning-only packet must never leak into user-visible SSE text.
        return httpx.Response(200, text=(
            'data: {"choices":[{"delta":{"reasoning_content":"private chain"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"سلام"}}]}\n\n'
            'data: [DONE]\n\n'
        ))

    configure_transport(monkeypatch, handler)
    config = StubConfig({"llm.base_url": "http://localhost:8080", "llm.enable_thinking": False})
    result = [chunk async for chunk in LlamaCppProvider(config).stream_chat_async("سلام")]
    assert result == ["سلام"]
    assert observed[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert observed[0]["messages"][-1]["content"] == "سلام"
    assert observed[0]["max_tokens"] == 256


@pytest.mark.asyncio
async def test_reasoning_only_with_no_answer_produces_no_delta(monkeypatch):
    response = (
        'data: {"choices":[{"delta":{"reasoning_content":"do not expose this"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":null},"finish_reason":"length"}]}\n\n'
        'data: [DONE]\n\n'
    )
    configure_transport(monkeypatch, lambda request: httpx.Response(200, text=response))
    instance = LlamaCppProvider(StubConfig({
        "llm.base_url": "http://localhost:8080", "llm.enable_thinking": False
    }))
    assert [chunk async for chunk in instance.stream_chat_async("synthetic")] == []


@pytest.mark.parametrize("value", ["false", 0, None, []])
def test_nonthinking_config_requires_explicit_boolean(value):
    with pytest.raises(ValueError, match="llm.enable_thinking"):
        LlamaCppProvider(StubConfig({
            "llm.base_url": "http://localhost:8080", "llm.enable_thinking": value
        }))
