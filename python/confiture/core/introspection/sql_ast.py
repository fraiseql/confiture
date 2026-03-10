"""SQL AST parsing via pglast (optional dependency).

If pglast is not installed, all functions raise ImportError with a
clear install instruction.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any


@dataclasses.dataclass
class CTENode:
    """A single CTE in a WITH clause."""

    name: str
    query_text: str
    dependencies: list[str]
    is_recursive: bool = False
    is_materialized: bool | None = None
    is_writable: bool = False


@dataclasses.dataclass
class JSONBKey:
    """A key detected in a jsonb_build_object() call."""

    key: str
    value_expr: str
    inferred_type: str | None = None


def _require_pglast() -> Any:
    """Import pglast or raise a clear error."""
    try:
        import pglast  # noqa: PLC0415

        return pglast
    except ImportError:
        msg = "pglast is required for SQL AST operations. Install it with: uv add pglast"
        raise ImportError(msg) from None


def extract_ctes(sql: str) -> list[CTENode]:
    """Parse a SQL statement and extract its CTE chain.

    Args:
        sql: A SQL statement containing a WITH clause.

    Returns:
        List of CTENode in declaration order.

    Raises:
        ImportError: If pglast is not installed.
        ValueError: If the SQL cannot be parsed.
    """
    pglast = _require_pglast()
    try:
        tree = pglast.parse_sql(sql)
    except pglast.Error as e:
        msg = f"Cannot parse SQL: {e}"
        raise ValueError(msg) from e

    cte_nodes: list[CTENode] = []
    cte_names: set[str] = set()

    for stmt in tree:
        if not hasattr(stmt, "stmt"):
            continue
        select_stmt = stmt.stmt
        if not hasattr(select_stmt, "withClause") or select_stmt.withClause is None:
            continue

        with_clause = select_stmt.withClause
        is_recursive = bool(getattr(with_clause, "recursive", False))

        for cte in with_clause.ctes or []:
            cte_name = str(cte.ctename)
            cte_names.add(cte_name)
            query_text = pglast.prettify(cte.ctequery)

            # Detect dependencies: other CTEs referenced in this CTE's body
            deps = _find_cte_refs(str(query_text), cte_names - {cte_name})

            # Detect writable CTE (INSERT/UPDATE/DELETE RETURNING)
            is_writable = _is_writable_cte(cte)

            materialized = getattr(cte, "ctematerialized", None)
            if materialized is not None:
                materialized_str = str(materialized)
                is_mat_val: bool | None = (
                    False
                    if "CTEMaterializeNever" in materialized_str
                    else "CTEMaterializeAlways" in materialized_str
                )
            else:
                is_mat_val = None

            cte_nodes.append(
                CTENode(
                    name=cte_name,
                    query_text=query_text,
                    dependencies=deps,
                    is_recursive=is_recursive,
                    is_materialized=is_mat_val,
                    is_writable=is_writable,
                )
            )

    return cte_nodes


def _find_cte_refs(query_text: str, known_ctes: set[str]) -> list[str]:
    """Find references to known CTEs in a query text."""
    refs = []
    query_lower = query_text.lower()
    for cte_name in sorted(known_ctes):
        if cte_name.lower() in query_lower:
            refs.append(cte_name)
    return refs


def _is_writable_cte(cte: Any) -> bool:
    """Check if a CTE body is a DML statement with RETURNING."""
    query = getattr(cte, "ctequery", None)
    if query is None:
        return False
    node_type = type(query).__name__
    return node_type in ("InsertStmt", "UpdateStmt", "DeleteStmt")


def infer_jsonb_shape(function_body: str) -> list[JSONBKey]:
    """Parse a PL/pgSQL function body and extract jsonb_build_object keys.

    Args:
        function_body: The prosrc text of a PL/pgSQL function.

    Returns:
        List of JSONBKey with detected keys. Empty if no jsonb_build_object found.
    """
    _require_pglast()

    keys: list[JSONBKey] = []
    pattern = re.compile(r"jsonb_build_object\s*\((.*?)\)", re.DOTALL | re.IGNORECASE)

    for match in pattern.finditer(function_body):
        args_text = match.group(1)
        args = [a.strip() for a in args_text.split(",")]
        for i in range(0, len(args) - 1, 2):
            key_expr = args[i].strip("'\" ")
            value_expr = args[i + 1].strip() if i + 1 < len(args) else ""
            keys.append(JSONBKey(key=key_expr, value_expr=value_expr))

    return keys


def parse_function_body(function_body: str) -> list[dict[str, Any]]:
    """Parse a PL/pgSQL function body into a list of statement nodes.

    Args:
        function_body: The prosrc text of a PL/pgSQL function.

    Returns:
        List of statement dicts from pglast's parse tree.
    """
    pglast = _require_pglast()
    try:
        tree = pglast.parse_sql(function_body)
        return [dict(stmt) for stmt in tree]
    except pglast.Error as e:
        msg = f"Cannot parse function body: {e}"
        raise ValueError(msg) from e
