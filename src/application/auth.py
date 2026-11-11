"""Shared HTTP identity validation; client-supplied claims never grant access."""
from __future__ import annotations

from uuid import UUID, uuid4
from fastapi import Request
from fastapi.responses import JSONResponse
from src.core.services.chat.chat_identity_service import ChatIdentity, ChatIdentityService


def api_error(code: str, message: str, status: int, request_id: UUID | None = None) -> JSONResponse:
    request_id = request_id or uuid4()
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "request_id": str(request_id)}},
        headers={"X-Request-ID": str(request_id)},
    )


def authenticate_request(
    request: Request, identity_service: ChatIdentityService, request_id: UUID
) -> ChatIdentity | JSONResponse:
    identity = identity_service.authenticate(request.headers.get("authorization"))
    if identity is None:
        return api_error("UNAUTHENTICATED", "Valid identity required.", 401, request_id)
    if any(key in request.headers for key in ("x-audience", "x-user-id", "x-tenant-id")):
        return api_error("UNTRUSTED_CLAIMS", "Client identity claims are not accepted.", 403, request_id)
    return identity
