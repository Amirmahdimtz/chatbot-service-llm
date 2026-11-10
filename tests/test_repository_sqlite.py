"""Real asynchronous SQLAlchemy CRUD test using ephemeral SQLite (not PostgreSQL)."""

import pytest
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.context.sql_db.psql_dbcontext import Base, PsqlDbContext
from src.infrastructure.repositories.base.base_repository import BaseRepository


class SqliteItem(Base):
    __tablename__ = "stage1_sqlite_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class StubConfig:
    def get(self, key: str) -> str:
        assert key == "database.url"
        return "sqlite+aiosqlite:///:memory:"


@pytest.mark.asyncio
async def test_real_async_crud_and_session_isolation():
    pytest.importorskip("aiosqlite")
    context = PsqlDbContext(StubConfig())
    try:
        async with context.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        repository = BaseRepository(context, SqliteItem)
        created = await repository.insert_async(SqliteItem(name="initial"))
        assert created.id is not None
        another_id = await repository.insert_and_get_id_async(SqliteItem(name="second"))
        assert another_id != created.id
        assert len(await repository.get_all_async()) == 2
        fetched = await repository.get_by_id_async(created.id)
        assert fetched is not None and fetched.name == "initial"
        fetched.name = "changed"
        updated = await repository.update_async(fetched)
        assert updated.name == "changed"
        assert (await repository.get_by_id_async(created.id)).name == "changed"
        assert await repository.delete_async(created.id) is True
        assert await repository.delete_async(created.id) is False
        assert await repository.get_by_id_async(created.id) is None
        async with context.session() as session_one, context.session() as session_two:
            assert session_one is not session_two
    finally:
        await context.dispose_async()
