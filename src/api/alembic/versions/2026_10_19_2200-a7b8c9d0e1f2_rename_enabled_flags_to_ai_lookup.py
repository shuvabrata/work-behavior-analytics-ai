"""rename enabled flags to ai_lookup_enabled

Revision ID: a7b8c9d0e1f2
Revises: 51d673fb286f
Create Date: 2026-10-19 22:02:00.000000

Both Neo4j and Elasticsearch are mandatory databases for this application.
The original NEO4J_ENABLED / ELASTICSEARCH_ENABLED flags were intended only
to control AI agent chain lookups. This migration renames them to make their
scope explicit, and updates the descriptions accordingly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = '51d673fb286f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEO4J_DESC = (
    "Controls whether the AI agent queries Neo4j for context enrichment during chat. "
    "When false, the Neo4j augmentation chain is skipped. "
    "Neo4j itself is always required for the application to function."
)

_ES_DESC = (
    "Controls whether the AI agent queries Elasticsearch for context enrichment during chat. "
    "When false, the Elasticsearch augmentation chain is skipped. "
    "Elasticsearch itself is always required for the application to function."
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE application_settings "
            "SET key = 'NEO4J_AI_LOOKUP_ENABLED', description = :desc "
            "WHERE key = 'NEO4J_ENABLED'"
        ).bindparams(desc=_NEO4J_DESC)
    )
    op.execute(
        sa.text(
            "UPDATE application_settings "
            "SET key = 'ELASTICSEARCH_AI_LOOKUP_ENABLED', description = :desc "
            "WHERE key = 'ELASTICSEARCH_ENABLED'"
        ).bindparams(desc=_ES_DESC)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE application_settings "
            "SET key = 'NEO4J_ENABLED', description = :desc "
            "WHERE key = 'NEO4J_AI_LOOKUP_ENABLED'"
        ).bindparams(
            desc=(
                "Turns the Neo4j graph database integration on or off. Neo4j powers the "
                "collaboration graph and relationship analytics, and is a core requirement "
                "of the application, so it is highly recommended to keep it ON. "
                "Turn it off only for debugging purposes."
            )
        )
    )
    op.execute(
        sa.text(
            "UPDATE application_settings "
            "SET key = 'ELASTICSEARCH_ENABLED', description = :desc "
            "WHERE key = 'ELASTICSEARCH_AI_LOOKUP_ENABLED'"
        ).bindparams(
            desc=(
                "Turns the Elasticsearch integration on or off. Elasticsearch powers search "
                "and log analytics across the app. It is enabled by default; disable it only "
                "if you're troubleshooting or running without Elasticsearch."
            )
        )
    )
