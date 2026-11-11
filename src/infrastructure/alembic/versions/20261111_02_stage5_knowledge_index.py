"""Stage 5: additive document indexing, publication and recovery metadata.

Revision ID: 20261111_02
Revises: 20261111_01
"""
from alembic import op
import sqlalchemy as sa

revision = "20261111_02"
down_revision = "20261111_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_documents", sa.Column("tenant_id", sa.String(200), nullable=True))
    op.add_column("knowledge_documents", sa.Column("extraction_metadata", sa.JSON(), nullable=True))
    op.add_column("knowledge_documents", sa.Column("chunk_ids", sa.JSON(), nullable=True))
    op.add_column("knowledge_documents", sa.Column("published", sa.Boolean(), nullable=False,
                                                    server_default=sa.false()))
    op.add_column("knowledge_documents", sa.Column("processing_state", sa.Boolean(), nullable=False,
                                                    server_default=sa.false()))
    op.add_column("knowledge_documents", sa.Column("processing_started_at", sa.DateTime(timezone=True)))
    op.add_column("knowledge_documents", sa.Column("processing_error", sa.String(64)))
    op.add_column("knowledge_documents", sa.Column("pending_storage_key", sa.String(500)))
    op.add_column("knowledge_documents", sa.Column("pending_checksum", sa.String(64)))
    op.create_index("ix_knowledge_checksum_scope", "knowledge_documents",
                    ["owner_id", "audience", "checksum"], unique=True)


def downgrade() -> None:
    # Only on explicitly disposable test databases; never on existing data.
    op.drop_index("ix_knowledge_checksum_scope", table_name="knowledge_documents")
    for name in ("pending_checksum", "pending_storage_key", "processing_error", "processing_started_at",
                 "processing_state", "published", "chunk_ids", "extraction_metadata", "tenant_id"):
        op.drop_column("knowledge_documents", name)
