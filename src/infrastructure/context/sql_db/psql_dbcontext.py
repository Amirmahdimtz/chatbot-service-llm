"""Shared SQLAlchemy async engine and session factory, never a shared session."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.infrastructure.di.inject import inject
from src.infrastructure.utils.config_reader import ConfigReader


class Base(DeclarativeBase):
    pass


@inject
class PsqlDbContext:
    __di_singleton__ = True

    def __init__(self, config_reader: ConfigReader) -> None:
        url = config_reader.get("database.url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("Database URL is not configured; set CHATBOT_DATABASE_URL")
        self._engine = create_async_engine(url, pool_pre_ping=True)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    @property
    def engine(self):
        return self._engine

    def session(self) -> AsyncSession:
        return self._session_factory()

    async def dispose_async(self) -> None:
        await self._engine.dispose()
