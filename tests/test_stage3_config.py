"""Stage 3 configuration remains fail-closed and secrets stay local."""

from pathlib import Path

import yaml

from src.infrastructure.utils.config_reader import ConfigReader


ROOT = Path(__file__).resolve().parents[1]


def test_auth_defaults_and_resource_limits(monkeypatch):
    prod = yaml.safe_load((ROOT / "src/host/res/appsettings.yaml").read_text(encoding="utf-8"))
    dev = yaml.safe_load((ROOT / "src/host/res/appsettings.development.yaml").read_text(encoding="utf-8"))
    assert prod["auth"]["dev_enabled"] is False
    assert dev["auth"]["dev_enabled"] is True
    assert prod["llm"]["max_concurrent_requests"] == dev["llm"]["max_concurrent_requests"] == 1
    assert prod["llm"]["max_tokens"] == dev["llm"]["max_tokens"] == 256
    assert "dev_api_token" not in prod["auth"]
    assert "dev_api_token" not in dev["auth"]
    monkeypatch.setenv("ENV_TYPE", "development")
    monkeypatch.setenv("CHATBOT_DEV_API_TOKEN", "synthetic-not-real")
    assert ConfigReader().get("auth.dev_api_token") == "synthetic-not-real"


def test_compose_passes_separate_uncommitted_credential():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert compose["services"]["app"]["environment"]["CHATBOT_DEV_API_TOKEN"] == "${CHATBOT_DEV_API_TOKEN:-}"
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "CHATBOT_DEV_API_TOKEN=\n" in example
    assert "CHATBOT_DEV_API_TOKEN=secret" not in example
