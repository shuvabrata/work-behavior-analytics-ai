"""drop connectors enabled

Revision ID: d4e5f6a7b8c9
Revises: 04d7fde989ed
Create Date: 2026-11-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = '04d7fde989ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the unused ``connectors.enabled`` column."""
    op.drop_column('connectors', 'enabled')


def downgrade() -> None:
    """Restore the ``connectors.enabled`` column."""
    op.add_column(
        'connectors',
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('connectors', 'enabled', server_default=None)
