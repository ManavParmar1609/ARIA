"""the decision record

Revision ID: e8f2a7c3d9b1
Revises: c6e1d4a9b2f7
Create Date: 2026-11-01 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import aria.db.types
from aria.db.models import append_only_ddl

revision: str = "e8f2a7c3d9b1"
down_revision: str | None = "c6e1d4a9b2f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Additive: a new table, with no link to runs, so a deleted or purged run leaves its
    # decisions on record. seq is the chain's position, chosen by the writer, not an identity.
    op.create_table(
        "decision_record",
        sa.Column("seq", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("ts", aria.db.types.UTCDateTime(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("seq"),
        sa.UniqueConstraint("hash", name="uq_decision_record_hash"),
    )
    with op.batch_alter_table("decision_record", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_decision_record_run_id"), ["run_id"], unique=False)
    # Append-only by the database's own rule: UPDATE and DELETE are refused by triggers, on
    # SQLite and on SQL Server (Azure SQL) alike.
    for statement in append_only_ddl(op.get_bind().dialect.name):
        op.execute(statement)


def downgrade() -> None:
    # Dropping the table drops its triggers with it, on both databases.
    with op.batch_alter_table("decision_record", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_decision_record_run_id"))
    op.drop_table("decision_record")
