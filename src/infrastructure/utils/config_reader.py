"""Read environment-specific non-secret appsettings and explicit environment overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from src.infrastructure.di.inject import inject


_ENV_OVERRIDES = {
    "database.url": "CHATBOT_DATABASE_URL",
    "vector.url": "CHATBOT_QDRANT_URL",
    "storage.path": "CHATBOT_STORAGE_PATH",
    "vector.api_key": "CHATBOT_QDRANT_API_KEY",
    "embedding.base_url": "CHATBOT_EMBEDDING_BASE_URL",
    "embedding.api_key": "CHATBOT_EMBEDDING_API_KEY",
    "reranking.base_url": "CHATBOT_RERANKING_BASE_URL",
    "reranking.api_key": "CHATBOT_RERANKING_API_KEY",
    "llm.base_url": "CHATBOT_LLM_BASE_URL",
    "llm.api_key": "CHATBOT_LLM_API_KEY",
    "llm.timeout_seconds": "CHATBOT_LLM_TIMEOUT_SECONDS",
    "auth.dev_api_token": "CHATBOT_DEV_API_TOKEN",
}


@inject
class ConfigReader:
    __di_singleton__ = True

    def __init__(self) -> None:
        env_type = os.getenv("ENV_TYPE", "production").lower()
        filename = "appsettings.development.yaml" if env_type == "development" else "appsettings.yaml"
        config_path = Path(__file__).resolve().parents[2] / "host" / "res" / filename
        with config_path.open("r", encoding="utf-8") as settings:
            data = yaml.safe_load(settings)
        if not isinstance(data, dict):
            raise ValueError(f"Configuration must be a mapping: {config_path}")
        self._data = data

    def get(self, key: str, default: Any = None) -> Any:
        override = _ENV_OVERRIDES.get(key)
        if override is not None and override in os.environ:
            return os.environ[override]
        value: Any = self._data
        for component in key.split("."):
            if not isinstance(value, dict) or component not in value:
                return default
            value = value[component]
        return value

    def get_api_prefix(self) -> str:
        prefix = self.get("api.prefix")
        if not isinstance(prefix, str) or not prefix.startswith("/") or prefix.endswith("/"):
            raise ValueError("api.prefix must start with '/' and have no trailing slash")
        return prefix
