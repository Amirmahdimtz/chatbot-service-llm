"""Committed Stage 8 migrations apply to a new disposable SQLite database."""
from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_stage8_sqlite_migration(monkeypatch, tmp_path):
    db_file = tmp_path / "stage8_migration.sqlite"
    monkeypatch.setenv("ENV_TYPE", "development")
    monkeypatch.setenv("CHATBOT_DATABASE_URL",
                       "sqlite+aiosqlite:///" + db_file.as_posix())
    cfg = Config("src/infrastructure/alembic/alembic.ini")
    command.upgrade(cfg, "head")
    engine = create_engine("sqlite:///" + db_file.as_posix())
    try:
        tables = inspect(engine).get_table_names()
        assert "scenario_records" in tables
        assert "chat_messages" in tables
        cols = {column["name"] for column in inspect(engine).get_columns("chat_messages")}
        assert "scenario_payload" in cols
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "20261115_04"
    finally:
        engine.dispose()
