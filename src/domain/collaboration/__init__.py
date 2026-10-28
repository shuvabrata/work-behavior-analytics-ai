"""Collaboration-network metadata and validation shared by the API and the UI.

Only the *metadata* half of the collaboration analytics package lives here: the
config model and its defaults, the layer/field label tables, the error types,
and the collaborator-cap choices. The scoring *algorithm* stays at
``app/analytics/collaboration/algorithm.py`` because it pulls in ``networkx``,
``community_louvain`` and ``matplotlib``, which the UI runtime must not carry.
"""
