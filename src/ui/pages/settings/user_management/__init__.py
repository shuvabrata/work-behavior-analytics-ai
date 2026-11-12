"""User Management settings page package."""

from .layout import get_layout

# pylint: disable=unused-import
from . import callbacks  # noqa: F401

__all__ = ["get_layout"]
