"""scope idempotency keys to the requesting principal

Revision ID: 20261023_0003
Revises: 20261012_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261023_0003"
down_revision: str | None = "20261012_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("builds") as batch:
        batch.drop_constraint("uq_builds_idempotency_key", type_="unique")
        batch.create_unique_constraint(
            "uq_builds_owner_idempotency_key", ["requested_by", "idempotency_key"]
        )


def downgrade() -> None:
    # The old schema allowed only one row for a key. If different principals reused a key after this
    # migration, retain the oldest row's key and clear the others so rollback remains possible.
    connection = op.get_bind()
    builds = sa.table(
        "builds",
        sa.column("id", sa.Uuid()),
        sa.column("requested_by", sa.String()),
        sa.column("idempotency_key", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    duplicate_keys = connection.execute(
        sa.select(builds.c.idempotency_key)
        .where(builds.c.idempotency_key.is_not(None))
        .group_by(builds.c.idempotency_key)
        .having(sa.func.count() > 1)
    ).scalars()
    for key in duplicate_keys:
        rows = connection.execute(
            sa.select(builds.c.id)
            .where(builds.c.idempotency_key == key)
            .order_by(builds.c.created_at, builds.c.id)
        ).scalars()
        for build_id in list(rows)[1:]:
            connection.execute(
                builds.update().where(builds.c.id == build_id).values(idempotency_key=None)
            )
    with op.batch_alter_table("builds") as batch:
        batch.drop_constraint("uq_builds_owner_idempotency_key", type_="unique")
        batch.create_unique_constraint("uq_builds_idempotency_key", ["idempotency_key"])
