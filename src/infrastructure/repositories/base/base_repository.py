"""Reusable async CRUD operations with an independent session per operation."""

from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import select

from src.infrastructure.context.sql_db.psql_dbcontext import Base, PsqlDbContext

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    def __init__(self, db_context: PsqlDbContext, model: type[ModelT]) -> None:
        self._db_context = db_context
        self._model = model

    async def insert_async(self, entity: ModelT) -> ModelT:
        async with self._db_context.session() as session:
            try:
                session.add(entity)
                await session.commit()
                await session.refresh(entity)
                return entity
            except Exception:
                await session.rollback()
                raise

    async def insert_and_get_id_async(self, entity: ModelT):
        saved = await self.insert_async(entity)
        return saved.id

    async def get_by_id_async(self, entity_id: object) -> ModelT | None:
        async with self._db_context.session() as session:
            return await session.get(self._model, entity_id)

    async def get_all_async(self) -> list[ModelT]:
        async with self._db_context.session() as session:
            return list((await session.scalars(select(self._model))).all())

    async def update_async(self, entity: ModelT) -> ModelT:
        async with self._db_context.session() as session:
            try:
                merged = await session.merge(entity)
                await session.commit()
                await session.refresh(merged)
                return merged
            except Exception:
                await session.rollback()
                raise

    async def delete_async(self, entity_id: object) -> bool:
        async with self._db_context.session() as session:
            try:
                entity = await session.get(self._model, entity_id)
                if entity is None:
                    return False
                await session.delete(entity)
                await session.commit()
                return True
            except Exception:
                await session.rollback()
                raise
