"""What ``Migration.execute`` does with a template string, pinned.

The static evaluator refuses a ``t"…"`` argument (it is a ``Template``, not a
``str``, and its SQL is what the driver renders). At run time the call is handed
to psycopg untouched, and psycopg 3.3 renders it. Whether ``execute`` should
accept a ``Template`` on purpose is a later decision; this makes that change a
deliberate one.
"""

from string.templatelib import Template
from unittest.mock import MagicMock

import psycopg

from confiture.models.migration import Migration


class _Shape(Migration):
    version = "20261005000000"
    name = "template"

    def up(self) -> None:
        pass

    def down(self) -> None:
        pass


def test_a_template_reaches_the_cursor_unchanged() -> None:
    connection = MagicMock(spec=psycopg.Connection)
    cursor = MagicMock()
    connection.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    connection.cursor.return_value.__exit__ = MagicMock(return_value=False)
    table = "a"
    statement = t"CREATE TABLE IF NOT EXISTS {table:i} (id int)"

    _Shape(connection=connection).execute(statement)

    (argument,), _ = cursor.execute.call_args
    assert argument is statement
    assert isinstance(argument, Template)
