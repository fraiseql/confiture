"""SQL-shape contract for the shared ledger-existence primitive (#188).

These are mock-cursor tests: they pin *which query* each path issues and how
its rows are read, not what a real PostgreSQL says. The behavioural coverage —
search_path resolution, privileges, a same-named relation in two schemas — is
in ``tests/integration/test_ledger_probe.py``.

Both layers are load-bearing, and the split is not stylistic: this repo's CI
cannot reach a database (461 of its tests skip there), so an integration-only
guard would gate nothing on a pull request.
"""

from unittest.mock import MagicMock, patch

import psycopg
import pytest

from confiture.core.ledger import (
    LedgerProbe,
    find_ledger_relations,
    ledger_exists,
    probe_ledger,
)
from confiture.exceptions import SQLError


def _conn_returning(row: tuple | None) -> tuple[MagicMock, MagicMock]:
    """Build a connection whose cursor yields ``row`` from fetchone()."""
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cursor


def _conn_raising(exc: BaseException) -> MagicMock:
    cursor = MagicMock()
    cursor.execute.side_effect = exc
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn


class TestBareNameResolvesThroughSearchPath:
    """A bare name asks the question the *next* query will ask (#188).

    ``information_schema.tables WHERE table_name = 'tb_confiture'`` matched the
    table in any schema, so a ledger in `staging` reported present to a session
    that would go on to read `public`. ``to_regclass`` resolves the name exactly
    as the subsequent query does.
    """

    def test_bare_probe_uses_to_regclass(self):
        conn, cursor = _conn_returning(("public", "tb_confiture"))

        assert probe_ledger(conn, "tb_confiture").exists is True

        sql, params = cursor.execute.call_args[0]
        assert "to_regclass" in sql
        assert "information_schema" not in sql
        assert params == ("tb_confiture",)
        # to_regclass takes a string *literal*, so the name is the injection
        # boundary CLAUDE.md's security section governs: bind it, never format.
        assert "tb_confiture" not in sql

    def test_bare_probe_reports_the_schema_it_resolved_to(self):
        conn, _ = _conn_returning(("staging", "tb_confiture"))

        probe = probe_ledger(conn, "tb_confiture")

        assert probe == LedgerProbe(exists=True, resolved_name="staging.tb_confiture")

    def test_bare_probe_absent_has_no_resolved_name(self):
        conn, _ = _conn_returning(None)

        assert probe_ledger(conn, "tb_confiture") == LedgerProbe(exists=False, resolved_name=None)

    def test_bare_probe_excludes_non_table_relations(self):
        """A sequence or index named `tb_confiture` is not a ledger.

        ``to_regclass`` resolves *every* relation kind, where
        ``information_schema.tables`` reported only tables, views and foreign
        tables. Without this filter the conversion would smuggle in a second
        behaviour change beside the search_path fix.
        """
        conn, cursor = _conn_returning(None)

        probe_ledger(conn, "tb_confiture")

        sql = cursor.execute.call_args[0][0]
        assert "relkind" in sql
        assert "'r'" in sql and "'v'" in sql

    def test_ledger_exists_is_the_boolean_face_of_the_probe(self):
        conn, _ = _conn_returning(("public", "tb_confiture"))

        assert ledger_exists(conn, "tb_confiture") is True


class TestBareProbePrivilegeErrorsAreTyped:
    """`to_regclass` can raise where `information_schema` returned cleanly.

    Measured on PostgreSQL 17.8, a *bare* name cannot reach that: search_path
    resolution silently skips schemas the role has no USAGE on and yields NULL.
    The wrapper covers what remains — a role with EXECUTE revoked on
    ``to_regclass``, say — and exists because letting a raw psycopg exception
    out of a ledger probe is precisely the crash class #182 and 0.37.0 closed.
    """

    def test_insufficient_privilege_becomes_a_confitur_error(self):
        conn = _conn_raising(psycopg.errors.InsufficientPrivilege("permission denied"))

        with pytest.raises(SQLError) as excinfo:
            probe_ledger(conn, "tb_confiture")

        assert excinfo.value.error_code == "SQL_001"
        assert "permission denied" in str(excinfo.value)

    def test_other_database_errors_are_not_swallowed(self):
        """Only the privilege case is translated; the rest propagate as-is.

        A blanket ``except Exception`` here would hide a NameError in this very
        module and keep every test in this file green.
        """
        conn = _conn_raising(psycopg.errors.UndefinedFunction("no such function"))

        with pytest.raises(psycopg.errors.UndefinedFunction):
            probe_ledger(conn, "tb_confiture")


