"""Stage 4: durable conversations, messages, feedback and document metadata.

Revision ID: 20261111_01
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "20261111_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(200), nullable=False),
        sa.Column("audience", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200)),
        sa.Column("next_sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("audience IN ('public', 'internal')", name="ck_conversation_audience"),
    )
    op.create_index("ix_conversations_owner_activity", "conversations", ["owner_id", "audience", "updated_at", "id"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant', 'system', 'tool')", name="ck_chat_message_role"),
        sa.CheckConstraint("status IN ('streaming', 'completed', 'failed', 'cancelled')", name="ck_chat_message_status"),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_chat_message_order"),
    )
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])
    op.create_index("ix_chat_messages_conversation_created", "chat_messages", ["conversation_id", "created_at", "id"])
    op.create_table(
        "feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("chat_messages.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("kind IN ('positive', 'negative', 'incorrect')", name="ck_feedback_kind"),
        sa.UniqueConstraint("message_id", "actor_id", name="uq_feedback_actor_message"),
    )
    op.create_index("ix_feedback_message_id", "feedback", ["message_id"])
    op.create_index("ix_feedback_actor_created", "feedback", ["actor_id", "created_at"])
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(200), nullable=False),
        sa.Column("audience", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("category", sa.String(100)),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("classification", sa.String(100)),
        sa.Column("source_uri", sa.String(500)),
        sa.Column("storage_key", sa.String(500)),
        sa.Column("checksum", sa.String(64)),
        sa.Column("embedding_model_version", sa.String(100)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("audience IN ('public', 'internal')", name="ck_knowledge_audience"),
        sa.CheckConstraint("status IN ('registered', 'processing', 'failed', 'approved')", name="ck_knowledge_status"),
        sa.CheckConstraint("version >= 1", name="ck_knowledge_version"),
    )
    op.create_index("ix_knowledge_owner_audience_created", "knowledge_documents", ["owner_id", "audience", "created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_owner_audience_created", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_index("ix_feedback_actor_created", table_name="feedback")
    op.drop_index("ix_feedback_message_id", table_name="feedback")
    op.drop_table("feedback")
    op.drop_index("ix_chat_messages_conversation_created", table_name="chat_messages")
    op.drop_index("ix_chat_messages_conversation_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_conversations_owner_activity", table_name="conversations")
    op.drop_table("conversations")
