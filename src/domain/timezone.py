"""Helpers for working with the app-configured timezone.

The functions here are pure ``zoneinfo`` arithmetic. The *source* of the
timezone string used to be database-adjacent (it read ``app.runtime_settings``),
which is why this module lives in ``domain.`` now: the API runtime, the UI
runtime and the connector runtimes all need it, and none of them may depend on
the others.

The timezone is read from :data:`runtime_settings`, the process-wide settings
cache. Each runtime populates that one shared object at startup — the API from
the database (``app.runtime_settings``) and the UI from the API's snapshot
endpoint (``ui.runtime_settings``). Sharing the cache is what keeps every call
site signature unchanged, so the UI's importers are a pure import-line edit.

``domain`` must not import ``app.*`` or ``ui.*`` (the package contract), so the
cache is owned here rather than by either runtime.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from common.runtime_settings import RuntimeConfigCache

#: The single, process-wide runtime-settings cache.
#:
#: ``app.runtime_settings`` and ``ui.runtime_settings`` both bind to this exact
#: object, so a refresh in either runtime is visible to :func:`get_app_timezone`.
#: A per-runtime cache would make the API's DB overrides invisible here.
runtime_settings: RuntimeConfigCache = RuntimeConfigCache()


def get_app_timezone() -> ZoneInfo:
    """Return the configured app timezone."""
    return ZoneInfo(runtime_settings.get("TIMEZONE"))


def to_app_timezone(dt: datetime) -> datetime:
    """Convert a datetime to the configured app timezone.

    Naive datetimes are treated as UTC so existing persisted timestamps remain stable.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(get_app_timezone())


def now_in_app_timezone() -> datetime:
    """Return the current time in the configured app timezone."""
    return datetime.now(get_app_timezone())


def humanize_duration(dt: datetime, tz: ZoneInfo | None = None) -> str:
    """Return a human readable duration from the current time.
    e.g. 1 min ago, 1 hr ago, 1 day ago, etc.
    """
    if tz is None:
        tz = get_app_timezone()

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    now = datetime.now(tz)
    dt_tz = dt.astimezone(tz)

    diff = now - dt_tz

    if diff.total_seconds() < 60:
        return "just now"

    mins = int(diff.total_seconds() / 60)
    if mins < 60:
        return f"{mins} min{'s' if mins != 1 else ''} ago"

    hours = int(mins / 60)
    if hours < 24:
        return f"{hours} hr{'s' if hours != 1 else ''} ago"

    days = diff.days
    if days < 7:
        return f"{days} day{'s' if days != 1 else ''} ago"

    weeks = int(days / 7)
    if days < 30:
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"

    months = int(days / 30)
    if days < 365:
        return f"{months} month{'s' if months != 1 else ''} ago"

    years = int(days / 365)
    return f"{years} year{'s' if years != 1 else ''} ago"


__all__ = [
    "get_app_timezone",
    "humanize_duration",
    "now_in_app_timezone",
    "runtime_settings",
    "to_app_timezone",
]
