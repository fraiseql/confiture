"""Introspect PostgreSQL functions and procedures, through ``core/live_catalog``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from confiture.core import live_catalog
from confiture.models.function_info import (
    FunctionCatalog,
    FunctionInfo,
    FunctionParam,
    ParamMode,
    Volatility,
)

if TYPE_CHECKING:
    import psycopg

    from confiture.core.live_catalog import RoutineRow

_CHAR_TO_MODE: dict[str, ParamMode] = {
    "i": ParamMode.IN,
    "o": ParamMode.OUT,
    "b": ParamMode.INOUT,
    "v": ParamMode.VARIADIC,
    "t": ParamMode.TABLE,
}

_CHAR_TO_VOLATILITY: dict[str, Volatility] = {
    "i": Volatility.IMMUTABLE,
    "s": Volatility.STABLE,
    "v": Volatility.VOLATILE,
}


class FunctionIntrospector:
    """Introspects functions and procedures from a PostgreSQL database.

    Each routine is one :class:`~confiture.core.live_catalog.RoutineRow`, read in
    one query with its argument types already spelled, and turned into a fully
    typed :class:`FunctionInfo` suitable for code generation.

    Args:
        connection: An open psycopg connection to the target database.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._conn = connection

    def introspect(
        self,
        schema: str = "public",
        *,
        include_triggers: bool = False,
        name_pattern: str | None = None,
    ) -> FunctionCatalog:
        """Introspect all functions/procedures in the given schema."""
        rows = live_catalog.routines(
            self._conn, [schema], include_triggers=include_triggers, name_pattern=name_pattern
        )
        functions = [_info(row, schema) for row in rows]
        db_name = self._get_db_name()
        return FunctionCatalog(
            database=db_name,
            schema=schema,
            introspected_at=datetime.now(UTC).isoformat(),
            functions=functions,
        )

    def introspect_one(self, schema: str, name: str) -> list[FunctionInfo]:
        """Introspect a single function by name (may return overloads)."""
        rows = live_catalog.routines(
            self._conn, [schema], include_triggers=False, name_pattern=name, exact_name=True
        )
        return [_info(row, schema) for row in rows]

    def _get_db_name(self) -> str:
        with self._conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            row = cur.fetchone()
            return row[0] if row else "unknown"


def _info(row: RoutineRow, schema: str) -> FunctionInfo:
    """One catalog row as a :class:`FunctionInfo`."""
    return FunctionInfo(
        schema=schema,
        name=row.name,
        oid=row.oid,
        params=_params(row),
        return_type=row.result,
        returns_set=row.returns_set,
        volatility=_CHAR_TO_VOLATILITY.get(row.volatility, Volatility.VOLATILE),
        is_procedure=row.kind == "p",
        language=row.language,
        source=row.source,
        estimated_cost=row.cost,
        comment=row.comment,
        security_definer=row.security_definer,
        search_path_pinned=row.search_path_pinned,
    )


def _params(row: RoutineRow) -> list[FunctionParam]:
    """Every argument, in order; a missing name is ``""`` and a missing mode ``IN``."""
    return [
        FunctionParam(
            name=(row.arg_names[i] if i < len(row.arg_names) else "") or "",
            pg_type=pg_type,
            mode=_CHAR_TO_MODE.get(
                row.arg_modes[i] if i < len(row.arg_modes) else "i", ParamMode.IN
            ),
        )
        for i, pg_type in enumerate(row.arg_types)
    ]
