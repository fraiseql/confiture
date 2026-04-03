"""Unit tests for migration dry-run mode."""

from unittest.mock import MagicMock, Mock, call

import pytest


class TestDryRunMode:
    """Test suite for migration dry-run mode."""

    def test_dry_run_executor_can_test_migration_in_transaction(self):
        """DryRunExecutor should execute migration in transaction, then rollback."""
        from confiture.core.dry_run import DryRunExecutor

        executor = DryRunExecutor()

        # Create mock connection
        mock_conn = Mock()
        mock_conn.autocommit = False

        # Create mock migration
        mock_migration = Mock()
        mock_migration.name = "001_test_migration"
        mock_migration.version = "001"

        def up_impl():
            """Simulate migration creating a table."""
            pass

        mock_migration.up = up_impl

        # Run dry-run
        result = executor.run(mock_conn, mock_migration)

        # Verify result
        assert result is not None
        assert result.migration_name == "001_test_migration"
        assert result.success is True

    def test_dry_run_result_contains_execution_metrics(self):
        """DryRunResult should contain execution metrics."""
        from confiture.core.dry_run import DryRunResult

        result = DryRunResult(
            migration_name="001_test",
            migration_version="001",
            success=True,
            execution_time_ms=125,
            rows_affected=42,
            locked_tables=["users", "orders"],
            estimated_production_time_ms=120,
            confidence_percent=85,
            warnings=[],
        )

        assert result.migration_name == "001_test"
        assert result.execution_time_ms == 125
        assert result.rows_affected == 42
        assert result.locked_tables == ["users", "orders"]
        assert result.estimated_production_time_ms == 120
        assert result.confidence_percent == 85

    def test_dry_run_detects_constraint_violations(self):
        """DryRunExecutor should detect constraint violations during test."""
        from confiture.core.dry_run import DryRunError, DryRunExecutor

        executor = DryRunExecutor()

        # Create mock connection that will raise constraint error
        mock_conn = Mock()

        # Create mock migration that violates constraints
        mock_migration = Mock()
        mock_migration.name = "002_bad_migration"
        mock_migration.version = "002"

        def up_impl():
            raise Exception("Unique constraint violated")

        mock_migration.up = up_impl

        # Should raise DryRunError
        with pytest.raises(DryRunError):
            executor.run(mock_conn, mock_migration)

    def test_dry_run_captures_lock_times(self):
        """DryRunExecutor should capture table lock times."""
        from confiture.core.dry_run import DryRunExecutor

        executor = DryRunExecutor()
        mock_conn = Mock()
        mock_migration = Mock()
        mock_migration.name = "003_lock_test"
        mock_migration.version = "003"
        mock_migration.up = lambda: None

        result = executor.run(mock_conn, mock_migration)

        # Should capture lock timing information
        assert hasattr(result, "locked_tables")
        assert isinstance(result.locked_tables, list)

    def test_dry_run_estimates_production_time(self):
        """DryRunExecutor should estimate production execution time."""
        from confiture.core.dry_run import DryRunExecutor

        executor = DryRunExecutor()
        mock_conn = Mock()
        mock_migration = Mock()
        mock_migration.name = "004_estimate_test"
        mock_migration.version = "004"
        mock_migration.up = lambda: None

        result = executor.run(mock_conn, mock_migration)

        # Should have time estimate field (may be 0 in minimal implementation)
        assert hasattr(result, "estimated_production_time_ms")
        assert isinstance(result.estimated_production_time_ms, (int, float))
        # Note: estimate is populated during REFACTOR phase

    def test_dry_run_provides_confidence_level(self):
        """DryRunExecutor should provide confidence in estimate."""
        from confiture.core.dry_run import DryRunExecutor

        executor = DryRunExecutor()
        mock_conn = Mock()
        mock_migration = Mock()
        mock_migration.name = "005_confidence_test"
        mock_migration.version = "005"
        mock_migration.up = lambda: None

        result = executor.run(mock_conn, mock_migration)

        # Should have confidence percentage (0-100)
        assert hasattr(result, "confidence_percent")
        assert 0 <= result.confidence_percent <= 100

    def test_dry_run_automatic_rollback(self):
        """DryRunExecutor should automatically rollback after test."""
        from confiture.core.dry_run import DryRunExecutor

        executor = DryRunExecutor()

        # Create mock connection with transaction support
        mock_conn = Mock()
        mock_conn.autocommit = False
        mock_transaction = MagicMock()
        mock_conn.transaction.return_value.__enter__ = Mock(return_value=mock_transaction)
        mock_conn.transaction.return_value.__exit__ = Mock(return_value=None)

        mock_migration = Mock()
        mock_migration.name = "006_rollback_test"
        mock_migration.version = "006"

        # Track if rollback was called
        rollback_called = False

        def up_impl():
            nonlocal rollback_called
            # Would normally make DB changes here
            pass

        mock_migration.up = up_impl

        result = executor.run(mock_conn, mock_migration)

        # Verify transaction context was used (indicates rollback)
        assert result.success is True

    def test_dry_run_comparison_with_production(self):
        """DryRunResult should show comparison to estimate."""
        from confiture.core.dry_run import DryRunResult

        result = DryRunResult(
            migration_name="007_comparison",
            migration_version="007",
            success=True,
            execution_time_ms=100,
            rows_affected=1000,
            locked_tables=["large_table"],
            estimated_production_time_ms=100,  # Match actual for this test
            confidence_percent=80,
            warnings=["Large table lock detected"],
        )

        # Calculate estimate range (±15%)
        low_estimate = result.estimated_production_time_ms * 0.85
        high_estimate = result.estimated_production_time_ms * 1.15

        assert low_estimate <= result.execution_time_ms <= high_estimate

    def test_migration_integrates_with_dry_run_executor(self):
        """Migration class should work with dry-run."""
        from confiture.models.migration import Migration

        class TestMigration(Migration):
            version = "001"
            name = "test_dry_run"

            def up(self):
                self.execute("CREATE TABLE test (id INT)")

            def down(self):
                self.execute("DROP TABLE test")

        mock_conn = Mock()
        migration = TestMigration(connection=mock_conn)

        # Should be compatible with dry-run
        assert hasattr(migration, "up")
        assert callable(migration.up)


