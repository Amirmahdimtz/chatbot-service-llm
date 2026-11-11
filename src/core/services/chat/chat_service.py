"""Persisted chat orchestration with stream-safe terminal state transitions."""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.conversation.conversation_service import ConversationService
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
    "PERSISTENCE_UNAVAILABLE": "The conversation could not be saved.",
}


@inject
class ChatService:
    def __init__(
        self, llama_cpp_provider: LlamaCppProvider, config_reader: ConfigReader,
        conversation_service: ConversationService
    ) -> None:
        self._provider = llama_cpp_provider
        self._conversations = conversation_service
        self._max_output_chars = int(config_reader.get("llm.max_output_chars", 8192))
        if not 1 <= self._max_output_chars <= 65536:
            raise ValueError("llm.max_output_chars must be between 1 and 65536")

    async def start_async(
        self, message: str, identity: ChatIdentity, conversation_id: str | None
    ) -> tuple[str, str]:
        return await self._conversations.start_exchange_async(message, identity, conversation_id)

    async def stream_async(
        self, message: str, request_id: UUID, message_id: UUID,
        conversation_id: UUID, identity: ChatIdentity
    ) -> AsyncIterator[ChatEvent]:
        chunks: list[str] = []
        chars = 0
        status: str | None = None
        iterator = None
        try:
            yield ChatEvent("message_start", {
                "request_id": str(request_id), "message_id": str(message_id),
                "conversation_id": str(conversation_id), "role": "assistant",
            })
            history = await self._conversations.prior_context_async(str(message_id), identity)
            iterator = (self._provider.stream_chat_async(message, history=history)
                        if history else self._provider.stream_chat_async(message))
            async for delta in iterator:
                chars += len(delta)
                if chars > self._max_output_chars:
                    raise LlmStreamError("OUTPUT_LIMIT")
                chunks.append(delta)
                yield ChatEvent("delta", {"text": delta})
            if chars == 0:
                raise LlmStreamError("LLM_EMPTY_RESPONSE")
            if not await self._conversations.finalize_async(str(message_id), identity, "completed", "".join(chunks)):
                raise RuntimeError("Terminal transition rejected")
            status = "completed"
            yield ChatEvent("message_end", {
                "request_id": str(request_id), "message_id": str(message_id), "status": status,
            })
        except LlmStreamError as exc:
            code = exc.code if exc.code in _MESSAGES else "LLM_UNAVAILABLE"
            try:
                if not await self._conversations.finalize_async(str(message_id), identity, "failed", "".join(chunks)):
                    raise RuntimeError("Terminal transition rejected")
                status = "failed"
            except Exception:
                code = "PERSISTENCE_UNAVAILABLE"
            yield ChatEvent("error", {
                "code": code, "message": _MESSAGES[code],
                "request_id": str(request_id), "message_id": str(message_id),
            })
            yield ChatEvent("message_end", {
                "request_id": str(request_id), "message_id": str(message_id), "status": "failed",
            })
        except Exception:
            try:
                if await self._conversations.finalize_async(str(message_id), identity, "failed", "".join(chunks)):
                    status = "failed"
            except Exception:
                pass
            yield ChatEvent("error", {
                "code": "PERSISTENCE_UNAVAILABLE", "message": _MESSAGES["PERSISTENCE_UNAVAILABLE"],
                "request_id": str(request_id), "message_id": str(message_id),
            })
            yield ChatEvent("message_end", {
                "request_id": str(request_id), "message_id": str(message_id), "status": "failed",
            })
        finally:
            if iterator is not None:
                await iterator.aclose()
            if status is None:
                # Cancellation/stream closure must never persist partial text as success.
                try:
                    await self._conversations.finalize_async(
                        str(message_id), identity, "cancelled", "".join(chunks)
                    )
                except Exception:
                    # A transient DB failure leaves an explicitly non-completed streaming row.
                    pass
