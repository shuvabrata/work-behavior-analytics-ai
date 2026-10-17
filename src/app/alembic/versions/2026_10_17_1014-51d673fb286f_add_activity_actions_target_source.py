"""add activity_actions target_source

Revision ID: 51d673fb286f
Revises: e636212b35b4
Create Date: 2026-10-17 10:14:08.650454

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '51d673fb286f'
down_revision: Union[str, Sequence[str], None] = 'e636212b35b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "activity_actions",
        sa.Column("target_source", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("activity_actions", "target_source")
