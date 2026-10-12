"""build events, reports and lifecycle columns

Moves the JSON ``logs`` array into an append-only ``build_events`` table and adds the columns
needed for cancellation, retries, idempotency, artifact integrity and build reports.

Revision ID: 20261012_0002
Revises: 20261011_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261012_0002"
down_revision: str | None = "20261011_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "build_events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("build_id", sa.Uuid(), sa.ForeignKey("builds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False, server_default="info"),
        sa.Column("stage", sa.String(length=40), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
    )
    op.create_index("ix_build_events_build_id_id", "build_events", ["build_id", "id"])

    with op.batch_alter_table("builds") as batch:
        batch.add_column(sa.Column("report", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("artifact_sha256", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("artifact_size", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("requested_by", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("parent_build_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("task_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("agentforge_version", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_unique_constraint("uq_builds_idempotency_key", ["idempotency_key"])
        batch.create_foreign_key("fk_builds_parent", "builds", ["parent_build_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_builds_created_at", ["created_at"])

    connection = op.get_bind()
    builds = sa.table("builds", sa.column("id", sa.Uuid()), sa.column("logs", sa.JSON()), sa.column("created_at", sa.DateTime(timezone=True)))
    events = sa.table(
        "build_events",
        sa.column("build_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("level", sa.String()),
        sa.column("stage", sa.String()),
        sa.column("message", sa.Text()),
    )
    rows = connection.execute(sa.select(builds.c.id, builds.c.logs, builds.c.created_at)).all()
    for build_id, logs, created_at in rows:
        for line in logs or []:
            connection.execute(
                events.insert().values(build_id=build_id, created_at=created_at, level="info", stage=None, message=str(line))
            )

    with op.batch_alter_table("builds") as batch:
        batch.drop_column("logs")


def downgrade() -> None:
    with op.batch_alter_table("builds") as batch:
        batch.add_column(sa.Column("logs", sa.JSON(), nullable=True))
    connection = op.get_bind()
    builds = sa.table("builds", sa.column("id", sa.Uuid()), sa.column("logs", sa.JSON()))
    events = sa.table("build_events", sa.column("id", sa.BigInteger()), sa.column("build_id", sa.Uuid()), sa.column("message", sa.Text()))
    for (build_id,) in connection.execute(sa.select(builds.c.id)).all():
        messages = [
            row.message
            for row in connection.execute(
                sa.select(events.c.message).where(events.c.build_id == build_id).order_by(events.c.id)
            )
        ]
        connection.execute(builds.update().where(builds.c.id == build_id).values(logs=messages[-250:]))
    with op.batch_alter_table("builds") as batch:
        batch.alter_column("logs", nullable=False, existing_type=sa.JSON())
        batch.drop_index("ix_builds_created_at")
        batch.drop_constraint("fk_builds_parent", type_="foreignkey")
        batch.drop_constraint("uq_builds_idempotency_key", type_="unique")
        for column in (
            "finished_at", "started_at", "agentforge_version", "task_id", "idempotency_key",
            "parent_build_id", "attempt", "cancel_requested", "requested_by", "artifact_size",
            "artifact_sha256", "report",
        ):
            batch.drop_column(column)
    op.drop_index("ix_build_events_build_id_id", table_name="build_events")
    op.drop_table("build_events")
