"""Scoped Memory: local-first, project-isolated memory for coding agents."""

from .core import MemoryStore, MemoryError

__all__ = ["MemoryStore", "MemoryError"]
__version__ = "0.3.0"
