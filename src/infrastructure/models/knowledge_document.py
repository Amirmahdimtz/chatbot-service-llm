"""Document metadata, indexing lifecycle and publication state."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column
from src.infrastructure.context.sql_db.psql_dbcontext import Base


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint("audience IN ('public', 'internal')", name="ck_knowledge_audience"),
        CheckConstraint("status IN ('registered', 'processing', 'failed', 'approved')", name="ck_knowledge_status"),
        CheckConstraint("version >= 1", name="ck_knowledge_version"),
        Index("ix_knowledge_owner_audience_created", "owner_id", "audience", "created_at", "id"),
        Index("ix_knowledge_checksum_scope", "owner_id", "audience", "checksum", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(200))
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="fa")
    classification: Mapped[str | None] = mapped_column(String(100))
    source_uri: Mapped[str | None] = mapped_column(String(500))
    storage_key: Mapped[str | None] = mapped_column(String(500))
    checksum: Mapped[str | None] = mapped_column(String(64))
    embedding_model_version: Mapped[str | None] = mapped_column(String(100))
    extraction_metadata: Mapped[dict | None] = mapped_column(JSON)
    chunk_ids: Mapped[list | None] = mapped_column(JSON)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    processing_state: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_error: Mapped[str | None] = mapped_column(String(64))
    pending_storage_key: Mapped[str | None] = mapped_column(String(500))
    pending_checksum: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="registered")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
