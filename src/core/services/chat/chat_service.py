"""Persisted chat orchestration: deterministic route, authorized evidence and safe SSE."""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from anyio import CancelScope
from uuid import UUID

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.conversation.conversation_service import ConversationService
from src.core.services.rag.rag_service import RagRetrievalError, RagService
from src.core.services.scenario_router.scenario_router_service import ScenarioRouterService
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
    "RETRIEVAL_UNAVAILABLE": "Authorized knowledge retrieval is temporarily unavailable.",
    "PERSISTENCE_UNAVAILABLE": "The conversation could not be saved.",
}


@inject
class ChatService:
    def __init__(
        self, llama_cpp_provider: LlamaCppProvider, config_reader: ConfigReader,
        conversation_service: ConversationService, scenario_router_service: ScenarioRouterService,
        rag_service: RagService,
    ) -> None:
        self._provider = llama_cpp_provider
        self._conversations = conversation_service
        self._router = scenario_router_service
        self._rag = rag_service
        self._max_output_chars = int(config_reader.get("llm.max_output_chars", 8192))
        self._history_budget = int(config_reader.get("llm.history_token_budget", 256))
        if not 1 <= self._max_output_chars <= 65536:
            raise ValueError("llm.max_output_chars must be between 1 and 65536")
        if not 0 <= self._history_budget <= 4096:
            raise ValueError("llm.history_token_budget must be between 0 and 4096")

    async def start_async(
        self, message: str, identity: ChatIdentity, conversation_id: str | None,
        scenario: str | None = None,
    ) -> tuple[str, str]:
        # Authorize before allocating a new conversation or assistant message.
        self._router.route(scenario, identity)
        return await self._conversations.start_exchange_async(message, identity, conversation_id)

    def _recent_history(self, history: list[dict[str, str]]) -> list[dict[str, str]]:
        remaining = self._history_budget
        selected: list[dict[str, str]] = []
        for item in reversed(history):
            content = item.get("content", "")
            cost = len(content.encode("utf-8"))
            if cost > remaining:
                break
            selected.append(item)
            remaining -= cost
        return list(reversed(selected))

    async def stream_async(
        self, message: str, request_id: UUID, message_id: UUID,
        conversation_id: UUID, identity: ChatIdentity, scenario: str | None = None,
    ) -> AsyncIterator[ChatEvent]:
        chunks: list[str] = []
        chars = 0
        status: str | None = None
        iterator = None
        response_type = "direct_generated"
        try:
            route = self._router.route(scenario, identity)
            yield ChatEvent("message_start", {
                "request_id": str(request_id), "message_id": str(message_id),
                "conversation_id": str(conversation_id), "role": "assistant",
                "scenario": route.scenario, "route": route.path,
            })
            history = self._recent_history(await self._conversations.prior_context_async(str(message_id), identity))
            if route.path == "rag":
                context = await self._rag.prepare_async(identity, message)
                if context.sources:
                    yield ChatEvent("sources", {"documents": list(context.sources)})
                    response_type = "rag_generated"
                    iterator = self._provider.stream_chat_async(
                        message, history=history, system_prompt=self._rag.SYSTEM_PROMPT,
                        evidence=context.evidence,
                    )
                else:
                    response_type = "insufficient_evidence"
                    text = self._rag.INSUFFICIENT_MESSAGE
                    if len(text) > self._max_output_chars:
                        raise LlmStreamError("OUTPUT_LIMIT")
                    chunks.append(text)
                    chars += len(text)
                    yield ChatEvent("delta", {"text": text})
            else:
                iterator = (self._provider.stream_chat_async(message, history=history)
                            if history else self._provider.stream_chat_async(message))
            if iterator is not None:
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
                "request_id": str(request_id), "message_id": str(message_id),
                "status": status, "response_type": response_type,
            })
        except (LlmStreamError, RagRetrievalError) as exc:
            code = exc.code if isinstance(exc, LlmStreamError) else "RETRIEVAL_UNAVAILABLE"
            if code not in _MESSAGES:
                code = "LLM_UNAVAILABLE"
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
            # Shield terminal persistence and upstream LLM cleanup on disconnect.
            with CancelScope(shield=True):
                try:
                    if status is None:
                        try:
                            await self._conversations.finalize_async(
                                str(message_id), identity, "cancelled", "".join(chunks)
                            )
                        except Exception:
                            pass
                finally:
                    if iterator is not None:
                        await iterator.aclose()
