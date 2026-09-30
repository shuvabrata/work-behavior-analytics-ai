from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from common.logger import logger

from common.activity_signal.models import (
    ActivitySignal,
    Relationship,
    RelationshipTarget,
    TeamAttributes,
)

from connectors.producers.github.constants import (
    _SOURCE,
    _VERSION,
    _EPOCH,
    _connector_url,
)


def _team_event_time(team_data: Dict[str, Any]) -> datetime:
    """Parse ``created_at`` from *team_data* into a UTC datetime.

    Falls back to the epoch sentinel without a warning — teams without a
    ``created_at`` are uncommon but possible.
    """
    raw = team_data.get("created_at") or ""
    if raw:
        try:
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
    return _EPOCH


def build_team_signal(
    team_data: Dict[str, Any],
    repo_data: Dict[str, Any],
    permission: Optional[str] = None,
) -> Optional[ActivitySignal]:
    """Build an ActivitySignal for a GitHub Team."""
    try:
        slug = team_data["slug"]
        attrs = TeamAttributes(
            name=team_data["name"],
            url=team_data.get("url"),
            description=team_data.get("description"),
        )
        props: Optional[Dict[str, Any]] = {"permission": permission} if permission else None
        rels: List[Relationship] = [
            Relationship(
                type="COLLABORATOR",
                direction=None,
                target=RelationshipTarget(
                    source=_SOURCE,
                    entity_type="Repository",
                    id=repo_data["full_name"],
                ),
                properties=props,
            )
        ]
        return ActivitySignal(
            source=_SOURCE,
            id=slug,
            source_config="https://github.com",
            connector_url=_connector_url(),
            event_time=_team_event_time(team_data),
            version=_VERSION,
            attributes=attrs,
            relationships=rels,
        )
    except Exception as exc:
        logger.warning(f"Skipping Team signal for '{team_data.get('name')}' (validation error): {exc}")
        return None
