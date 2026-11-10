"""Discover @inject providers without per-component registrations."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path


class ProviderDiscoveryError(RuntimeError):
    """A provider module could not be inspected or imported."""


_EXCLUDED = {"di", "dtos", "models", "scripts", "alembic", "versions", "res", "sso"}


def discover_providers() -> list[type]:
    src_root = Path(__file__).resolve().parents[2]
    providers: list[type] = []
    for layer in ("infrastructure", "core", "application"):
        for file in sorted((src_root / layer).rglob("*.py")):
            if file.name == "__init__.py" or any(part in _EXCLUDED for part in file.relative_to(src_root).parts):
                continue
            module_name = ".".join(file.relative_to(src_root.parent).with_suffix("").parts)
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:
                raise ProviderDiscoveryError(f"Failed importing {module_name}: {exc}") from exc
            providers.extend(
                cls
                for _, cls in inspect.getmembers(module, inspect.isclass)
                if cls.__module__ == module_name and cls.__dict__.get("__di_provider__", False)
            )
    return providers
