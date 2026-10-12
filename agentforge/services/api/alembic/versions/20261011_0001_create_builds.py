"""create builds table

Revision ID: 20261011_0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261011_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "builds",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("agent_name", sa.String(length=80), nullable=False),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("current_stage", sa.String(length=80), nullable=True),
        sa.Column("stages", sa.JSON(), nullable=False),
        sa.Column("logs", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("artifact_path", sa.String(length=512), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_builds_status_created_at", "builds", ["status", "created_at"])
    op.create_index("ix_builds_agent_name", "builds", ["agent_name"])


def downgrade() -> None:
    op.drop_index("ix_builds_agent_name", table_name="builds")
    op.drop_index("ix_builds_status_created_at", table_name="builds")
    op.drop_table("builds")

