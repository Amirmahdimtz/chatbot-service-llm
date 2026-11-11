"""Fail-closed identity boundary: only synthetic public access in development."""
from __future__ import annotations

from dataclasses import dataclass, field
import hmac
import os

from src.infrastructure.di.inject import inject
from src.infrastructure.utils.config_reader import ConfigReader


@dataclass(frozen=True)
class ChatIdentity:
    subject: str
    audience: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    tenant_id: str | None = None


@inject
class ChatIdentityService:
    def __init__(self, config_reader: ConfigReader) -> None:
        self._config_reader = config_reader

    def authenticate(self, authorization: str | None) -> ChatIdentity | None:
        if os.getenv("ENV_TYPE", "production").lower() != "development":
            return None
        if self._config_reader.get("auth.dev_enabled") is not True:
            return None
        expected = self._config_reader.get("auth.dev_api_token", "")
        if not isinstance(expected, str) or len(expected) < 32:
            return None
        if not isinstance(authorization, str):
            return None
        scheme, separator, presented = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not presented:
            return None
        if not hmac.compare_digest(presented, expected):
            return None
        return ChatIdentity(subject="synthetic-development-public", audience="public",
                            permissions=frozenset({"knowledge:write"}))
