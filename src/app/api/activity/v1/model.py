"""Pydantic models for Activity Timeline API v1."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TimelineRequest(BaseModel):
    """Query parameters for ``GET /api/v1/activity/timeline``.

    ``wba_ids`` is a list of WBA canonical keys (``{source}::{entity_type}::{id}``),
    one per requested swimlane.  The router splits the comma-separated query
    parameter into this list.
    """

    wba_ids: list[str] = Field(
        ...,
        description="WBA canonical keys, e.g. github::Person::alice",
    )
    scope: Literal["activity", "history"] = Field(
        default="activity",
        description=(
            "activity = actions involving the entity (actor or target); "
            "history = the entity's own state-change snapshots"
        ),
    )
    from_: datetime | None = Field(
        default=None,
        description="Time range start (ISO 8601).",
    )
    to: datetime | None = Field(
        default=None,
        description="Time range end (ISO 8601).",
    )
    cursor: str | None = Field(
        default=None,
        description="Opaque pagination cursor from a previous response.",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Events per lane. Default 20, max 100.",
    )


class TimelineEvent(BaseModel):
    """A single event rendered inside a timeline lane."""

    signal_id: str = Field(..., description="UUID of the originating ActivitySignal.")
    event_time: datetime = Field(..., description="When the event happened in the source system.")
    relationship_type: str = Field(
        ...,
        description=(
            "Relationship observed (e.g. CREATED, REVIEWED). For scope=history "
            "events this is the synthetic STATE_CHANGE marker."
        ),
    )
    summary: str | None = Field(default=None, description="Short human-readable summary.")
    entity_type: str = Field(
        ...,
        description=(
            "The *other* entity involved: the target when the lane entity is the "
            "actor, the actor when the lane entity is the target. For scope=history "
            "this is the lane entity's own type."
        ),
    )
    source: str = Field(..., description="Data integration source (github, jira, confluence).")
    url: str | None = Field(default=None, description="Link to the source system.")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Attributes snapshot of the signal entity at event_time.",
    )


class TimelineLane(BaseModel):
    """One swimlane — the chronological activity of a single entity."""

    wba_id: str = Field(..., description="WBA canonical key of the lane entity.")
    entity_type: str = Field(..., description="Entity type of the lane entity.")
    label: str = Field(..., description="Display label (pre-computed display_name or raw id).")
    avatar_url: str | None = Field(default=None, description="Person avatar; NULL for other types.")
    events: list[TimelineEvent] = Field(default_factory=list)
    next_cursor: str | None = Field(
        default=None,
        description="Opaque cursor for the next page of this lane; null when exhausted.",
    )


def _empty_time_range() -> dict[str, datetime | None]:
    """Return the default empty time range dict."""
    return {"from": None, "to": None}


class TimelineMeta(BaseModel):
    """Response metadata for the timeline endpoint."""

    time_range: dict[str, datetime | None] = Field(
        default_factory=_empty_time_range,
        description="Echo of the requested time range.",
    )
    total_lanes: int = Field(default=0, description="Number of lanes returned.")


class TimelineResponse(BaseModel):
    """Response for ``GET /api/v1/activity/timeline``."""

    lanes: list[TimelineLane] = Field(default_factory=list)
    meta: TimelineMeta = Field(default_factory=TimelineMeta)


class Suggestion(BaseModel):
    """A single typeahead suggestion for the entity selector."""

    wba_id: str = Field(..., description="WBA canonical key.")
    label: str = Field(..., description="Display label for the suggestion.")
    entity_type: str = Field(..., description="Entity type (Person, Issue, ...).")
    source: str = Field(..., description="Data integration source.")
    avatar_url: str | None = Field(default=None, description="Person avatar; NULL for other types.")


class SuggestResponse(BaseModel):
    """Response for ``GET /api/v1/activity/suggest``."""

    results: list[Suggestion] = Field(default_factory=list)