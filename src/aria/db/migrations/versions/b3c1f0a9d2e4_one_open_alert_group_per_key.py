"""one open alert group per key

Revision ID: b3c1f0a9d2e4
Revises: 7257db204ce1
Create Date: 2026-10-30 07:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3c1f0a9d2e4"
down_revision: str | None = "7257db204ce1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPEN = sa.text("status = 'open'")
groups = sa.table(
    "alert_groups",
    sa.column("id", sa.String),
    sa.column("key", sa.String),
    sa.column("status", sa.String),
    sa.column("last_at", sa.DateTime),
)


def upgrade() -> None:
    # Racing deliveries could leave a key with several open groups: keep the latest open and close
    # the rest, so the index below can hold.
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(groups.c.id, groups.c.key)
        .where(groups.c.status == "open")
        .order_by(groups.c.key, groups.c.last_at.desc(), groups.c.id.desc())
    ).fetchall()
    seen: set[str] = set()
    for group_id, key in rows:
        if key in seen:
            bind.execute(sa.update(groups).where(groups.c.id == group_id).values(status="closed"))
        seen.add(key)
    op.create_index(
        "uq_alert_groups_open_key",
        "alert_groups",
        ["key"],
        unique=True,
        sqlite_where=OPEN,
        postgresql_where=OPEN,
        mssql_where=OPEN,
    )


def downgrade() -> None:
    op.drop_index("uq_alert_groups_open_key", table_name="alert_groups")
