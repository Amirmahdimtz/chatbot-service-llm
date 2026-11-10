"""HTTP authentication, request validation and SSE framing; workflow stays in Core."""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.application.chat.dtos.chat_dto import ChatRequestDto
from src.core.services.chat.chat_identity_service import ChatIdentityService
from src.core.services.chat.chat_service import ChatService
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

        @router.post(
            "/stream",
            summary="Stream one stateless answer from the local model",
            response_class=StreamingResponse,
            responses={
                200: {
                    "description": "SSE: message_start, delta*, message_end; on failure: error, message_end",
                    "content": {"text/event-stream": {"schema": {"type": "string"}}},
                },
                401: {"description": "Untrusted identity"},
                403: {"description": "Untrusted audience claim"},
                409: {"description": "Conversation persistence not available until stage 4"},
                422: {"description": "Invalid request"},
            },
        )
        async def stream_chat_async(payload: ChatRequestDto, request: Request):
            request_id = uuid4()
            headers = {"X-Request-ID": str(request_id)}
            if self._identity.authenticate(request.headers.get("authorization")) is None:
                return JSONResponse(
                    status_code=401,
                    content={"error": {"code": "UNAUTHENTICATED", "message": "Valid identity required.",
                                       "request_id": str(request_id)}},
                    headers=headers,
                )
            if "x-audience" in request.headers or "x-user-id" in request.headers:
                return JSONResponse(
                    status_code=403,
                    content={"error": {"code": "UNTRUSTED_CLAIMS", "message": "Client identity claims are not accepted.",
                                       "request_id": str(request_id)}},
                    headers=headers,
                )
            if payload.conversation_id is not None:
                return JSONResponse(
                    status_code=409,
                    content={"error": {"code": "CONVERSATION_UNAVAILABLE",
                                       "message": "Conversation continuation requires persistent ownership checks.",
                                       "request_id": str(request_id)}},
                    headers=headers,
                )

            message_id = uuid4()

            async def stream_events_async():
                iterator = self._chat_service.stream_async(payload.message, request_id, message_id)
                try:
                    async for event in iterator:
                        if await request.is_disconnected():
                            break
                        yield encode_sse(event.name, event.payload)
                finally:
                    await iterator.aclose()

            return StreamingResponse(
                stream_events_async(),
                media_type="text/event-stream",
                headers={**headers, "Cache-Control": "no-cache, no-transform",
                         "X-Accel-Buffering": "no"},
            )

        return router
