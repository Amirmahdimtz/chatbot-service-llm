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
    if (not isinstance(identity, ChatIdentity) or not isinstance(identity.subject, str)
            or not identity.subject.strip() or identity.audience not in {"public", "internal"}):
        return api_error("FORBIDDEN", "Untrusted identity scope.", 403, request_id)
    if identity.audience == "internal":
        allowed_permissions = {"chat:use_internal", "knowledge:read_internal",
                               "knowledge:read_public", "knowledge:write", "knowledge:publish"}
        if (not isinstance(identity.tenant_id, str) or not identity.tenant_id.strip()
                or not (identity.permissions & allowed_permissions)):
            return api_error("FORBIDDEN", "Valid internal tenant and permissions required.", 403, request_id)
    return identity
