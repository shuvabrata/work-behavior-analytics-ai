"""Pure geometry helpers for the swimlane timeline.

All functions here are deterministic and free of Dash imports so they can be
unit-tested in isolation.  They compute the pixel layout of event cards inside
a lane, applying linear time scaling with adaptive gap compression.

Gap compression
---------------
Events are positioned linearly by time (``px_per_day`` pixels per day).  When
the gap between two consecutive events exceeds an adaptive threshold, the gap
is compressed to a fixed ``gap_break_px`` height and a visual "gap break"
marker (with the number of skipped days) is rendered instead of the empty
space.  The threshold is ``max(2 * median_spacing, MIN_GAP_THRESHOLD)`` so the
behaviour adapts to the density of the loaded events while never compressing
small, meaningful gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

#: Minimum gap (in days) that is ever compressed, regardless of event density.
MIN_GAP_THRESHOLD_DAYS = 2.0

#: Multiplier applied to the median inter-event spacing to derive the adaptive
#: compression threshold.
GAP_THRESHOLD_MEDIAN_MULTIPLIER = 2.0

#: Absolute cap (in days) on the compression threshold.  Any gap larger than
#: this is always compressed, even when the median spacing is large (e.g. a
#: lane with only two sparse events must still compress the gap between them).
ABSOLUTE_MAX_GAP_DAYS = 7.0

#: Fixed pixel height reserved for a compressed gap break marker.
GAP_BREAK_PX = 28.0

#: Default pixels per day for the linear time scale.
DEFAULT_PX_PER_DAY = 32.0

#: Minimum pixel height of an event card.
MIN_CARD_HEIGHT_PX = 36.0

#: Vertical padding between consecutive event cards.
CARD_GAP_PX = 4.0


@dataclass(frozen=True)
class PositionedCard:
    """An event card positioned within a lane.

    Attributes:
        top: Pixel offset from the top of the lane.
        height: Pixel height of the card.
        gap_before: True when a compressed gap break marker precedes this card.
        gap_days: Number of days skipped by the preceding gap break (0 when
            ``gap_before`` is False).
    """

    top: float
    height: float
    gap_before: bool = False
    gap_days: float = 0.0


@dataclass(frozen=True)
class LaneLayout:
    """Result of laying out a lane's events.

    Attributes:
        cards: Positioned cards, in chronological order (oldest first).
        total_height: Total pixel height of the lane body.
        gap_breaks: Number of compressed gaps rendered.
    """

    cards: list[PositionedCard]
    total_height: float
    gap_breaks: int


def _to_utc(value: datetime) -> datetime:
    """Normalize a datetime to an aware UTC datetime."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _median(values: list[float]) -> float:
    """Return the median of a non-empty list of floats."""
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def compute_gap_threshold_days(event_times: list[datetime]) -> float:
    """Compute the adaptive gap-compression threshold for a set of events.

    The threshold is ``min(max(2 * median_spacing, MIN_GAP_THRESHOLD_DAYS),
    ABSOLUTE_MAX_GAP_DAYS)`` where ``median_spacing`` is the median time delta
    between consecutive events.  The median multiplier adapts the threshold to
    the density of the loaded events; the absolute cap guarantees that very
    sparse data (e.g. two events weeks apart) is still compressed.

    Args:
        event_times: Event timestamps in chronological order.

    Returns:
        The gap threshold in days. Gaps strictly larger than this are
        compressed.
    """
    if len(event_times) < 2:
        return MIN_GAP_THRESHOLD_DAYS

    deltas = [
        (_to_utc(later) - _to_utc(earlier)).total_seconds() / 86400.0
        for earlier, later in zip(event_times, event_times[1:])
    ]
    median_spacing = _median(deltas)
    return min(
        max(
            GAP_THRESHOLD_MEDIAN_MULTIPLIER * median_spacing,
            MIN_GAP_THRESHOLD_DAYS,
        ),
        ABSOLUTE_MAX_GAP_DAYS,
    )


def compute_lane_layout(  # pylint: disable=too-many-locals
    event_times: list[datetime],
    *,
    range_start: datetime,
    range_end: datetime,
    px_per_day: float = DEFAULT_PX_PER_DAY,
    gap_break_px: float = GAP_BREAK_PX,
) -> LaneLayout:
    """Compute the pixel layout of a lane's event cards.

    Events are positioned linearly by time within ``[range_start, range_end]``.
    Gaps between consecutive events that exceed the adaptive threshold are
    compressed to ``gap_break_px`` and flagged with ``gap_before=True``.

    Args:
        event_times: Event timestamps, oldest first.
        range_start: Start of the visible time range (inclusive).
        range_end: End of the visible time range (inclusive).
        px_per_day: Pixels per day of the linear time scale.
        gap_break_px: Fixed pixel height of a compressed gap break.

    Returns:
        A :class:`LaneLayout` with positioned cards and the total lane height.
    """
    if not event_times:
        return LaneLayout(cards=[], total_height=0.0, gap_breaks=0)

    start = _to_utc(range_start)
    end = _to_utc(range_end)
    span_days = max((end - start).total_seconds() / 86400.0, 1e-9)

    # Events may arrive newest-first (API ORDER BY event_time DESC); the
    # layout math requires chronological order.
    ordered_times = sorted(_to_utc(t) for t in event_times)

    threshold_days = compute_gap_threshold_days(ordered_times)

    cards: list[PositionedCard] = []
    cursor = 0.0
    gap_breaks = 0
    previous_time: datetime | None = None

    for utc_time in ordered_times:
        # Clamp to the visible range so out-of-range events still render at
        # the lane edges rather than at negative offsets.
        clamped = max(utc_time, start)
        clamped = min(clamped, end)

        gap_before = False
        gap_days = 0.0

        if previous_time is None:
            # Leading gap: from the range start to the first event.  Compress
            # it when it exceeds the threshold so a lane whose activity is
            # clustered late in the window does not stretch the axis.
            leading_gap_days = (clamped - start).total_seconds() / 86400.0
            if leading_gap_days > threshold_days:
                gap_before = True
                gap_breaks += 1
                gap_days = leading_gap_days
                top = cursor + gap_break_px
            else:
                top = cursor + leading_gap_days * px_per_day
        else:
            gap_days = (utc_time - previous_time).total_seconds() / 86400.0
            if gap_days > threshold_days:
                gap_before = True
                gap_breaks += 1
                top = cursor + gap_break_px
            else:
                top = cursor + gap_days * px_per_day

        cards.append(
            PositionedCard(
                top=top,
                height=MIN_CARD_HEIGHT_PX,
                gap_before=gap_before,
                gap_days=gap_days if gap_before else 0.0,
            )
        )
        cursor = top + MIN_CARD_HEIGHT_PX + CARD_GAP_PX
        previous_time = utc_time

    total_height = max(cursor - CARD_GAP_PX, 0.0)
    return LaneLayout(cards=cards, total_height=total_height, gap_breaks=gap_breaks)


