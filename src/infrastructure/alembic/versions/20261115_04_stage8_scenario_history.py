"""Stage 8: persist validated structured scenario results alongside assistant text.

Revision ID: 20261115_04
Revises: 20261115_03
"""
from alembic import op
import sqlalchemy as sa

revision = "20261115_04"
down_revision = "20261115_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("scenario_payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    # Only against disposable data; would lose saved scenario analyses.
    op.drop_column("chat_messages", "scenario_payload")
