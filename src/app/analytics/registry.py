"""Registry for out-of-the-box analytics visualizations.

This module is the single source of truth for graph-based analytics that can be
launched from the Analytics gallery and rendered in the generic graph page.
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


COLLABORATION_NETWORK_ANALYTIC = GraphAnalytic(
    key="collaboration_network",
    title="Collaboration Network",
    description=(
        "Discover organic teams and collaboration hubs from GitHub and Jira "
        "interactions over the last 90 days."
    ),
    icon="fas fa-share-nodes",
)


@dataclass(frozen=True)
class TimelineAnalytic:
    """Metadata for the activity timeline visualization."""

    key: str
    title: str
    description: str
    icon: str

    @property
    def href(self) -> str:
        """Return the timeline page route used to launch this analytic."""
        return "/app/analytics/timeline"


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