@dataclass(frozen=True)
class TimeAxisMarker:
    """A single time-axis marker.

    Attributes:
        label: Short display label (e.g. ``"Mar 14"``).
        top: Pixel offset from the top of the lane body.
    """

    label: str
    top: float


def build_time_axis_markers(
    range_start: datetime,
    range_end: datetime,
    *,
    px_per_day: float = DEFAULT_PX_PER_DAY,
) -> list[TimeAxisMarker]:
    """Build daily time-axis markers for the visible range.

    One marker is emitted per calendar day (at midnight) between
    ``range_start`` and ``range_end`` inclusive.  Labels use ``%b %d``
    (e.g. ``Mar 14``).

    Args:
        range_start: Start of the visible time range.
        range_end: End of the visible time range.
        px_per_day: Pixels per day of the linear time scale.

    Returns:
        A list of markers ordered oldest first.
    """
    start = _to_utc(range_start)
    end = _to_utc(range_end)

    # Align to local midnight of the start day.
    day_start = start.replace(hour=0, minute=0, second=0, microsecond=0)

    markers: list[TimeAxisMarker] = []
    current = day_start
    while current <= end:
        offset_days = (current - start).total_seconds() / 86400.0
        markers.append(
            TimeAxisMarker(
                label=current.strftime("%b %d"),
                top=max(offset_days * px_per_day, 0.0),
            )
        )
        current += timedelta(days=1)
    return markers


def build_compressed_axis_markers(  # pylint: disable=too-many-locals
    event_times: list[datetime],
    *,
    range_start: datetime,
    range_end: datetime,
    px_per_day: float = DEFAULT_PX_PER_DAY,
    gap_break_px: float = GAP_BREAK_PX,
) -> list[TimeAxisMarker]:
    """Build daily axis markers compressed to match a lane's layout.

    Only markers within the event span (first event day → last event day) are
    emitted, positioned with the same gap compression as the lane cards so the
    axis stays aligned with the rendered events.  This prevents the axis from
    showing 30 empty rows when activity is clustered in a few days.

    Args:
        event_times: Event timestamps, oldest first.
        range_start: Start of the visible time range (inclusive).
        range_end: End of the visible time range (inclusive).
        px_per_day: Pixels per day of the linear time scale.
        gap_break_px: Fixed pixel height of a compressed gap break.

    Returns:
        A list of markers ordered oldest first, positioned on the compressed
        timeline.
    """
    if not event_times:
        return []

    start = _to_utc(range_start)
    end = _to_utc(range_end)
    ordered_times = sorted(_to_utc(t) for t in event_times)
    threshold_days = compute_gap_threshold_days(ordered_times)

    first_event = ordered_times[0]
    last_event = ordered_times[-1]

    # Marker days: midnight of each day from the first event day to the last
    # event day (inclusive).
    first_day = first_event.replace(hour=0, minute=0, second=0, microsecond=0)
    marker_days: list[datetime] = []
    current = first_day
    while current <= last_event:
        marker_days.append(current)
        current += timedelta(days=1)

    # Walk the same compression as compute_lane_layout: a running pixel cursor
    # that advances by the compressed gap between consecutive reference times.
    # Reference times are the marker days themselves, so each marker lands on
    # the compressed position of its day.
    markers: list[TimeAxisMarker] = []
    cursor = 0.0
    previous: datetime | None = None
    for day in marker_days:
        if previous is None:
            leading_gap_days = (day - start).total_seconds() / 86400.0
            if leading_gap_days > threshold_days:
                top = cursor + gap_break_px
            else:
                top = cursor + leading_gap_days * px_per_day
        else:
            gap_days = (day - previous).total_seconds() / 86400.0
            if gap_days > threshold_days:
                top = cursor + gap_break_px
            else:
                top = cursor + gap_days * px_per_day
        markers.append(
            TimeAxisMarker(
                label=day.strftime("%b %d"),
                top=max(top, 0.0),
            )
        )
        cursor = top + 12.0  # small marker height
        previous = day

    return markers