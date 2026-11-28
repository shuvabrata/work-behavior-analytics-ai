"""drop_projects_table

Revision ID: b3f7c1a9d204
Revises: a7b8c9d0e1f2
Create Date: 2026-10-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f7c1a9d204'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the unused ``projects`` table backing the removed /api/v1/projects API."""
    op.drop_table('projects')


def downgrade() -> None:
    """Recreate the ``projects`` table."""
    op.create_table(
        'projects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=1023), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_projects')),
        sa.UniqueConstraint('name', name=op.f('uq_projects_name')),
    )
