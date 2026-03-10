"""Unit tests for MigrationVerifier (Issue #65)."""

from unittest.mock import MagicMock

import pytest

from confiture.core.migration_verifier import MigrationVerifier, _is_truthy
from confiture.exceptions import VerifyFileError


@pytest.fixture
def tmp_migrations(tmp_path):
    """Create a temp migrations directory."""
    return tmp_path


@pytest.fixture
def mock_connection():
    """Create a mock DB connection with cursor."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


class TestDiscoverVerifyFiles:
    def test_discovers_verify_sql(self, tmp_migrations):
        (tmp_migrations / "001_foo.verify.sql").write_text("SELECT true")
        verifier = MigrationVerifier(connection=MagicMock(), migrations_dir=tmp_migrations)
        files = verifier.discover_verify_files()
        assert "001" in files

    def test_ignores_up_down_sql(self, tmp_migrations):
        (tmp_migrations / "001_foo.up.sql").write_text("CREATE TABLE foo (id int)")
        (tmp_migrations / "001_foo.down.sql").write_text("DROP TABLE foo")
        verifier = MigrationVerifier(connection=MagicMock(), migrations_dir=tmp_migrations)
        files = verifier.discover_verify_files()
        assert len(files) == 0

    def test_timestamp_version(self, tmp_migrations):
        (tmp_migrations / "20260228120530_foo.verify.sql").write_text("SELECT true")
        verifier = MigrationVerifier(connection=MagicMock(), migrations_dir=tmp_migrations)
        files = verifier.discover_verify_files()
        assert "20260228120530" in files

    def test_maps_to_file_path(self, tmp_migrations):
        verify_file = tmp_migrations / "001_foo.verify.sql"
        verify_file.write_text("SELECT true")
        verifier = MigrationVerifier(connection=MagicMock(), migrations_dir=tmp_migrations)
        files = verifier.discover_verify_files()
        assert files["001"] == verify_file


class TestIsTruthy:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (True, True),
            (False, False),
            (None, False),
            (1, True),
            (0, False),
            (42, True),
            (-1, True),
            (0.0, False),
            (1.5, True),
            ("true", True),
            ("True", True),
            ("t", True),
            ("yes", True),
            ("1", True),
            ("false", False),
            ("False", False),
            ("f", False),
            ("0", False),
            ("", False),
        ],
    )
    def test_is_truthy(self, value, expected):
        assert _is_truthy(value) == expected


class TestRunVerify:
    def test_true_result_passes(self, tmp_migrations, mock_connection):
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (True,)

        verify_file = tmp_migrations / "001_foo.verify.sql"
        verify_file.write_text("SELECT true")

        verifier = MigrationVerifier(connection=conn, migrations_dir=tmp_migrations)
        result = verifier.run_verify("001", "foo", verify_file)
        assert result.status == "verified"
        assert result.actual_value is True

    def test_false_result_fails(self, tmp_migrations, mock_connection):
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (False,)

        verify_file = tmp_migrations / "001_foo.verify.sql"
        verify_file.write_text("SELECT false")

        verifier = MigrationVerifier(connection=conn, migrations_dir=tmp_migrations)
        result = verifier.run_verify("001", "foo", verify_file)
        assert result.status == "failed"
        assert result.actual_value is False

    def test_empty_result_fails(self, tmp_migrations, mock_connection):
        conn, cursor = mock_connection
        cursor.fetchone.return_value = None

        verify_file = tmp_migrations / "001_foo.verify.sql"
        verify_file.write_text("SELECT true WHERE false")

        verifier = MigrationVerifier(connection=conn, migrations_dir=tmp_migrations)
        result = verifier.run_verify("001", "foo", verify_file)
        assert result.status == "failed"
        assert "zero rows" in (result.error or "")

    def test_nonzero_int_passes(self, tmp_migrations, mock_connection):
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (42,)

        verify_file = tmp_migrations / "001_foo.verify.sql"
        verify_file.write_text("SELECT count(*) FROM pg_tables")

        verifier = MigrationVerifier(connection=conn, migrations_dir=tmp_migrations)
        result = verifier.run_verify("001", "foo", verify_file)
        assert result.status == "verified"
        assert result.actual_value == 42

    def test_null_fails(self, tmp_migrations, mock_connection):
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (None,)

        verify_file = tmp_migrations / "001_foo.verify.sql"
        verify_file.write_text("SELECT NULL")

        verifier = MigrationVerifier(connection=conn, migrations_dir=tmp_migrations)
        result = verifier.run_verify("001", "foo", verify_file)
        assert result.status == "failed"

    def test_ddl_rejected(self, tmp_migrations, mock_connection):
        conn, cursor = mock_connection
        verify_file = tmp_migrations / "001_foo.verify.sql"
        verify_file.write_text("ALTER TABLE foo ADD COLUMN bar int")

        verifier = MigrationVerifier(connection=conn, migrations_dir=tmp_migrations)
        with pytest.raises(VerifyFileError):
            verifier.run_verify("001", "foo", verify_file)

    def test_insert_rejected(self, tmp_migrations, mock_connection):
        conn, cursor = mock_connection
        verify_file = tmp_migrations / "001_foo.verify.sql"
        verify_file.write_text("INSERT INTO foo VALUES (1)")

        verifier = MigrationVerifier(connection=conn, migrations_dir=tmp_migrations)
        with pytest.raises(VerifyFileError):
            verifier.run_verify("001", "foo", verify_file)

    def test_cte_select_passes(self, tmp_migrations, mock_connection):
        """WITH ... SELECT should be allowed (UNKNOWN type in sqlparse)."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (True,)

        verify_file = tmp_migrations / "001_foo.verify.sql"
        verify_file.write_text("WITH t AS (SELECT 1) SELECT true FROM t")

        verifier = MigrationVerifier(connection=conn, migrations_dir=tmp_migrations)
        result = verifier.run_verify("001", "foo", verify_file)
        assert result.status == "verified"

    def test_verify_runs_in_savepoint(self, tmp_migrations, mock_connection):
        """Check that SAVEPOINT/ROLLBACK are sent around the query."""
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (True,)

        verify_file = tmp_migrations / "001_foo.verify.sql"
        verify_file.write_text("SELECT true")

        verifier = MigrationVerifier(connection=conn, migrations_dir=tmp_migrations)
        verifier.run_verify("001", "foo", verify_file)

        calls = [c[0][0] for c in cursor.execute.call_args_list]
        assert any("SAVEPOINT" in c for c in calls)
        assert any("ROLLBACK TO SAVEPOINT" in c for c in calls)

    def test_sql_error_returns_failed(self, tmp_migrations, mock_connection):
        """SQL execution error should return failed status, not raise."""
        conn, cursor = mock_connection
        cursor.execute.side_effect = [None, Exception("syntax error"), None]

        verify_file = tmp_migrations / "001_foo.verify.sql"
        verify_file.write_text("SELECT true")

        verifier = MigrationVerifier(connection=conn, migrations_dir=tmp_migrations)
        result = verifier.run_verify("001", "foo", verify_file)
        assert result.status == "failed"
        assert result.error is not None


