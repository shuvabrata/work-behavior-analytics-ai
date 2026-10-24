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
    launch_path: str | None = None

    @property
    def href(self) -> str:
        """Return the route used to launch this analytic.

        Analytics rendered by a dedicated page (rather than the generic graph
        page) set ``launch_path``; the rest fall back to the graph-page route.
        """
        return self.launch_path or f"/app/graph?mode={self.key}"


COLLABORATION_NETWORK_ANALYTIC = GraphAnalytic(
    key="collaboration_network",
    title="Collaboration Network",
    description=(
        "Discover organic teams and collaboration hubs from GitHub and Jira "
        "interactions over the last 90 days."
    ),
    icon="fas fa-share-nodes",
)


PER_PERSON_COLLABORATION_NETWORK_ANALYTIC = GraphAnalytic(
    key="per_person_collaboration_network",
    title="Per-Person Collaboration Network",
    description=(
        "See who one person works with, and how closely, from GitHub and Jira "
        "interactions over the last 90 days."
    ),
    icon="fas fa-users",
    launch_path="/app/collaboration/person",
)


GRAPH_ANALYTICS = [
    COLLABORATION_NETWORK_ANALYTIC,
    PER_PERSON_COLLABORATION_NETWORK_ANALYTIC,
]


GRAPH_ANALYTICS_BY_KEY = {analytic.key: analytic for analytic in GRAPH_ANALYTICS}
