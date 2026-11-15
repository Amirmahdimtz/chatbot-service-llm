"""Stage 8: additive tenant-isolated structured scenario storage.

Revision ID: 20261115_03
Revises: 20261111_02
"""
from alembic import op
import sqlalchemy as sa

revision = "20261115_03"
down_revision = "20261111_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scenario_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("audience", sa.String(16), nullable=False),
        sa.Column("tenant_key", sa.String(200), nullable=False),
        sa.Column("owner_id", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("external_key", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("audience IN ('public', 'internal')", name="ck_scenario_record_audience"),
        sa.CheckConstraint("version >= 1", name="ck_scenario_record_version"),
        sa.UniqueConstraint("audience", "tenant_key", "kind", "external_key", name="uq_scenario_record_scope_key"),
    )
    op.create_index("ix_scenario_record_scope_kind", "scenario_records", ["audience", "tenant_key", "kind"])


def downgrade() -> None:
    # Destructive rollback: never run against retained organizational records.
    op.drop_index("ix_scenario_record_scope_kind", table_name="scenario_records")
    op.drop_table("scenario_records")
