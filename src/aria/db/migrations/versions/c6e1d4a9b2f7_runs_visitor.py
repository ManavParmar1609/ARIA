"""each visitor's own runs

Revision ID: c6e1d4a9b2f7
Revises: b3c1f0a9d2e4
Create Date: 2026-10-31 01:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6e1d4a9b2f7"
down_revision: str | None = "b3c1f0a9d2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Runs from before visitor scoping have no visitor: every visitor sees them as examples.
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("visitor", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_runs_visitor"), ["visitor"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_runs_visitor"))
        batch_op.drop_column("visitor")
