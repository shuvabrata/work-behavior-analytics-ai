"""Shared utilities for the Library page package."""

from __future__ import annotations

from ui.settings import settings


def get_api_base_url() -> str:
    """Return the configured API base URL (falls back to localhost)."""
    return settings.API_BASE_URL