"""Read environment-specific non-secret appsettings and environment overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from src.infrastructure.di.inject import inject


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
        if key == "database.url" and "CHATBOT_DATABASE_URL" in os.environ:
            return os.environ["CHATBOT_DATABASE_URL"]
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
