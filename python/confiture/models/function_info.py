"""Data models for PostgreSQL function/procedure introspection."""

from __future__ import annotations

import dataclasses
from enum import Enum


class ParamMode(Enum):
    """PostgreSQL parameter mode."""

    IN = "IN"
    OUT = "OUT"
    INOUT = "INOUT"
    VARIADIC = "VARIADIC"
    TABLE = "TABLE"


class Volatility(Enum):
    """PostgreSQL function volatility classification."""

    IMMUTABLE = "IMMUTABLE"
    STABLE = "STABLE"
    VOLATILE = "VOLATILE"


@dataclasses.dataclass
class FunctionParam:
    """A single parameter of a PostgreSQL function."""

    name: str
    pg_type: str
    mode: ParamMode = dataclasses.field(default_factory=lambda: ParamMode.IN)
    has_default: bool = False
    default_expr: str | None = None


@dataclasses.dataclass
class FunctionInfo:
    """Complete introspection result for a single PostgreSQL function."""

    schema: str
    name: str
    oid: int
    params: list[FunctionParam]
    return_type: str | None
    returns_set: bool
    volatility: Volatility
    is_procedure: bool
    language: str
    source: str | None
    estimated_cost: float
    comment: str | None = None

    @property
    def qualified_name(self) -> str:
        """Fully qualified name: schema.name."""
        return f"{self.schema}.{self.name}"

    @property
    def in_params(self) -> list[FunctionParam]:
        """Only IN and INOUT parameters (what callers must provide)."""
        return [p for p in self.params if p.mode in (ParamMode.IN, ParamMode.INOUT)]

    @property
    def out_params(self) -> list[FunctionParam]:
        """Only OUT and TABLE parameters (what callers receive)."""
        return [p for p in self.params if p.mode in (ParamMode.OUT, ParamMode.TABLE)]


@dataclasses.dataclass
class FunctionCatalog:
    """Collection of introspected functions for a schema."""

    database: str
    schema: str
    introspected_at: str
    functions: list[FunctionInfo]

    def by_name(self, name: str) -> list[FunctionInfo]:
        """Find functions by name (may return multiple overloads)."""
        return [f for f in self.functions if f.name == name]

    def procedures_only(self) -> list[FunctionInfo]:
        """Filter to procedures (CALL-able, no return value)."""
        return [f for f in self.functions if f.is_procedure]

    def functions_only(self) -> list[FunctionInfo]:
        """Filter to functions (SELECT-able, has return value)."""
        return [f for f in self.functions if not f.is_procedure]
