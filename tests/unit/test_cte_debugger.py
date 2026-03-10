"""Unit tests for CTEDebugger."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from confiture.core.cte_debugger import (
    CTEDebugger,
    _build_cte_isolation_query,
    _extract_cte_blocks,
    _extract_cte_names,
)


def test_extract_cte_names_simple():
    sql = "WITH base AS (SELECT 1) SELECT * FROM base"
    names = _extract_cte_names(sql)
    assert names == ["base"]


def test_extract_cte_names_multiple():
    sql = """
    WITH
        users AS (SELECT * FROM tb_user),
        bookings AS (SELECT * FROM tb_booking WHERE user_id IN (SELECT id FROM users))
    SELECT * FROM bookings
    """
    names = _extract_cte_names(sql)
    assert "users" in names
    assert "bookings" in names
    assert names.index("users") < names.index("bookings")


def test_extract_cte_names_empty():
    sql = "SELECT * FROM tb_user"
    names = _extract_cte_names(sql)
    assert names == []


def test_extract_cte_blocks_simple():
    sql = "WITH base AS (SELECT 1 AS id) SELECT * FROM base"
    blocks = _extract_cte_blocks(sql)
    assert len(blocks) == 1
    assert blocks[0]["name"] == "base"
    assert "SELECT 1 AS id" in blocks[0]["body"]


def test_build_cte_isolation_query_single():
    sql = "WITH base AS (SELECT 1 AS id) SELECT * FROM base"
    query = _build_cte_isolation_query(sql, "base")
    assert "WITH" in query.upper()
    assert "base" in query
    assert "SELECT * FROM base" in query


def test_build_cte_isolation_query_stops_at_target():
    sql = """
    WITH
        a AS (SELECT 1 AS v),
        b AS (SELECT v + 1 AS v FROM a)
    SELECT * FROM b
    """
    # Request only up to "a"
    query = _build_cte_isolation_query(sql, "a")
    assert "SELECT * FROM a" in query
    # "b" should not appear as a CTE definition
    assert "b AS" not in query


def test_cte_debugger_debug_single_cte():
    from confiture.models.debug_models import CTEDebugSession

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchmany.return_value = [(1,), (2,)]
    mock_cursor.description = [("id",)]
    mock_conn.cursor.return_value = mock_cursor

    debugger = CTEDebugger(mock_conn)
    session = debugger.debug("WITH base AS (SELECT 1 AS id) SELECT * FROM base")

    assert isinstance(session, CTEDebugSession)
    assert len(session.steps) == 1
    assert session.steps[0].cte_name == "base"
    assert session.all_succeeded is True


def test_cte_debugger_debug_stops_on_error():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.execute.side_effect = Exception("relation 'missing' does not exist")
    mock_conn.cursor.return_value = mock_cursor

    debugger = CTEDebugger(mock_conn)
    sql = "WITH bad AS (SELECT * FROM missing) SELECT * FROM bad"
    session = debugger.debug(sql)

    assert len(session.steps) == 1
    assert session.steps[0].error is not None
    assert session.all_succeeded is False
    assert session.failed_at == "bad"


def test_cte_debugger_step_result_includes_timing():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchmany.return_value = []
    mock_cursor.description = [("v",)]
    mock_conn.cursor.return_value = mock_cursor

    debugger = CTEDebugger(mock_conn)
    session = debugger.debug("WITH x AS (SELECT 1 AS v) SELECT * FROM x")

    assert session.steps[0].execution_time_ms >= 0
