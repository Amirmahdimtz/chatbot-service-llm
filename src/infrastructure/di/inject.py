"""Convention-based constructor injection and provider lifetime management."""

from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
from inspect import Parameter, signature
from threading import RLock
from typing import Any, get_type_hints


class DependencyResolutionError(RuntimeError):
    """A dependency cannot be resolved safely."""


_providers: dict[type, type] = {}
_singletons: dict[type, object] = {}
_lock = RLock()
_resolution_stack: ContextVar[tuple[type, ...]] = ContextVar("di_stack", default=())


def inject(cls: type) -> type:
    """Mark a provider and inject only required, unsupplied constructor parameters."""
    cls.__di_provider__ = True
    original_init = cls.__init__
    if original_init is object.__init__:
        return cls

    parameters = signature(original_init)

    @wraps(original_init)
    def injected_init(self: object, *args: Any, **kwargs: Any) -> None:
        bound = parameters.bind_partial(self, *args, **kwargs)
        missing = [
            (name, parameter)
            for name, parameter in parameters.parameters.items()
            if name != "self"
            and name not in bound.arguments
            and parameter.default is Parameter.empty
            and parameter.kind in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY)
        ]
        if missing:
            try:
                hints = get_type_hints(original_init)
            except (NameError, TypeError) as exc:
                raise DependencyResolutionError(
                    f"Cannot evaluate constructor annotations for {cls.__name__}: {exc}"
                ) from exc
            for name, _ in missing:
                dependency = hints.get(name)
                if not isinstance(dependency, type):
                    raise DependencyResolutionError(
                        f"{cls.__name__}.{name} requires a resolvable type annotation"
                    )
                bound.arguments[name] = resolve(dependency)
        original_init(*bound.args, **bound.kwargs)

    cls.__init__ = injected_init
    return cls


def install_providers(classes: list[type]) -> None:
    """Atomically register discovered classes and their explicitly identifiable bases."""
    candidate: dict[type, type] = {}
    for cls in classes:
        if not cls.__dict__.get("__di_provider__", False):
            continue
        keys = [cls]
        for base in cls.__bases__:
            if base is not object and (base.__name__.startswith("I") or bool(getattr(base, "__abstractmethods__", False))):
                keys.append(base)
        for key in keys:
            if key in candidate and candidate[key] is not cls:
                raise DependencyResolutionError(f"Multiple providers for {key.__name__}")
            candidate[key] = cls
    with _lock:
        _providers.clear()
        _providers.update(candidate)
        _singletons.clear()


def resolve(dependency_type: type) -> Any:
    """Resolve a previously discovered provider; cache only declared singletons."""
    with _lock:
        implementation = _providers.get(dependency_type)
        if implementation is None:
            raise DependencyResolutionError(
                f"Provider for {dependency_type.__name__} not found; run bootstrap_di() first"
            )
        if getattr(implementation, "__di_singleton__", False) and implementation in _singletons:
            return _singletons[implementation]
        stack = _resolution_stack.get()
        if implementation in stack:
            chain = " -> ".join(item.__name__ for item in (*stack, implementation))
            raise DependencyResolutionError(f"Circular dependency: {chain}")
        token = _resolution_stack.set((*stack, implementation))
        try:
            instance = implementation()
            if getattr(implementation, "__di_singleton__", False):
                _singletons[implementation] = instance
            return instance
        finally:
            _resolution_stack.reset(token)