class TestQualifiedNameIsDeliberatelyUnchanged:
    """The qualified path stays on `information_schema` — see #188's decision.

    ``to_regclass('hidden.tb_secret')`` *raises* `permission denied for schema
    hidden` for a role without USAGE, where the `information_schema` query
    returns cleanly (both measured). A qualified name already filters on schema
    correctly, so converting it would buy nothing and reopen #182's crash class
    on the path `_migrator/state.py` uses whenever `tracking_table` is
    qualified.
    """

    def test_qualified_probe_still_queries_information_schema(self):
        conn, cursor = _conn_returning((True,))

        assert probe_ledger(conn, "public.tb_confiture").exists is True

        sql, params = cursor.execute.call_args[0]
        assert "information_schema" in sql
        assert "to_regclass" not in sql
        assert params == ("public", "tb_confiture")

    def test_qualified_probe_resolves_to_the_name_it_was_given(self):
        conn, _ = _conn_returning((True,))

        assert probe_ledger(conn, "public.tb_confiture") == LedgerProbe(
            exists=True, resolved_name="public.tb_confiture"
        )

    def test_qualified_name_does_not_match_other_schema(self):
        conn, cursor = _conn_returning((False,))

        probe = probe_ledger(conn, "public.tb_confiture")

        assert probe == LedgerProbe(exists=False, resolved_name=None)
        assert cursor.execute.call_args[0][1] == ("public", "tb_confiture")

    def test_no_row_is_absent(self):
        conn, _ = _conn_returning(None)

        assert ledger_exists(conn, "public.tb_confiture") is False

    def test_multi_dot_name_splits_on_first_dot_only(self):
        conn, cursor = _conn_returning((True,))

        probe_ledger(conn, "my_schema.weird.name")

        assert cursor.execute.call_args[0][1] == ("my_schema", "weird.name")


class TestFindLedgerRelations:
    """The schema-blind sweep behind the auto-baseline guard.

    ``LedgerProbe.resolved_name`` cannot answer "where else does this name
    exist?" — it is None precisely when the probe says absent, which is the only
    time the question is asked. So the guard needs this second query.
    """

    def _conn_returning_rows(self, rows: list[tuple]) -> tuple[MagicMock, MagicMock]:
        cursor = MagicMock()
        cursor.fetchall.return_value = rows
        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn, cursor

    def test_lists_every_schema_holding_the_name(self):
        conn, cursor = self._conn_returning_rows([("archive",), ("staging",)])

        assert find_ledger_relations(conn, "tb_confiture") == [
            "archive.tb_confiture",
            "staging.tb_confiture",
        ]
        assert cursor.execute.call_args[0][1] == ("tb_confiture",)

    def test_a_qualified_name_is_swept_by_its_base(self):
        """The point is to find copies *outside* the configured schema."""
        conn, cursor = self._conn_returning_rows([])

        assert find_ledger_relations(conn, "public.tb_confiture") == []
        assert cursor.execute.call_args[0][1] == ("tb_confiture",)

    def test_the_name_is_split_the_same_way_the_probe_splits_it(self):
        """Both split on the first dot, so the sweep follows up on what was probed.

        A sweep for a different relation than the one probed would report
        look-alikes that are not look-alikes.
        """
        conn, cursor = self._conn_returning_rows([])

        find_ledger_relations(conn, "my_schema.weird.name")

        assert cursor.execute.call_args[0][1] == ("weird.name",)

    def test_system_schemas_are_excluded(self):
        conn, cursor = self._conn_returning_rows([])

        find_ledger_relations(conn, "tb_confiture")

        assert "pg_catalog" in cursor.execute.call_args[0][0]


class TestStateDelegatesToLedgerExists:
    """The _migrator state helpers must not carry their own copy of the SQL."""

    def _migrator(self, schema: str | None, base: str) -> MagicMock:
        migrator = MagicMock()
        migrator._table_schema = schema
        migrator._table_base = base
        return migrator

    def test_state_probe_delegates_to_the_shared_probe(self):
        from confiture.core._migrator import state

        migrator = self._migrator("public", "tb_confiture")

        with patch.object(state, "ledger_exists", return_value=True) as probe:
            assert state.tracking_table_exists(migrator) is True

        probe.assert_called_once_with(migrator.connection, "public.tb_confiture")

    def test_state_probe_delegates_with_bare_name(self):
        from confiture.core._migrator import state

        migrator = self._migrator(None, "tb_confiture")

        with patch.object(state, "ledger_exists", return_value=False) as probe:
            assert state.tracking_table_exists(migrator) is False

        probe.assert_called_once_with(migrator.connection, "tb_confiture")

    @staticmethod
    def _executed_sql(migrator: MagicMock) -> str:
        return " ".join(str(call.args[0]) for call in migrator._execute_sql.call_args_list)

    def test_initialize_uses_ledger_exists_and_skips_create(self):
        """Present ledger: no CREATE TABLE, only the #137 additive ALTER."""
        from confiture.core._migrator import state

        migrator = self._migrator("public", "tb_confiture")

        with patch.object(state, "ledger_exists", return_value=True) as probe:
            state.initialize(migrator)

        probe.assert_called_once_with(migrator.connection, "public.tb_confiture")
        executed = self._executed_sql(migrator)
        assert "CREATE TABLE" not in executed
        assert "ADD COLUMN IF NOT EXISTS applied_by" in executed

    def test_initialize_creates_table_when_ledger_absent(self):
        from confiture.core._migrator import state

        migrator = self._migrator("public", "tb_confiture")

        with patch.object(state, "ledger_exists", return_value=False):
            state.initialize(migrator)

        executed = self._executed_sql(migrator)
        assert "CREATE TABLE" in executed
        assert "CREATE INDEX" in executed
