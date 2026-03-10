"""CTE step-through debugger: execute each CTE in isolation to find failures."""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any

import psycopg

from confiture.models.debug_models import CTEDebugSession, CTEStepResult

if TYPE_CHECKING:
    pass


def _extract_cte_names(sql: str) -> list[str]:
    """Extract CTE names from a WITH ... AS query using regex."""
    # Match: WITH [RECURSIVE] name AS (
    pattern = re.compile(
        r"(?:^|\bWITH\b)\s+(?:RECURSIVE\s+)?(\w+)\s+AS\s*\(",
        re.IGNORECASE | re.MULTILINE,
    )
    # Also match subsequent CTEs: , name AS (
    subsequent_pattern = re.compile(
        r",\s*(\w+)\s+AS\s*\(",
        re.IGNORECASE | re.MULTILINE,
    )

    names: list[str] = []
    for m in pattern.finditer(sql):
        name = m.group(1)
        if name.upper() not in ("SELECT", "INSERT", "UPDATE", "DELETE", "WITH"):
            names.append(name)

    for m in subsequent_pattern.finditer(sql):
        name = m.group(1)
        if name not in names:
            names.append(name)

    return names


def _build_cte_isolation_query(sql: str, up_to: str) -> str:
    """Build a query that runs all CTEs up to and including `up_to`, then SELECTs from it."""
    # Strip trailing semicolon
    sql = sql.strip().rstrip(";")

    # Find the position of the final SELECT (after all CTEs)
    # We need to replace the final SELECT with SELECT * FROM <cte_name>
    cte_names = _extract_cte_names(sql)

    if not cte_names:
        return sql

    target_idx = cte_names.index(up_to) if up_to in cte_names else len(cte_names) - 1
    included = cte_names[: target_idx + 1]

    # Parse the WITH clause to extract just the relevant CTEs
    # Strategy: find each CTE's body by matching balanced parentheses
    cte_blocks = _extract_cte_blocks(sql)

    selected_blocks = [b for b in cte_blocks if b["name"] in included]
    if not selected_blocks:
        return f"SELECT * FROM ({sql}) AS _debug LIMIT 100"

    cte_defs = ",\n".join(f"{b['name']} AS ({b['body']})" for b in selected_blocks)

    # Detect if original query had RECURSIVE
    recursive = "RECURSIVE " if re.search(r"\bWITH\s+RECURSIVE\b", sql, re.IGNORECASE) else ""

    return f"WITH {recursive}{cte_defs}\nSELECT * FROM {up_to} LIMIT 100"


def _extract_cte_blocks(sql: str) -> list[dict[str, Any]]:
    """Extract CTE name/body pairs from a WITH clause."""
    blocks: list[dict[str, Any]] = []

    # Find the WITH keyword
    with_match = re.search(r"\bWITH\b\s+(?:RECURSIVE\s+)?", sql, re.IGNORECASE)
    if not with_match:
        return blocks

    pos = with_match.end()

    while pos < len(sql):
        # Skip whitespace
        while pos < len(sql) and sql[pos].isspace():
            pos += 1

        # Read CTE name
        name_match = re.match(r"(\w+)\s*AS\s*\(", sql[pos:], re.IGNORECASE)
        if not name_match:
            break

        name = name_match.group(1)
        if name.upper() in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            break

        pos += name_match.end() - 1  # position at opening (

        # Find matching closing )
        depth = 0
        body_start = pos
        body_end = pos
        while pos < len(sql):
            if sql[pos] == "(":
                depth += 1
            elif sql[pos] == ")":
                depth -= 1
                if depth == 0:
                    body_end = pos
                    pos += 1
                    break
            pos += 1

        body = sql[body_start + 1 : body_end]
        blocks.append({"name": name, "body": body})

        # Skip whitespace and comma
        while pos < len(sql) and sql[pos] in (" ", "\t", "\n", "\r"):
            pos += 1
        if pos < len(sql) and sql[pos] == ",":
            pos += 1  # skip comma, continue to next CTE
        else:
            break  # no more CTEs

    return blocks


class CTEDebugger:
    """Executes each CTE in a WITH query in isolation to pinpoint failures."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._conn = connection

    def debug(self, sql: str, *, max_rows: int = 100) -> CTEDebugSession:
        """Run the CTE query step by step.

        For each CTE in the query, executes all preceding CTEs + that CTE
        and returns the intermediate result.

        Args:
            sql: A SQL query with a WITH clause.
            max_rows: Maximum rows to return per step (default: 100).

        Returns:
            CTEDebugSession with results for each step.
        """
        cte_names = _extract_cte_names(sql)
        steps: list[CTEStepResult] = []

        for name in cte_names:
            step = self._execute_step(sql, name, max_rows=max_rows)
            steps.append(step)
            if not step.success:
                # Stop at first failure
                break

        return CTEDebugSession(
            original_query=sql,
            steps=steps,
            total_ctes=len(cte_names),
        )

    def _execute_step(self, sql: str, cte_name: str, *, max_rows: int) -> CTEStepResult:
        """Execute all CTEs up to and including cte_name and return results."""
        isolation_query = _build_cte_isolation_query(sql, cte_name)

        start_time = time.monotonic()
        try:
            with self._conn.cursor() as cur:
                cur.execute(isolation_query)
                rows = cur.fetchmany(max_rows)
                columns = [desc[0] for desc in (cur.description or [])]
                elapsed_ms = (time.monotonic() - start_time) * 1000
                return CTEStepResult(
                    cte_name=cte_name,
                    row_count=len(rows),
                    columns=columns,
                    rows=list(rows),
                    execution_time_ms=round(elapsed_ms, 2),
                )
        except Exception as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            # Rollback to recover the connection state
            import contextlib

            with contextlib.suppress(Exception):
                self._conn.rollback()
            return CTEStepResult(
                cte_name=cte_name,
                row_count=0,
                columns=[],
                rows=[],
                execution_time_ms=round(elapsed_ms, 2),
                error=str(e),
            )
