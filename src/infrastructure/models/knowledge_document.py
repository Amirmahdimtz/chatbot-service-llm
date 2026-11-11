"""Document registration metadata only; no ingestion or index is implied."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from src.infrastructure.context.sql_db.psql_dbcontext import Base


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint("audience IN ('public', 'internal')", name="ck_knowledge_audience"),
        CheckConstraint("status IN ('registered', 'processing', 'failed', 'approved')", name="ck_knowledge_status"),
        CheckConstraint("version >= 1", name="ck_knowledge_version"),
        Index("ix_knowledge_owner_audience_created", "owner_id", "audience", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str] = mapped_column(String(200), nullable=False)
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
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="registered")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
