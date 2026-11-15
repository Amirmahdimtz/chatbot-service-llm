"""Scope-constrained reads and atomic upserts for structured scenario records."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.infrastructure.context.sql_db.psql_dbcontext import PsqlDbContext
from src.infrastructure.di.inject import inject
from src.infrastructure.models.scenario_record import ScenarioRecord
from src.infrastructure.repositories.base.base_repository import BaseRepository


@inject
class ScenarioRepository(BaseRepository[ScenarioRecord]):
    def __init__(self, db_context: PsqlDbContext):
        super().__init__(db_context, ScenarioRecord)

    async def list_scoped_async(self, audience: str, tenant_key: str, kind: str,
                                limit: int = 200) -> list[ScenarioRecord]:
        async with self._db_context.session() as session:
            return list((await session.scalars(
                select(ScenarioRecord).where(
                    ScenarioRecord.audience == audience,
                    ScenarioRecord.tenant_key == tenant_key,
                    ScenarioRecord.kind == kind,
                ).order_by(ScenarioRecord.external_key).limit(limit)
            )).all())

    async def get_scoped_async(self, audience: str, tenant_key: str, kind: str,
                               key: str) -> ScenarioRecord | None:
        async with self._db_context.session() as session:
            return await session.scalar(select(ScenarioRecord).where(
                ScenarioRecord.audience == audience,
                ScenarioRecord.tenant_key == tenant_key,
                ScenarioRecord.kind == kind,
                ScenarioRecord.external_key == key,
            ))

    async def upsert_scoped_async(self, audience: str, tenant_key: str, owner_id: str,
                                  kind: str, key: str, payload: dict,
                                  verified: bool = False) -> ScenarioRecord:
        # Serializes writers for an existing record and never searches across tenants.
        async with self._db_context.session() as session:
            async with session.begin():
                record = await session.scalar(select(ScenarioRecord).where(
                    ScenarioRecord.audience == audience,
                    ScenarioRecord.tenant_key == tenant_key,
                    ScenarioRecord.kind == kind,
                    ScenarioRecord.external_key == key,
                ).with_for_update())
                if record is None:
                    record = ScenarioRecord(
                        audience=audience, tenant_key=tenant_key, owner_id=owner_id,
                        kind=kind, external_key=key, payload=payload, verified=verified,
                    )
                    session.add(record)
                else:
                    record.payload = payload
                    record.verified = verified
                    record.version += 1
                await session.flush()
            await session.refresh(record)
            return record

    async def register_pending_async(self, audience: str, tenant_key: str, owner_id: str,
                                     key: str, payload: dict) -> None:
        # A repeated unanswered question is idempotent, even with concurrent requests.
        async with self._db_context.session() as session:
            try:
                async with session.begin():
                    existing = await session.scalar(select(ScenarioRecord.id).where(
                        ScenarioRecord.audience == audience,
                        ScenarioRecord.tenant_key == tenant_key,
                        ScenarioRecord.kind == "faq_pending",
                        ScenarioRecord.external_key == key,
                    ))
                    if existing is None:
                        session.add(ScenarioRecord(
                            audience=audience, tenant_key=tenant_key, owner_id=owner_id,
                            kind="faq_pending", external_key=key, payload=payload,
                        ))
            except IntegrityError:
                pass
