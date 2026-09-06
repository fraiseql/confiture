"""The tracking-table name is an identifier, never SQL text (SEC-01).

``migration.tracking_table`` comes from a YAML file that anyone with write
access to the repository can edit.  Two properties keep it from becoming a SQL
injection vector:

1. ``_get_tracking_table`` rejects anything that is not a plain, optionally
   schema-qualified identifier — the same rule ``Migrator.__init__`` applies —
   and it does so before any connection is opened.
2. Every query built from the name goes through ``psycopg.sql.Identifier``, so
   the driver quotes it; no call site hand-quotes with an f-string.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from psycopg import sql

from confiture.cli.helpers import _get_tracking_table, _query_applied_versions
from confiture.exceptions import ConfigurationError

_INJECTION = 'tb"; DROP SCHEMA public CASCADE; --'


class _RecordingCursor:
    """A cursor that records what it is asked to execute."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.executed: list[Any] = []

    def __enter__(self) -> _RecordingCursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, query: Any, params: Any = None) -> None:
        self.executed.append(query)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class _FakeConnection:
    def __init__(self, cursor: _RecordingCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _RecordingCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


class TestGetTrackingTableRejectsInjection:
    @pytest.mark.parametrize(
        "value",
        [
            _INJECTION,
            "tb;drop",
            'tb"x',
            "a.b.c",
            "1starts_with_digit",
            "has space",
            "has-dash",
            "",
        ],
    )
    def test_dict_config_with_bad_name_raises_configuration_error(self, value: str) -> None:
        with pytest.raises(ConfigurationError):
            _get_tracking_table({"migration": {"tracking_table": value}})

    def test_environment_object_with_bad_name_raises_configuration_error(self) -> None:
        from confiture.config.environment import Environment

        env = Environment.model_validate(
            {
                "name": "test",
                "database_url": "postgresql://localhost/test",
                "include_dirs": ["db/schema"],
                "migration": {"tracking_table": _INJECTION},
            }
        )
        with pytest.raises(ConfigurationError):
            _get_tracking_table(env)

    def test_error_carries_a_config_code_and_the_offending_value(self) -> None:
        with pytest.raises(ConfigurationError) as excinfo:
            _get_tracking_table({"migration": {"tracking_table": _INJECTION}})
        assert excinfo.value.error_code.startswith("CONFIG_")
        assert _INJECTION in str(excinfo.value)

    @pytest.mark.parametrize("value", ["tb_confiture", "public.tb_confiture", "Audit.TB_Track"])
    def test_valid_names_pass_through_unchanged(self, value: str) -> None:
        assert _get_tracking_table({"migration": {"tracking_table": value}}) == value

    def test_missing_key_still_yields_default(self) -> None:
        assert _get_tracking_table({"database_url": "postgresql://localhost/x"}) == "tb_confiture"


class TestQueryAppliedVersionsUsesIdentifier:
    def _run(self, tracking_table: str) -> tuple[set[str], _RecordingCursor, _FakeConnection]:
        cursor = _RecordingCursor(rows=[("001",), ("002",)])
        conn = _FakeConnection(cursor)
        config = {
            "database_url": "postgresql://localhost/x",
            "migration": {"tracking_table": tracking_table},
        }
        with patch("confiture.core.connection.create_connection", return_value=conn):
            result = _query_applied_versions(config)
        return result, cursor, conn

    def test_qualified_name_executes_a_composed_identifier(self) -> None:
        result, cursor, conn = self._run("audit.tb_track")

        assert result == {"001", "002"}
        assert conn.closed is True
        assert len(cursor.executed) == 1
        query = cursor.executed[0]
        assert isinstance(query, sql.Composed), (
            f"expected psycopg.sql.Composed, got {type(query).__name__}: {query!r}"
        )
        assert query.as_string() == 'SELECT version FROM "audit"."tb_track"'

    def test_bare_name_resolves_through_search_path_not_hardcoded_public(self) -> None:
        """A bare name is left to ``search_path``, as every other reader does (#188)."""
        _, cursor, _ = self._run("tb_track")

        query = cursor.executed[0]
        assert isinstance(query, sql.Composed)
        assert query.as_string() == 'SELECT version FROM "tb_track"'

    def test_no_string_query_is_ever_executed(self) -> None:
        _, cursor, _ = self._run("public.tb_confiture")
        assert not any(isinstance(q, str) for q in cursor.executed)
