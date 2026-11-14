"""Deterministic scenario selection independent of untrusted prompt content."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.core.services.chat.chat_identity_service import ChatIdentity
from src.core.services.errors import PermissionDenied
from src.infrastructure.di.inject import inject


@dataclass(frozen=True)
class ScenarioRoute:
    scenario: str
    path: Literal["direct_llm", "rag"]


@inject
class ScenarioRouterService:
    """Only general chat and knowledge QA are active in Stage 6.

    Future scenario implementations can register explicit routes here without
    relying on text heuristics or accepting caller-supplied authorization scope.
    """

    _ROUTES: dict[str, Literal["direct_llm", "rag"]] = {
        "general": "direct_llm",
        "knowledge_qa": "rag",
    }

    def route(self, scenario: str | None, identity: ChatIdentity) -> ScenarioRoute:
        if not isinstance(identity, ChatIdentity) or not identity.subject.strip():
            raise PermissionDenied("A trusted identity is required")
        if identity.audience not in {"public", "internal"}:
            raise PermissionDenied("Invalid audience")
        if identity.audience == "internal":
            if not identity.tenant_id or not identity.tenant_id.strip():
                raise PermissionDenied("Internal identity requires a tenant")
            if not ({"chat:use_internal", "knowledge:read_internal"} & identity.permissions):
                raise PermissionDenied("Internal access requires a permission")
        selected = "general" if scenario is None else scenario
        path = self._ROUTES.get(selected)
        if path is None:
            raise ValueError("Unsupported scenario")
        if path == "rag" and identity.audience == "internal" and "knowledge:read_internal" not in identity.permissions:
            raise PermissionDenied("Internal knowledge access requires permission")
        return ScenarioRoute(selected, path)
