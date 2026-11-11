"""Authenticated Chat SSE; persistence is finalized in Core, not HTTP."""
from __future__ import annotations

import json
from uuid import UUID, uuid4

from anyio import CancelScope
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.application.auth import api_error, authenticate_request
from src.application.chat.dtos.chat_dto import ChatRequestDto
from src.core.services.chat.chat_identity_service import ChatIdentityService
from src.core.services.chat.chat_service import ChatService
from src.core.services.errors import ResourceNotFound
from src.infrastructure.di.inject import inject


def encode_sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


@inject
class ChatController:
    def __init__(self, chat_service: ChatService, chat_identity_service: ChatIdentityService) -> None:
        self._chat_service = chat_service
        self._identity = chat_identity_service

    def api(self) -> APIRouter:
        router = APIRouter(tags=["Chat"])

        @router.post("/stream", summary="Stream a persisted local-model response",
                     response_class=StreamingResponse,
                     responses={
                         200: {"description": "SSE: message_start, delta*, message_end; errors via error event",
                               "content": {"text/event-stream": {"schema": {"type": "string"}}}},
                         401: {"description": "Untrusted identity"},
                         403: {"description": "Untrusted audience claim"},
                         404: {"description": "Conversation not found or not owned"},
                         503: {"description": "Persistence unavailable"},
                         422: {"description": "Invalid request"},
                     })
        async def stream_chat_async(payload: ChatRequestDto, request: Request):
            request_id = uuid4()
            principal = authenticate_request(request, self._identity, request_id)
            if isinstance(principal, JSONResponse):
                return principal
            try:
                conversation_id, message_id = await self._chat_service.start_async(
                    payload.message, principal,
                    str(payload.conversation_id) if payload.conversation_id else None
                )
            except ResourceNotFound:
                return api_error("NOT_FOUND", "Conversation not found.", 404, request_id)
            except Exception:
                return api_error("PERSISTENCE_UNAVAILABLE", "Conversation storage unavailable.", 503, request_id)

            async def stream_events_async():
                iterator = self._chat_service.stream_async(
                    payload.message, request_id, UUID(message_id), UUID(conversation_id), principal
                )
                try:
                    async for event in iterator:
                        if await request.is_disconnected():
                            break
                        yield encode_sse(event.name, event.payload)
                finally:
                    # Starlette cancels the response task when the client disconnects.
                    # Shield generator closure so the Core terminal update can finish.
                    with CancelScope(shield=True):
                        await iterator.aclose()

            return StreamingResponse(
                stream_events_async(), media_type="text/event-stream",
                headers={"X-Request-ID": str(request_id), "Cache-Control": "no-cache, no-transform",
                         "X-Accel-Buffering": "no"},
            )

        return router
