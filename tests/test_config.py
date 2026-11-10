import pytest

from src.infrastructure.utils.config_reader import ConfigReader


def test_config_environments_and_override(monkeypatch):
    monkeypatch.setenv('ENV_TYPE', 'development')
    monkeypatch.delenv('CHATBOT_DATABASE_URL', raising=False)
    config = ConfigReader()
    assert config.get('app.name') == 'Chatbot Service (Development)'
    assert config.get_api_prefix() == '/api/v1'
    assert config.get('no.such.key', 'fallback') == 'fallback'
    assert config.get('database.url') == ''
    monkeypatch.setenv('CHATBOT_DATABASE_URL', 'postgresql+asyncpg://example.invalid/dev')
    assert config.get('database.url') == 'postgresql+asyncpg://example.invalid/dev'


def test_no_credentials_by_default(monkeypatch):
    monkeypatch.delenv('CHATBOT_DATABASE_URL', raising=False)
    monkeypatch.setenv('ENV_TYPE', 'production')
    config = ConfigReader()
    assert config.get('database.url') == ''
    assert config.get_api_prefix() == '/api/v1'
