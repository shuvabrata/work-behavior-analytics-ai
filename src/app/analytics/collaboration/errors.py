"""Exceptions raised by the collaboration analytics pipeline.

A dedicated type exists so the UI can tell "the question was answered and the
answer is empty" apart from "the settings were wrong". Both used to be a plain
``ValueError``, which the Dash callbacks funnel through
``describe_config_error()`` — so a person who simply has no collaborators was
reported as a malformed setting.

``LookupError`` is deliberately *not* a ``ValueError`` subclass. A caller that
forgets to handle this type fails loudly (the generic "unexpected error" path)
rather than silently rendering the settings message again.
"""


class CollaborationDataUnavailable(LookupError):
    """The query ran cleanly but produced no collaboration records.

    This is a legitimate, user-recoverable outcome, not a failure: the focus
    person may be new, dormant, or working entirely outside the lookback
    window. Callers should surface it as a warning with a suggestion to widen
    the window or enable more layers — never as a settings error.
    """