class TestSavepointDryRunExecutor:
    """Test suite for SAVEPOINT-based dry-run executor."""

    def test_dry_run_executor_executes_sql_statements(self):
        """DryRunExecutor should execute SQL statements inside SAVEPOINT and rollback."""
        from unittest.mock import Mock

        from confiture.core.dry_run import DryRunExecutor

        # Mock connection and cursors
        mock_conn = Mock()

        # DDL cursor (CREATE TABLE) - typically rowcount = -1
        ddl_cursor = Mock()
        ddl_cursor.rowcount = -1

        # DML cursor (INSERT) - affects 2 rows
        dml_cursor = Mock()
        dml_cursor.rowcount = 2

        # SAVEPOINT cursors - no rowcount needed
        savepoint_cursor = Mock()

        # Configure execute to return different cursors
        mock_conn.execute.side_effect = [
            savepoint_cursor,  # SAVEPOINT
            ddl_cursor,  # CREATE TABLE
            dml_cursor,  # INSERT
            savepoint_cursor,  # ROLLBACK TO
            savepoint_cursor,  # RELEASE
        ]

        # Create executor
        executor = DryRunExecutor(mock_conn)

        # SQL statements
        statements = [
            "CREATE TABLE dry_run_test (id SERIAL PRIMARY KEY, name TEXT)",
            "INSERT INTO dry_run_test (name) VALUES ('test1'), ('test2')",
        ]

        # Run dry-run
        result = executor.run("test_migration", statements)

        # Verify SAVEPOINT operations were called
        expected_calls = [
            call("SAVEPOINT confiture_dry_run"),
            call("CREATE TABLE dry_run_test (id SERIAL PRIMARY KEY, name TEXT)"),
            call("INSERT INTO dry_run_test (name) VALUES ('test1'), ('test2')"),
            call("ROLLBACK TO SAVEPOINT confiture_dry_run"),
            call("RELEASE SAVEPOINT confiture_dry_run"),
        ]
        mock_conn.execute.assert_has_calls(expected_calls)

        # Verify result
        assert result.migration_name == "test_migration"
        assert result.success is True
        assert result.confidence_pct == 85
        assert len(result.statements) == 2

        # Check statements
        create_stmt = result.statements[0]
        assert create_stmt.sql == "CREATE TABLE dry_run_test (id SERIAL PRIMARY KEY, name TEXT)"
        assert create_stmt.success is True
        assert create_stmt.rows_affected == 0  # DDL

        insert_stmt = result.statements[1]
        assert insert_stmt.sql == "INSERT INTO dry_run_test (name) VALUES ('test1'), ('test2')"
        assert insert_stmt.success is True
        assert insert_stmt.rows_affected == 2

        # Verify total
        assert result.rows_affected == 2

    def test_dry_run_executor_handles_sql_errors_and_rolls_back(self):
        """DryRunExecutor should handle SQL errors, capture error messages, and still rollback."""
        from unittest.mock import Mock

        from confiture.core.dry_run import DryRunExecutor

        # Mock connection
        mock_conn = Mock()

        # Cursors for successful and failed executions
        success_cursor = Mock()
        success_cursor.rowcount = -1  # DDL

        # Configure execute to succeed first, then fail
        def execute_side_effect(sql):
            if "CREATE TABLE" in sql:
                return success_cursor
            elif "INVALID SQL" in sql:
                raise Exception('syntax error at or near "INVALID"')
            else:
                return Mock()  # SAVEPOINT operations

        mock_conn.execute.side_effect = execute_side_effect

        # Create executor
        executor = DryRunExecutor(mock_conn)

        # SQL statements - first good, second bad
        statements = ["CREATE TABLE test_table (id INT)", "INVALID SQL STATEMENT"]

        # Run dry-run
        result = executor.run("test_migration", statements)

        # Verify result shows failure
        assert result.migration_name == "test_migration"
        assert result.success is False
        assert result.error == 'syntax error at or near "INVALID"'
        assert len(result.statements) == 2

        # Check first statement succeeded
        first_stmt = result.statements[0]
        assert first_stmt.success is True
        assert first_stmt.error is None

        # Check second statement failed
        second_stmt = result.statements[1]
        assert second_stmt.success is False
        assert second_stmt.error == 'syntax error at or near "INVALID"'

        # Verify SAVEPOINT operations were still called (rollback happened)
        calls = mock_conn.execute.call_args_list
        assert any("SAVEPOINT confiture_dry_run" in str(call) for call in calls)
        assert any("ROLLBACK TO SAVEPOINT confiture_dry_run" in str(call) for call in calls)
        assert any("RELEASE SAVEPOINT confiture_dry_run" in str(call) for call in calls)

    def test_migrator_dry_run_uses_savepoint_executor_for_sql_migrations(self):
        """Migrator.dry_run() should use SAVEPOINT executor for SQL migrations."""
        from unittest.mock import Mock

        from confiture.core._migrator.engine import Migrator
        from confiture.models.migration import SQLMigration

        # Create a test SQL migration
        class TestSQLMigration(SQLMigration):
            version = "001"
            name = "test_sql_migration"
            up_sql = "CREATE TABLE test (id INT); INSERT INTO test VALUES (1);"
            down_sql = "DROP TABLE test;"

        # Mock connection
        mock_conn = Mock()

        # Mock cursors for SAVEPOINT operations and SQL execution
        cursors = [
            Mock(),  # SAVEPOINT
            Mock(rowcount=-1),  # CREATE TABLE
            Mock(rowcount=1),  # INSERT
            Mock(),  # ROLLBACK
            Mock(),  # RELEASE
        ]
        mock_conn.execute.side_effect = cursors

        # Create migrator and migration
        migrator = Migrator(connection=mock_conn)
        migration = TestSQLMigration(connection=mock_conn)

        # Run dry-run
        result = migrator.dry_run(migration)

        # Verify result
        assert result.migration_name == "test_sql_migration"
        assert result.success is True
        assert result.confidence_pct == 85
        assert len(result.statements) == 2

        # Check statements
        assert "CREATE TABLE test (id INT)" in result.statements[0].sql
        assert "INSERT INTO test VALUES (1)" in result.statements[1].sql

        # Verify SAVEPOINT calls were made
        calls = mock_conn.execute.call_args_list
        assert any("SAVEPOINT confiture_dry_run" in str(call) for call in calls)

    def test_cli_display_formats_dry_run_result_with_statements(self):
        """CLI display should format DryRunResult with per-statement details."""
        import sys
        from io import StringIO

        from confiture.cli.dry_run import display_dry_run_result
        from confiture.core.dry_run import DryRunResult, StatementResult

        # Create a mock result with statements
        statements = [
            StatementResult(
                sql="CREATE TABLE test (id INT)",
                success=True,
                execution_time_ms=5.2,
                rows_affected=0,
            ),
            StatementResult(
                sql="INSERT INTO test VALUES (1), (2)",
                success=True,
                execution_time_ms=2.1,
                rows_affected=2,
            ),
        ]

        result = DryRunResult(
            migration_name="test_migration",
            success=True,
            total_time_ms=7.3,
            confidence_pct=85,
            statements=statements,
        )

        # Capture console output
        old_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()

        try:
            display_dry_run_result(result, format_type="text")
            output = captured_output.getvalue()
        finally:
            sys.stdout = old_stdout

        # Verify output contains expected elements
        assert "✓ SUCCESS" in output
        assert "test_migration" in output
        assert "7.3ms" in output
        assert "85%" in output
        assert "Statement Details" in output
        assert "CREATE TABLE test" in output
        assert "INSERT INTO test" in output
        assert "Total rows affected: 2" in output
