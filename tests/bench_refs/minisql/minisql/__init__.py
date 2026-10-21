"""minisql: an in-memory engine for a subset of SQLite's SQL (standard library only)."""

from .api import Connection, Cursor, connect
from .errors import Error

__all__ = ["Connection", "Cursor", "Error", "connect"]
