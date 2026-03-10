"""Introspection layer for PostgreSQL schemas, functions, and dependencies.

This package extends confiture's existing SchemaIntrospector (tables/columns/FKs)
with function introspection, type mapping, dependency graphs, and SQL AST parsing.
"""

from confiture.core.introspection.dependency_graph import DependencyGraph
from confiture.core.introspection.functions import FunctionIntrospector
from confiture.core.introspection.type_mapping import TypeMapper

__all__ = [
    "DependencyGraph",
    "FunctionIntrospector",
    "TypeMapper",
]
