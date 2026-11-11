"""One feedback record per actor and assistant message."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from src.infrastructure.context.sql_db.psql_dbcontext import Base


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("kind IN ('positive', 'negative', 'incorrect')", name="ck_feedback_kind"),
        UniqueConstraint("message_id", "actor_id", name="uq_feedback_actor_message"),
        Index("ix_feedback_actor_created", "actor_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_messages.id", ondelete="RESTRICT"), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
