"""Stage 2 configuration keeps secrets out of committed defaults."""

from src.infrastructure.utils.config_reader import ConfigReader


def test_development_infrastructure_settings(monkeypatch):
    monkeypatch.setenv("ENV_TYPE", "development")
    for name in ("CHATBOT_DATABASE_URL", "CHATBOT_LLM_BASE_URL", "CHATBOT_QDRANT_URL", "CHATBOT_STORAGE_PATH"):
        monkeypatch.delenv(name, raising=False)
    settings = ConfigReader()
    assert settings.get("vector.url") == "http://127.0.0.1:6333"
    assert settings.get("vector.public_collection") == "knowledge_public"
    assert settings.get("vector.internal_collection") == "knowledge_internal"
    assert settings.get("llm.base_url") == "http://127.0.0.1:8080"
    assert settings.get("storage.path") == "storage"


def test_environment_overrides_without_database_secret_in_yaml(monkeypatch):
    monkeypatch.setenv("ENV_TYPE", "production")
    monkeypatch.setenv("CHATBOT_QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("CHATBOT_LLM_BASE_URL", "http://host.docker.internal:8080")
    monkeypatch.setenv("CHATBOT_LLM_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("CHATBOT_STORAGE_PATH", "/app/storage")
    monkeypatch.setenv("CHATBOT_LLM_TIMEOUT_SECONDS", "25")
    settings = ConfigReader()
    assert settings.get("database.url") == ""
    assert settings.get("vector.url") == "http://qdrant:6333"
    assert settings.get("llm.base_url") == "http://host.docker.internal:8080"
    assert settings.get("llm.api_key") == "synthetic-test-key"
    assert settings.get("llm.timeout_seconds") == "25"
    assert settings.get("storage.path") == "/app/storage"


def test_production_external_endpoints_fail_closed_without_overrides(monkeypatch):
    monkeypatch.setenv("ENV_TYPE", "production")
    for key in ("CHATBOT_QDRANT_URL", "CHATBOT_LLM_BASE_URL", "CHATBOT_DATABASE_URL"):
        monkeypatch.delenv(key, raising=False)
    config = ConfigReader()
    assert config.get("vector.url") == ""
    assert config.get("llm.base_url") == ""
    assert config.get("database.url") == ""
