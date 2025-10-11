"""Confiture: PostgreSQL migrations, sweetly done 🍓

Confiture is a modern PostgreSQL migration tool with a build-from-scratch
philosophy and 4 migration strategies.

Example:
    >>> from confiture import SchemaBuilder
    >>> builder = SchemaBuilder(env="local")
    >>> builder.build()
"""

__version__ = "0.1.0-alpha"
__author__ = "Lionel Hamayon"
__email__ = "lionel@fraiseql.com"

from confiture.core.builder import SchemaBuilder
from confiture.core.migrator import Migrator
from confiture.config.environment import Environment

__all__ = [
    "SchemaBuilder",
    "Migrator",
    "Environment",
    "__version__",
]
