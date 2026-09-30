from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


from common.activity_signal.models import (
    ActivitySignal,
    PersonAttributes,
    Relationship,
)
from common.activity_signal.wba_node_id import wba_format
from common.logger import logger

from connectors.producers.github.constants import (
    _SOURCE,
    _VERSION,
    _EPOCH,
    _connector_url
)

def _person_event_time(person_data: Dict[str, Any]) -> datetime:
    """Parse ``created_at`` from *person_data* into a UTC datetime.

    Falls back to the epoch sentinel without a warning — expected behaviour
    for GitAuthor-path persons (commit authors with no GitHub account).
    """
    raw = person_data.get("created_at") or ""
    if raw:
        try:
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
    return _EPOCH


def build_person_signal(
    person_data: Dict[str, Any],
    extra_relationships: Optional[List[Relationship]] = None,
) -> Optional[ActivitySignal]:
    """Build an ActivitySignal for a Person (GitHub author/contributor)."""
    login = person_data.get("login") or person_data.get("name", "unknown")
    person_id = wba_format(_SOURCE, "Person", login)
    logger.debug(
        f"[build_person_signal] id={person_id}  login={login!r}  name={person_data.get('name')!r}  email="
        f"{person_data.get('email')!r}  extra_rels={len(extra_relationships) if extra_relationships else 0}"
    )
    try:
        attrs = PersonAttributes(
            full_name=person_data.get("name") or login,
            login=login,
            email=person_data.get("email") or None,
        )
        return ActivitySignal(
            source=_SOURCE,
            id=login,
            source_config="https://github.com",
            connector_url=_connector_url(),
            event_time=_person_event_time(person_data),
            version=_VERSION,
            attributes=attrs,
            relationships=list(extra_relationships) if extra_relationships else [],
        )
    except Exception as exc:
        logger.warning(f"Skipping Person signal for '{login}' (validation error): {exc}")
        return None

