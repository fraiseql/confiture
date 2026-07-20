"""Tests for the shared ledger-existence primitive."""

from unittest.mock import MagicMock, patch

from confiture.core.ledger import ledger_exists


def _conn_returning(row: tuple | None) -> tuple[MagicMock, MagicMock]:
    """Build a connection whose cursor yields ``row`` from fetchone()."""
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cursor


class TestLedgerExistsBareName:
    """A bare table name matches the table in any schema."""

    def test_ledger_exists_bare_name_present(self):
        conn, cursor = _conn_returning((True,))

        assert ledger_exists(conn, "tb_confiture") is True

        sql, params = cursor.execute.call_args[0]
        assert params == ("tb_confiture",)
        assert "table_schema" not in sql
        assert "tb_confiture" not in sql  # bound as a parameter, never interpolated

    def test_ledger_exists_bare_name_absent(self):
        conn, _ = _conn_returning((False,))

        assert ledger_exists(conn, "tb_confiture") is False

    def test_ledger_exists_no_row_is_false(self):
        conn, _ = _conn_returning(None)

        assert ledger_exists(conn, "tb_confiture") is False


class TestLedgerExistsQualifiedName:
    """A schema-qualified name filters on the schema too."""

    def test_ledger_exists_qualified_name_filters_schema(self):
        conn, cursor = _conn_returning((True,))

        assert ledger_exists(conn, "public.tb_confiture") is True

        sql, params = cursor.execute.call_args[0]
        assert params == ("public", "tb_confiture")
        assert "table_schema" in sql
        assert "table_name" in sql

    def test_qualified_name_does_not_match_other_schema(self):
        """A `public.` qualified probe must not match tb_confiture elsewhere.

        The schema filter is what enforces this; the database returns False
        because the WHERE clause binds both parts.
        """
        conn, cursor = _conn_returning((False,))

        assert ledger_exists(conn, "public.tb_confiture") is False
        assert cursor.execute.call_args[0][1] == ("public", "tb_confiture")

    def test_multi_dot_name_splits_on_first_dot_only(self):
        conn, cursor = _conn_returning((True,))

        ledger_exists(conn, "my_schema.weird.name")

        assert cursor.execute.call_args[0][1] == ("my_schema", "weird.name")


class TestStateDelegatesToLedgerExists:
    """The _migrator state helpers must not carry their own copy of the SQL."""

    def _migrator(self, schema: str | None, base: str) -> MagicMock:
        migrator = MagicMock()
        migrator._table_schema = schema
        migrator._table_base = base
        return migrator

    def test_state_probe_delegates_to_ledger_exists(self):
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
