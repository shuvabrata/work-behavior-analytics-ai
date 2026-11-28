"""add scheduler_lease table and scan_interval_hours to connectors

Revision ID: 1a2b3c4d5e6f
Revises: 0c1d2e3f4a5b
Create Date: 2026-09-14 21:00:00.000000

Adds two schema changes required by the per-connector scan scheduler (Plan 020):

1. ``connectors.scan_interval_hours`` (INTEGER, nullable) — stores the
   per-connector scheduled scan interval in hours.  NULL means no schedule
   (manual-only); any integer >= 1 enables automatic scanning at that cadence.

2. ``scheduler_lease`` table — single-row distributed leader-election table.
   The scheduler loop in each app instance races to claim/renew this row on
   every tick.  The instance that wins the UPDATE runs the scheduler; all
   others skip the tick.  A single seed row is inserted with ``expires_at``
   set to the Unix epoch so the first instance to start always wins the
   initial lease.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = "0c1d2e3f4a5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add scan_interval_hours column to connectors table.
    op.add_column(
        "connectors",
        sa.Column("scan_interval_hours", sa.Integer(), nullable=True),
    )

    # 2. Create the scheduler_lease table.
    op.create_table(
        "scheduler_lease",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("held_by", sa.String(length=64), nullable=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduler_lease")),
    )

    # 3. Seed the single lease row with an already-expired timestamp so that
    #    the very first app instance to start can immediately claim the lease
    #    without needing a special bootstrap path.
    op.execute(
        "INSERT INTO scheduler_lease (held_by, expires_at) "
        "VALUES (NULL, '1970-01-01 00:00:00+00')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("scheduler_lease")
    op.drop_column("connectors", "scan_interval_hours")
