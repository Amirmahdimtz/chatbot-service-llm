from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.context.sql_db import psql_dbcontext
from src.infrastructure.repositories.base.base_repository import BaseRepository
from src.infrastructure.context.sql_db.psql_dbcontext import Base
from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column


class FakeConfig:
    def __init__(self, url: str):
        self.url = url

    def get(self, key: str):
        assert key == 'database.url'
        return self.url


class FakeEntity(Base):
    __tablename__ = "test_entity"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    def __init__(self):
        self.id = 17


@pytest.mark.asyncio
async def test_dbcontext_one_engine_factory_and_distinct_sessions(monkeypatch):
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()
    fake_factory = MagicMock(side_effect=[object(), object()])
    mock_engine = MagicMock(return_value=fake_engine)
    mock_session_factory = MagicMock(return_value=fake_factory)
    monkeypatch.setattr(psql_dbcontext, 'create_async_engine', mock_engine)
    monkeypatch.setattr(psql_dbcontext, 'async_sessionmaker', mock_session_factory)
    ctx = psql_dbcontext.PsqlDbContext(FakeConfig('postgresql+asyncpg://localhost/fake'))
    assert ctx.engine is fake_engine
    assert ctx.session() is not ctx.session()
    mock_engine.assert_called_once_with('postgresql+asyncpg://localhost/fake', pool_pre_ping=True)
    mock_session_factory.assert_called_once_with(fake_engine, expire_on_commit=False)
    await ctx.dispose_async()
    fake_engine.dispose.assert_awaited_once()


def test_missing_database_configuration_is_explicit():
    with pytest.raises(ValueError, match='CHATBOT_DATABASE_URL'):
        psql_dbcontext.PsqlDbContext(FakeConfig(''))


def make_repo(session):
    context = MagicMock()
    context.session.return_value.__aenter__ = AsyncMock(return_value=session)
    context.session.return_value.__aexit__ = AsyncMock(return_value=None)
    return BaseRepository(context, FakeEntity), context


@pytest.mark.asyncio
async def test_base_repository_crud_contract_and_session_lifecycle():
    session = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    session.merge = AsyncMock(side_effect=lambda entity: entity)
    session.get = AsyncMock(return_value=FakeEntity())
    session.delete = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.all.return_value = [FakeEntity()]
    session.scalars = AsyncMock(return_value=scalar_result)
    repo, context = make_repo(session)
    inserted = FakeEntity()
    assert await repo.insert_async(inserted) is inserted
    assert await repo.insert_and_get_id_async(FakeEntity()) == 17
    assert isinstance(await repo.get_by_id_async(17), FakeEntity)
    assert len(await repo.get_all_async()) == 1
    assert await repo.update_async(FakeEntity()) is not None
    assert await repo.delete_async(17) is True
    session.get.return_value = None
    assert await repo.delete_async(999) is False
    assert context.session.call_count == 7
    assert session.commit.await_count == 4
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_repository_rolls_back_failed_write():
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock(side_effect=RuntimeError('write failed'))
    session.rollback = AsyncMock()
    repo, _ = make_repo(session)
    with pytest.raises(RuntimeError, match='write failed'):
        await repo.insert_async(FakeEntity())
    session.rollback.assert_awaited_once()
