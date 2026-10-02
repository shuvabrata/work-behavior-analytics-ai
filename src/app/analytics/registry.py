"""Registry for out-of-the-box analytics visualizations.

This module is the single source of truth for analytics that can be launched
from the Analytics gallery.  Graph-based analytics are rendered in the generic
graph page; the activity timeline is rendered on its own dedicated page.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class GraphAnalytic:
    """Metadata for a pre-built graph analytic."""

    key: str
    title: str
    description: str
    icon: str

    @property
    def href(self) -> str:
        """Return the graph-page route used to launch this analytic."""
        return f"/app/graph?mode={self.key}"


@dataclass(frozen=True)
class TimelineAnalytic:
    """Metadata for the activity timeline visualization.

    Deliberately separate from :class:`GraphAnalytic`: the timeline is rendered
    on its own page (``/app/analytics/timeline``), not in the generic graph
    page, so ``href`` must not use the ``/app/graph?mode=...`` scheme.
    """

    key: str
    title: str
    description: str
    icon: str

    @property
    def href(self) -> str:
        """Return the timeline page route used to launch this analytic."""
        return "/app/analytics/timeline"


COLLABORATION_NETWORK_ANALYTIC = GraphAnalytic(
    key="collaboration_network",
    title="Collaboration Network",
    description=(
        "Discover organic teams and collaboration hubs from GitHub and Jira "
        "interactions over the last 90 days."
    ),
    icon="fas fa-share-nodes",
)


TIMELINE_ANALYTIC = TimelineAnalytic(
    key="activity_timeline",
    title="Activity Timeline",
    description=(
        "Visualize the chronological activity of persons and objects "
        "across GitHub, Jira, and Confluence in a side-by-side swimlane view."
    ),
    icon="fas fa-timeline",
)


GRAPH_ANALYTICS = [
    COLLABORATION_NETWORK_ANALYTIC,
]


GRAPH_ANALYTICS_BY_KEY = {analytic.key: analytic for analytic in GRAPH_ANALYTICS}
