import pytest

from src.application.web import WebService
from src.infrastructure.di.bootstrap import bootstrap_di
from src.infrastructure.di.inject import DependencyResolutionError, inject, resolve
from src.infrastructure.di.reflection import discover_providers
from src.infrastructure.utils.config_reader import ConfigReader
from src.infrastructure.context.sql_db.psql_dbcontext import PsqlDbContext


def test_provider_discovery_and_bootstrap():
    found = discover_providers()
    assert {WebService, ConfigReader, PsqlDbContext}.issubset(set(found))
    bootstrap_di()
    bootstrap_di()
    assert resolve(ConfigReader) is resolve(ConfigReader)
    assert resolve(WebService) is not resolve(WebService)


def test_caller_override_and_optional_parameter():
    @inject
    class DependencyConsumer:
        def __init__(self, reader: ConfigReader, optional: object = None):
            self.reader = reader
            self.optional = optional

    reader = object()
    instance = DependencyConsumer(reader)
    assert instance.reader is reader
    assert instance.optional is None
    assert DependencyConsumer(reader=reader, optional='supplied').optional == 'supplied'


def test_resolved_constructor_and_unregistered_dependency():
    bootstrap_di()
    assert isinstance(WebService()._config_reader, ConfigReader)
    with pytest.raises(DependencyResolutionError, match='not found'):
        resolve(str)


def test_bootstrap_reports_nonexistent_module(monkeypatch):
    import src.infrastructure.di.reflection as reflection
    original = reflection.importlib.import_module

    def fail_selected(name):
        if name == 'src.application.health.health_controller':
            raise ImportError('synthetic discovery failure')
        return original(name)

    monkeypatch.setattr(reflection.importlib, 'import_module', fail_selected)
    with pytest.raises(reflection.ProviderDiscoveryError, match='synthetic discovery failure'):
        reflection.discover_providers()
