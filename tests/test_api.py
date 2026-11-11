"""Controller discovery smoke checks with the required Stage 4 database config."""
from fastapi.testclient import TestClient
import pytest
from src.application.web import WebService
from src.infrastructure.di.inject import install_providers
from src.infrastructure.di.reflection import discover_providers
from src.infrastructure.utils.config_reader import ConfigReader


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV_TYPE", "development")
    monkeypatch.setenv("CHATBOT_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'health.sqlite').as_posix()}")
    install_providers(discover_providers())
    return WebService(ConfigReader()).create_app()


def test_health_discovered_without_queries(app):
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "/api/v1/health" in app.openapi()["paths"]


def test_openapi_health_route(app):
    assert "/api/v1/health" in app.openapi()["paths"]
