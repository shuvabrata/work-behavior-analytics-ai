
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from common.activity_signal.models import ActivitySignal, RepositoryAttributes
from common.activity_signal.wba_node_id import wba_format
from common.logger import logger

from connectors.producers.github.constants import (
    _SOURCE,
    _VERSION,
    _EPOCH,
    _connector_url,
)


def _repo_event_time(repo_data: Dict[str, Any]) -> datetime:
    """Parse ``created_at`` from *repo_data* into a UTC datetime.

    Repository ``event_time`` uses ``created_at`` because the repo node is a
    structural anchor — its identity doesn't change when content is pushed.
    Falls back to the epoch sentinel with a warning if the field is absent.
    """
    raw = repo_data.get("created_at") or ""
    if raw:
        try:
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
    logger.warning(
        f"Repository '{repo_data.get('full_name')}' has no created_at — using epoch sentinel."
    )
    return _EPOCH

def build_repository_signal(repo_data: Dict[str, Any]) -> Optional[ActivitySignal]:
    """Build an ActivitySignal for a GitHub Repository."""
    try:
        full_name = repo_data["full_name"]
        attrs = RepositoryAttributes(
            name=repo_data["name"],
            description=repo_data.get("description") or None,
            language=repo_data.get("language") or None,
            is_private=repo_data.get("is_private", False),
            topics=repo_data.get("topics") or [],
            url=repo_data.get("url"),
            created_at=repo_data.get("created_at"),
            updated_at=repo_data.get("updated_at"),
        )
        return ActivitySignal(
            source=_SOURCE,
            id=full_name,
            source_config="https://github.com",
            connector_url=_connector_url(),
            event_time=_repo_event_time(repo_data),
            version=_VERSION,
            attributes=attrs,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(f"Skipping Repository signal (validation error): {exc}")
        return None