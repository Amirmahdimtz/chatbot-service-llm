"""Alembic upgrade/downgrade on an isolated temporary DB, never on real data."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_isolated_alembic_upgrade_and_downgrade(tmp_path, monkeypatch):
    db = tmp_path / "alembic.sqlite"
    url = f"sqlite+aiosqlite:///{db.as_posix()}"
    monkeypatch.setenv("ENV_TYPE", "development")
    monkeypatch.setenv("CHATBOT_DATABASE_URL", url)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "src/infrastructure/alembic/alembic.ini"))
    command.upgrade(config, "head")
    sync_engine = create_engine(f"sqlite:///{db.as_posix()}")
    try:
        tables = set(inspect(sync_engine).get_table_names())
        assert {"conversations", "chat_messages", "feedback", "knowledge_documents"} <= tables
        assert "alembic_version" in tables
    finally:
        sync_engine.dispose()
    # Destructive rollback is permitted ONLY on the temporary isolated fixture database.
    command.downgrade(config, "base")
    sync_engine = create_engine(f"sqlite:///{db.as_posix()}")
    try:
        assert "conversations" not in inspect(sync_engine).get_table_names()
    finally:
        sync_engine.dispose()
