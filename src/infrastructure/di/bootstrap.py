"""Idempotent provider bootstrap, before WebService resolution."""

from threading import Lock

from src.infrastructure.di.inject import install_providers
from src.infrastructure.di.reflection import discover_providers

_bootstrap_lock = Lock()
_bootstrapped = False


def bootstrap_di() -> None:
    global _bootstrapped
    with _bootstrap_lock:
        if _bootstrapped:
            return
        providers = discover_providers()
        install_providers(providers)
        _bootstrapped = True
