"""A statement confiture executes is shown as its SQL, whatever it was built as.

Executed SQL moves to template strings (#599). A ``Template`` has no
``as_string``, so an error or a log line that rendered a composed statement by
duck-typing would show ``Template(strings=…)`` instead of the statement.
"""

from unittest.mock import MagicMock

import psycopg
import pytest
from psycopg import sql

from confiture.core._migrator.engine import MigrationEngine
from confiture.exceptions import SQLError
from confiture.sql_text import rendered

TABLE = "tb_item"


def test_a_template_renders_as_its_sql() -> None:
    assert rendered(t"DELETE FROM {TABLE:i} WHERE id = {7}") == 'DELETE FROM "tb_item" WHERE id = 7'


def test_a_composed_statement_and_a_string_render_as_before() -> None:
    assert rendered(sql.SQL("SELECT {}").format(sql.Identifier("a"))) == 'SELECT "a"'
    assert rendered("SELECT 1") == "SELECT 1"


def test_an_sql_error_shows_a_templates_sql() -> None:
    error = SQLError(t"DELETE FROM {TABLE:i}", None, RuntimeError("boom"))
    assert 'SQL: DELETE FROM "tb_item"' in str(error)


def test_the_migrators_failure_shows_a_templates_sql() -> None:
    connection = MagicMock(spec=psycopg.Connection)
    cursor = MagicMock()
    cursor.execute.side_effect = psycopg.errors.UndefinedTable("no such table")
    connection.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    connection.cursor.return_value.__exit__ = MagicMock(return_value=False)
    engine = MigrationEngine.__new__(MigrationEngine)
    engine.connection = connection

    with pytest.raises(SQLError) as raised:
        engine._execute_sql(t"DELETE FROM {TABLE:i}")

    assert raised.value.sql == 'DELETE FROM "tb_item"'
