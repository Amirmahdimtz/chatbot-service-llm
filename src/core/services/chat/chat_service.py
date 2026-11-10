"""Stateless stage-3 chat orchestration; history and ownership await stage 4."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from src.infrastructure.di.inject import inject
from src.infrastructure.providers.llm.llama_cpp_provider import LlamaCppProvider, LlmStreamError
from src.infrastructure.utils.config_reader import ConfigReader


@dataclass(frozen=True)
class ChatEvent:
    name: str
    payload: dict


_MESSAGES = {
    "LLM_BUSY": "The local model is busy; retry later.",
    "LLM_TIMEOUT": "The local model timed out.",
    "LLM_UNAVAILABLE": "The local model is unavailable.",
    "LLM_BAD_RESPONSE": "The local model returned an invalid response.",
    "LLM_EMPTY_RESPONSE": "The local model returned no text.",
    "OUTPUT_LIMIT": "The response exceeded the configured limit.",
}


@inject
class ChatService:
    def __init__(self, llama_cpp_provider: LlamaCppProvider, config_reader: ConfigReader) -> None:
        self._provider = llama_cpp_provider
        self._max_output_chars = int(config_reader.get("llm.max_output_chars", 8192))
        if not 1 <= self._max_output_chars <= 65536:
            raise ValueError("llm.max_output_chars must be between 1 and 65536")

    async def stream_async(self, message: str, request_id: UUID, message_id: UUID) -> AsyncIterator[ChatEvent]:
        yield ChatEvent("message_start", {
            "request_id": str(request_id), "message_id": str(message_id),
            "conversation_id": None, "role": "assistant",
        })
        chars = 0
        try:
            async for delta in self._provider.stream_chat_async(message):
                chars += len(delta)
                if chars > self._max_output_chars:
                    raise LlmStreamError("OUTPUT_LIMIT")
                yield ChatEvent("delta", {"text": delta})
            if chars == 0:
                raise LlmStreamError("LLM_EMPTY_RESPONSE")
        except LlmStreamError as exc:
            code = exc.code if exc.code in _MESSAGES else "LLM_UNAVAILABLE"
            yield ChatEvent("error", {
                "code": code, "message": _MESSAGES[code],
                "request_id": str(request_id), "message_id": str(message_id),
            })
            yield ChatEvent("message_end", {
                "request_id": str(request_id), "message_id": str(message_id), "status": "failed",
            })
            return
        yield ChatEvent("message_end", {
            "request_id": str(request_id), "message_id": str(message_id), "status": "completed",
        })
