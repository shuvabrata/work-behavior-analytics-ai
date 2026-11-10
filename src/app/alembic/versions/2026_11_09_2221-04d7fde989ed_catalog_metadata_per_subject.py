"""catalog metadata per subject

Revision ID: 04d7fde989ed
Revises: fc1b240aeecb
Create Date: 2026-11-09 22:21:27.666237

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '04d7fde989ed'
down_revision: Union[str, Sequence[str], None] = 'fc1b240aeecb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Scope catalog favourites to their owner."""
    op.drop_constraint("uq_catalog_metadata_catalog_id", "catalog_metadata", type_="unique")
    # Existing rows predate ownership and have no real owner; drop them so the
    # non-null column can be added.
    op.execute("DELETE FROM catalog_metadata")
    op.add_column("catalog_metadata", sa.Column("subject", sa.String(length=255), nullable=False))
    op.create_index("ix_catalog_metadata_subject", "catalog_metadata", ["subject"])
    op.create_unique_constraint(
        "uq_catalog_metadata_catalog_subject", "catalog_metadata", ["catalog_id", "subject"]
    )


def downgrade() -> None:
    """Revert to a single global favourite per catalog query.

    Per-user rows cannot be collapsed back into one global row, so the table is
    emptied before the global unique constraint is restored — recreating it over
    duplicate catalog_ids fails.
    """
    op.drop_constraint("uq_catalog_metadata_catalog_subject", "catalog_metadata", type_="unique")
    op.drop_index("ix_catalog_metadata_subject", table_name="catalog_metadata")
    op.drop_column("catalog_metadata", "subject")
    op.execute("DELETE FROM catalog_metadata")
    op.create_unique_constraint(
        "uq_catalog_metadata_catalog_id", "catalog_metadata", ["catalog_id"]
    )
