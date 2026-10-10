"""Shared utilities for the Library page package."""

from __future__ import annotations

import os


def get_api_base_url() -> str:
    """Return the configured API base URL (falls back to localhost)."""
    return os.getenv("API_BASE_URL", "http://localhost:8000")