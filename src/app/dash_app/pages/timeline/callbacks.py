"""Dash callbacks for the Activity Timeline page.

UI-0 intentionally leaves this module empty; the selector, fetch, and render
callbacks land in UI-1 onwards. It must exist and be imported from
``app.dash_app.pages.timeline.__init__`` so module-level ``@callback``
registrations added later are picked up at app startup.
"""
