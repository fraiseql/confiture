"""Integration tests for SAVEPOINT-based dry-run executor."""


class TestDryRunSavepointIntegration:
    """Integration tests for SAVEPOINT dry-run with real database."""

    def test_dry_run_executes_real_sql_and_rolls_back(self, clean_test_db):
        """Integration test: DryRunExecutor executes real SQL and rolls back completely."""
        from confiture.core.dry_run import DryRunExecutor

        conn = clean_test_db

        # Create executor
        executor = DryRunExecutor(conn)

        # SQL statements that modify the database
        statements = [
            "CREATE TABLE integration_test (id SERIAL PRIMARY KEY, name TEXT NOT NULL)",
            "INSERT INTO integration_test (name) VALUES ('Alice'), ('Bob'), ('Charlie')",
            "CREATE INDEX idx_integration_test_name ON integration_test(name)",
            "UPDATE integration_test SET name = UPPER(name) WHERE id > 1",
        ]

        # Run dry-run
        result = executor.run("integration_test_migration", statements)

        # Verify result
        assert result.migration_name == "integration_test_migration"
        assert result.success is True
        assert result.confidence_pct == 85
        assert len(result.statements) == 4
        # Aggregate sums every statement's rowcount: 3 inserts + 2 updates.
        assert result.rows_affected == 5

        # Verify individual statements
        assert result.statements[0].rows_affected == 0  # CREATE TABLE
        assert result.statements[1].rows_affected == 3  # INSERT 3 rows
        assert result.statements[2].rows_affected == 0  # CREATE INDEX
        assert result.statements[3].rows_affected == 2  # UPDATE 2 rows

        # Most critical: verify NO data persists after dry-run
        with conn.cursor() as cur:
            # Check table doesn't exist
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'integration_test'
                )
            """)
            table_exists = cur.fetchone()[0]
            assert not table_exists, "Table should not exist after dry-run rollback"

            # Check index doesn't exist
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE schemaname = 'public' AND indexname = 'idx_integration_test_name'
                )
            """)
            index_exists = cur.fetchone()[0]
            assert not index_exists, "Index should not exist after dry-run rollback"

    def test_dry_run_fails_gracefully_on_constraint_violation(self, clean_test_db):
        """Integration test: DryRunExecutor handles constraint violations and rolls back."""
        from confiture.core.dry_run import DryRunExecutor

        conn = clean_test_db

        # First create a table with constraints (outside dry-run)
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE constraint_test (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL
                )
            """)
            cur.execute("INSERT INTO constraint_test (email) VALUES ('test@example.com')")
        conn.commit()

        try:
            executor = DryRunExecutor(conn)

            # SQL that will violate unique constraint
            statements = [
                "INSERT INTO constraint_test (email) VALUES ('test@example.com')"  # Duplicate!
            ]

            result = executor.run("constraint_violation_test", statements)

            # Should fail
            assert result.success is False
            assert (
                "unique constraint" in result.error.lower()
                or "duplicate key" in result.error.lower()
            )
            assert len(result.statements) == 1
            assert not result.statements[0].success
            assert result.statements[0].error

            # Verify rollback: the failed INSERT should not have persisted
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM constraint_test")
                count = cur.fetchone()[0]
                assert count == 1, "Failed INSERT should not have persisted"

        finally:
            # Cleanup
            with conn.cursor() as cur:
                cur.execute("DROP TABLE IF EXISTS constraint_test")
            conn.commit()
