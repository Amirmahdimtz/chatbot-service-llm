"""Tenant-scoped, versioned scenario records; data shape is validated before persistence."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.context.sql_db.psql_dbcontext import Base


class ScenarioRecord(Base):
    __tablename__ = "scenario_records"
    __table_args__ = (
        CheckConstraint("audience IN ('public', 'internal')", name="ck_scenario_record_audience"),
        CheckConstraint("version >= 1", name="ck_scenario_record_version"),
        UniqueConstraint("audience", "tenant_key", "kind", "external_key", name="uq_scenario_record_scope_key"),
        Index("ix_scenario_record_scope_kind", "audience", "tenant_key", "kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    tenant_key: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    owner_id: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    external_key: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
