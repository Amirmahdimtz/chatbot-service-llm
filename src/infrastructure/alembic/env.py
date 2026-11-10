"""Alembic online/offline migrations with SQLAlchemy async engine."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.infrastructure.alembic.model_discovery import load_models
from src.infrastructure.context.sql_db.psql_dbcontext import Base
from src.infrastructure.utils.config_reader import ConfigReader

config = context.config
load_models()
target_metadata = Base.metadata


def database_url() -> str:
    url = ConfigReader().get("database.url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Database URL is not configured; set CHATBOT_DATABASE_URL")
    return url


def run_migrations_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    options = config.get_section(config.config_ini_section) or {}
    options["sqlalchemy.url"] = database_url()
    connectable = async_engine_from_config(options, prefix="sqlalchemy.", poolclass=pool.NullPool)
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
