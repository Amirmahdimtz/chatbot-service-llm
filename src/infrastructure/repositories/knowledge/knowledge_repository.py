"""Owner-scoped metadata, atomic ingestion claims and retrieval visibility enforcement."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from sqlalchemy import and_, case, or_, select, update, func

from src.infrastructure.context.sql_db.psql_dbcontext import PsqlDbContext
from src.infrastructure.di.inject import inject
from src.infrastructure.models.knowledge_document import KnowledgeDocument
from src.infrastructure.repositories.base.base_repository import BaseRepository


@inject
class KnowledgeRepository(BaseRepository[KnowledgeDocument]):
    def __init__(self, db_context: PsqlDbContext):
        super().__init__(db_context, KnowledgeDocument)

    async def get_scoped_async(self, document_id: str, owner_id: str, audience: str) -> KnowledgeDocument | None:
        async with self._db_context.session() as session:
            return await session.scalar(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.id == document_id,
                    KnowledgeDocument.owner_id == owner_id,
                    KnowledgeDocument.audience == audience
                )
            )

    async def list_scoped_async(
        self, owner_id: str, audience: str, limit: int, offset: int, tenant_id: str | None = None
    ) -> tuple[list[KnowledgeDocument], bool]:
        async with self._db_context.session() as session:
            records = list((await session.scalars(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.owner_id == owner_id, KnowledgeDocument.audience == audience,
                    KnowledgeDocument.tenant_id == tenant_id
                ).order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id.desc())
                .limit(limit + 1).offset(offset)
            )).all())
        return records[:limit], len(records) > limit

    async def find_duplicate_async(
        self, owner: str, audience: str, checksum: str, exclude_id: str
    ) -> bool:
        async with self._db_context.session() as session:
            return (await session.scalar(select(KnowledgeDocument.id).where(
                KnowledgeDocument.owner_id == owner, KnowledgeDocument.audience == audience,
                KnowledgeDocument.checksum == checksum, KnowledgeDocument.status == "approved",
                KnowledgeDocument.id != exclude_id,
            ).limit(1))) is not None

    async def claim_processing_async(
        self, document_id: str, owner: str, audience: str, version: int, stale_minutes: int
    ) -> bool:
        expiry = datetime.now(UTC) - timedelta(minutes=stale_minutes)
        async with self._db_context.session() as session:
            result = await session.execute(
                update(KnowledgeDocument).where(
                    KnowledgeDocument.id == document_id,
                    KnowledgeDocument.owner_id == owner,
                    KnowledgeDocument.audience == audience,
                    KnowledgeDocument.version == version,
                    or_(KnowledgeDocument.processing_state.is_(False),
                        KnowledgeDocument.processing_started_at < expiry),
                ).values(
                    processing_state=True, processing_started_at=datetime.now(UTC),
                    status=case((KnowledgeDocument.status == 'approved', 'approved'), else_='processing'),
                    processing_error=None, updated_at=func.now(),
                )
            )
            if result.rowcount != 1:
                await session.rollback()
                return False
            await session.commit()
            return True

    async def mark_pending_async(self, document_id: str, storage_key: str, checksum: str) -> None:
        async with self._db_context.session() as session:
            await session.execute(update(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id, KnowledgeDocument.processing_state.is_(True),
            ).values(pending_storage_key=storage_key, pending_checksum=checksum,
                     updated_at=func.now()))
            await session.commit()

    async def complete_index_async(
        self, document_id: str, expected_version: int, new_version: int, storage_key: str,
        checksum: str, model_version: str, chunk_ids: list[str], extraction: dict,
    ) -> bool:
        async with self._db_context.session() as session:
            result = await session.execute(update(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id, KnowledgeDocument.version == expected_version,
                KnowledgeDocument.processing_state.is_(True),
            ).values(
                version=new_version, status="approved", storage_key=storage_key,
                checksum=checksum, embedding_model_version=model_version,
                chunk_ids=chunk_ids, extraction_metadata=extraction, processing_error=None,
                processing_state=False, processing_started_at=None,
                pending_storage_key=None, pending_checksum=None, updated_at=func.now(),
            ))
            if result.rowcount != 1:
                await session.rollback()
                return False
            await session.commit()
            return True

    async def mark_failed_async(self, document_id: str, code: str) -> None:
        async with self._db_context.session() as session:
            record = await session.get(KnowledgeDocument, document_id)
            if record is not None and record.processing_state:
                if record.status != "approved":
                    record.status = "failed"
                record.processing_state = False
                record.processing_started_at = None
                record.processing_error = code[:64]
                record.updated_at = datetime.now(UTC)
                await session.commit()

    async def publish_async(self, document_id: str, owner: str) -> bool:
        async with self._db_context.session() as session:
            result = await session.execute(update(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id, KnowledgeDocument.owner_id == owner,
                KnowledgeDocument.audience == "public", KnowledgeDocument.status == "approved",
                KnowledgeDocument.classification.is_(None),
            ).values(published=True, updated_at=func.now()))
            await session.commit()
            return result.rowcount == 1

    async def visible_async(self, document_ids: list[str], identity) -> dict[str, KnowledgeDocument]:
        if not document_ids:
            return {}
        clauses = [KnowledgeDocument.id.in_(document_ids), KnowledgeDocument.status == "approved"]
        if identity.audience == "public":
            clauses.extend([
                KnowledgeDocument.audience == "public",
                or_(KnowledgeDocument.published.is_(True),
                    and_(KnowledgeDocument.owner_id == identity.subject,
                         KnowledgeDocument.tenant_id == identity.tenant_id)),
            ])
        elif identity.audience == "internal":
            internal = [KnowledgeDocument.audience == "internal",
                        KnowledgeDocument.tenant_id == identity.tenant_id]
            if "knowledge:read_internal" not in identity.permissions:
                internal.append(KnowledgeDocument.owner_id == identity.subject)
            internal_filter = and_(*internal)
            if "knowledge:read_public" in identity.permissions:
                clauses.append(or_(internal_filter,
                    and_(KnowledgeDocument.audience == "public",
                         or_(KnowledgeDocument.published.is_(True),
                             and_(KnowledgeDocument.owner_id == identity.subject,
                                  KnowledgeDocument.tenant_id == identity.tenant_id)))))
            else:
                clauses.append(internal_filter)
        else:
            return {}
        async with self._db_context.session() as session:
            docs = list((await session.scalars(select(KnowledgeDocument).where(*clauses))).all())
            return {item.id: item for item in docs}
