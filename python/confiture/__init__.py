"""Confiture: PostgreSQL migrations, sweetly done 🍓

Confiture is a modern PostgreSQL migration tool with a build-from-scratch
philosophy and 4 migration strategies.

Example:
    >>> from confiture import __version__
    >>> print(__version__)
    0.1.0-alpha
"""

from typing import Any

__version__ = "0.1.0-alpha"
__author__ = "Lionel Hamayon"
__email__ = "lionel@fraiseql.com"

__all__ = [
    "__version__",
    "__author__",
    "__email__",
]

# Lazy imports to avoid errors during development
# These will be enabled as components are implemented:
# - SchemaBuilder (Milestone 1.3+)
# - Migrator (Milestone 1.7+)
# - Environment (Milestone 1.2+)


def __getattr__(name: str) -> Any:
    """Lazy import for not-yet-implemented components"""
    if name == "SchemaBuilder":
        from confiture.core.builder import SchemaBuilder

        return SchemaBuilder
    elif name == "Migrator":
        from confiture.core.migrator import Migrator

        return Migrator
    elif name == "Environment":
        from confiture.config.environment import Environment

        return Environment
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
