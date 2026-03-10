"""Introspect PostgreSQL functions and procedures via pg_catalog."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import psycopg
import psycopg.rows

from confiture.models.function_info import (
    FunctionCatalog,
    FunctionInfo,
    FunctionParam,
    ParamMode,
    Volatility,
)

if TYPE_CHECKING:
    pass

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

    Uses pg_proc, pg_namespace, pg_type, and pg_description to produce
    fully typed FunctionInfo objects suitable for code generation.

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
        rows = self._query(schema, include_triggers=include_triggers, name_pattern=name_pattern)
        functions = [self._row_to_info(row, schema) for row in rows]
        db_name = self._get_db_name()
        return FunctionCatalog(
            database=db_name,
            schema=schema,
            introspected_at=datetime.now(UTC).isoformat(),
            functions=functions,
        )

    def introspect_one(self, schema: str, name: str) -> list[FunctionInfo]:
        """Introspect a single function by name (may return overloads)."""
        rows = self._query(schema, name_pattern=name, exact_name=True)
        return [self._row_to_info(row, schema) for row in rows]

    def _get_db_name(self) -> str:
        with self._conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            row = cur.fetchone()
            return row[0] if row else "unknown"

    def _query(
        self,
        schema: str,
        *,
        include_triggers: bool = False,
        name_pattern: str | None = None,
        exact_name: bool = False,
    ) -> list[dict[str, Any]]:
        """Execute pg_proc query and return raw rows as dicts."""
        conditions = ["n.nspname = %(schema)s", "p.prokind IN ('f', 'p')"]
        params: dict[str, Any] = {"schema": schema}

        if not include_triggers:
            conditions.append("pg_get_function_result(p.oid) IS DISTINCT FROM 'trigger'")

        if name_pattern is not None:
            if exact_name:
                conditions.append("p.proname = %(name_pattern)s")
            else:
                conditions.append("p.proname LIKE %(name_pattern)s")
            params["name_pattern"] = name_pattern

        where_clause = " AND ".join(conditions)

        sql = f"""
            SELECT
                p.oid,
                p.proname                                    AS name,
                n.nspname                                    AS schema,
                p.prokind                                    AS kind,
                p.provolatile                                AS volatility,
                l.lanname                                    AS language,
                pg_get_function_result(p.oid)                AS return_text,
                p.proretset                                  AS returns_set,
                p.prosrc                                     AS source,
                p.procost                                    AS cost,
                p.proargnames                                AS arg_names,
                p.proargmodes                                AS arg_modes,
                COALESCE(p.proallargtypes::oid[], p.proargtypes::oid[]) AS arg_type_oids,
                d.description                                AS comment
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            JOIN pg_language l  ON l.oid = p.prolang
            LEFT JOIN pg_description d ON d.objoid = p.oid AND d.classoid = 'pg_proc'::regclass
            WHERE {where_clause}
            ORDER BY p.proname, p.oid
        """

        with self._conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def _row_to_info(self, row: dict[str, Any], schema: str) -> FunctionInfo:
        """Convert a pg_proc row dict to a FunctionInfo object."""
        params = self._parse_params(row)
        return FunctionInfo(
            schema=schema,
            name=row["name"],
            oid=row["oid"],
            params=params,
            return_type=row["return_text"],
            returns_set=row["returns_set"],
            volatility=_CHAR_TO_VOLATILITY.get(row["volatility"], Volatility.VOLATILE),
            is_procedure=row["kind"] == "p",
            language=row["language"],
            source=row["source"],
            estimated_cost=float(row["cost"]),
            comment=row["comment"],
        )

    def _parse_params(self, row: dict[str, Any]) -> list[FunctionParam]:
        """Parse pg_proc arrays into FunctionParam objects."""
        type_oids: list[int] = row["arg_type_oids"] or []
        names: list[str] = row["arg_names"] or []
        modes: list[str] = row["arg_modes"] or []

        params = []
        for i, type_oid in enumerate(type_oids):
            name = names[i] if i < len(names) else ""
            mode_char = modes[i] if i < len(modes) else "i"
            pg_type = self._resolve_type(type_oid)
            params.append(
                FunctionParam(
                    name=name or "",
                    pg_type=pg_type,
                    mode=_CHAR_TO_MODE.get(mode_char, ParamMode.IN),
                )
            )
        return params

    def _resolve_type(self, type_oid: int) -> str:
        """Resolve a PostgreSQL type OID to its type name."""
        with self._conn.cursor() as cur:
            cur.execute("SELECT format_type(%s, NULL)", (type_oid,))
            row = cur.fetchone()
            return row[0] if row else "unknown"