class TestVerifyAll:
    def test_returns_all_applied(self, tmp_migrations, mock_connection):
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (True,)

        (tmp_migrations / "001_foo.verify.sql").write_text("SELECT true")
        (tmp_migrations / "002_bar.verify.sql").write_text("SELECT true")

        verifier = MigrationVerifier(connection=conn, migrations_dir=tmp_migrations)
        results = verifier.verify_all(["001", "002"])
        assert len(results) == 2
        assert all(r.status == "verified" for r in results)

    def test_target_version_filters(self, tmp_migrations, mock_connection):
        conn, cursor = mock_connection
        cursor.fetchone.return_value = (True,)

        (tmp_migrations / "001_foo.verify.sql").write_text("SELECT true")
        (tmp_migrations / "002_bar.verify.sql").write_text("SELECT true")

        verifier = MigrationVerifier(connection=conn, migrations_dir=tmp_migrations)
        results = verifier.verify_all(["001", "002"], target_version="001")
        assert len(results) == 1
        assert results[0].version == "001"

    def test_no_file_is_skipped(self, tmp_migrations, mock_connection):
        conn, cursor = mock_connection

        # No verify file for version 001
        verifier = MigrationVerifier(connection=conn, migrations_dir=tmp_migrations)
        results = verifier.verify_all(["001"])
        assert len(results) == 1
        assert results[0].status == "no_file"
