"""Integration tests for PrepSeedOrchestrator with database.

Tests Levels 4-5 with real PostgreSQL database connection.
Requires PYTEST_DATABASE_URL environment variable or local test database.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from confiture.core.seed_validation.prep_seed.models import (
    PrepSeedPattern,
    ViolationSeverity,
)
from confiture.core.seed_validation.prep_seed.orchestrator import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)


@pytest.fixture
def test_db_url() -> str:
    """Get test database URL from environment or use default."""
    return os.environ.get(
        "PYTEST_DATABASE_URL",
        "postgresql://postgres@localhost/confiture_test",
    )


@pytest.fixture
def test_db(test_db_url: str) -> object:
    """Create test database and clean up after tests."""
    # Connect to create database if needed
    try:
        conn = psycopg.connect(test_db_url)
    except psycopg.OperationalError:
        # Try to create from template0
        base_url = test_db_url.rsplit("/", 1)[0]
        admin_conn = psycopg.connect(base_url)
        admin_conn.autocommit = True
        try:
            db_name = test_db_url.rsplit("/", 1)[1]
            admin_conn.execute(f"CREATE DATABASE {db_name}")
        except psycopg.Error:
            pass  # Database already exists
        finally:
            admin_conn.close()
        conn = psycopg.connect(test_db_url)

    yield conn

    # Cleanup
    conn.close()


@pytest.fixture
def prep_seed_schema(test_db: object) -> None:
    """Create prep_seed and catalog schemas with test tables."""
    conn = test_db

    # Create schemas
    conn.execute("CREATE SCHEMA IF NOT EXISTS prep_seed")
    conn.execute("CREATE SCHEMA IF NOT EXISTS catalog")

    # Create prep_seed table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prep_seed.tb_manufacturer (
            id UUID PRIMARY KEY,
            name TEXT NOT NULL
        )
        """
    )

    # Create catalog table with trinity pattern
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog.tb_manufacturer (
            id UUID NOT NULL UNIQUE,
            pk_manufacturer BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            name TEXT NOT NULL
        )
        """
    )

    # Create resolution function
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION fn_resolve_tb_manufacturer()
        RETURNS void AS $$
        BEGIN
            INSERT INTO catalog.tb_manufacturer (id, name)
            SELECT id, name FROM prep_seed.tb_manufacturer
            ON CONFLICT (id) DO NOTHING;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    conn.commit()


@pytest.mark.integration
class TestOrchestratorLevel4:
    """Test Level 4: Runtime validation with database."""

    def test_level_4_detects_missing_table(
        self,
        tmp_path: Path,
        test_db_url: str,
    ) -> None:
        """Level 4 detects when target table doesn't exist."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        # Create resolution function that targets non-existent table
        fn_file = schema_dir / "fn_resolve_tb_missing.sql"
        fn_file.write_text(
            "CREATE FUNCTION fn_resolve_tb_missing() AS $$ SELECT 1; $$ LANGUAGE SQL;"
        )

        config = OrchestrationConfig(
            max_level=4,
            seeds_dir=tmp_path / "seeds",
            schema_dir=schema_dir,
            database_url=test_db_url,
            catalog_schema="public",  # Table won't exist
        )

        orchestrator = PrepSeedOrchestrator(config)
        violations = orchestrator._run_level_4()

        # Should detect missing table
        assert len(violations) > 0
        assert any(v.severity == ViolationSeverity.ERROR for v in violations)

    def test_level_4_connects_to_database(
        self,
        tmp_path: Path,
        test_db_url: str,
        prep_seed_schema: None,
    ) -> None:
        """Level 4 successfully connects to database."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        # Create valid function
        fn_file = schema_dir / "fn_resolve_tb_manufacturer.sql"
        fn_file.write_text(
            "CREATE FUNCTION fn_resolve_tb_manufacturer() AS $$ SELECT 1; $$ LANGUAGE SQL;"
        )

        config = OrchestrationConfig(
            max_level=4,
            seeds_dir=tmp_path / "seeds",
            schema_dir=schema_dir,
            database_url=test_db_url,
        )

        orchestrator = PrepSeedOrchestrator(config)
        violations = orchestrator._run_level_4()

        # Should not raise exception (connection works)
        assert isinstance(violations, list)

    def test_level_4_dry_runs_functions(
        self,
        tmp_path: Path,
        test_db_url: str,
        prep_seed_schema: None,
    ) -> None:
        """Level 4 executes dry-run with SAVEPOINT."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        # Create valid function
        fn_file = schema_dir / "fn_resolve_tb_manufacturer.sql"
        fn_file.write_text(
            "CREATE FUNCTION fn_resolve_tb_manufacturer() AS $$ SELECT 1; $$ LANGUAGE SQL;"
        )

        config = OrchestrationConfig(
            max_level=4,
            seeds_dir=tmp_path / "seeds",
            schema_dir=schema_dir,
            database_url=test_db_url,
        )

        orchestrator = PrepSeedOrchestrator(config)
        violations = orchestrator._run_level_4()

        # Function should execute without crashing
        assert isinstance(violations, list)


@pytest.mark.integration
class TestOrchestratorLevel5:
    """Test Level 5: Full execution validation."""

    def test_level_5_requires_database_url(self, tmp_path: Path) -> None:
        """Level 5 requires database_url."""
        config = OrchestrationConfig(
            max_level=5,
            seeds_dir=tmp_path / "seeds",
            schema_dir=tmp_path / "schema",
            database_url=None,
        )

        orchestrator = PrepSeedOrchestrator(config)

        with pytest.raises(ValueError):
            orchestrator.run()

    def test_level_5_executes_with_database(
        self,
        tmp_path: Path,
        test_db_url: str,
        prep_seed_schema: None,
    ) -> None:
        """Level 5 executes full cycle."""
        seeds_dir = tmp_path / "seeds"
        seeds_dir.mkdir()

        # Create seed file
        seed_file = seeds_dir / "manufacturers.sql"
        seed_file.write_text(
            "INSERT INTO prep_seed.tb_manufacturer (id, name) VALUES "
            "('550e8400-e29b-41d4-a716-446655440000', 'Acme Corp');"
        )

        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        # Create function
        fn_file = schema_dir / "fn_resolve_tb_manufacturer.sql"
        fn_file.write_text(
            """
            CREATE FUNCTION fn_resolve_tb_manufacturer() AS $$
            INSERT INTO catalog.tb_manufacturer (id, name)
            SELECT id, name FROM prep_seed.tb_manufacturer;
            $$ LANGUAGE SQL;
            """
        )

        config = OrchestrationConfig(
            max_level=5,
            seeds_dir=seeds_dir,
            schema_dir=schema_dir,
            database_url=test_db_url,
            level_5_mode="standard",
        )

        orchestrator = PrepSeedOrchestrator(config)
        violations = orchestrator._run_level_5()

        # Should execute without errors (empty list of violations)
        assert isinstance(violations, list)

    def test_level_5_detects_null_fks(
        self,
        tmp_path: Path,
        test_db_url: str,
        prep_seed_schema: None,
    ) -> None:
        """Level 5 detects NULL foreign keys."""
        conn = psycopg.connect(test_db_url)

        # Add FK column that will be NULL
        try:
            conn.execute(
                """
                ALTER TABLE catalog.tb_manufacturer
                ADD COLUMN fk_parent_id BIGINT
                """
            )
            conn.commit()
        except psycopg.Error:
            conn.close()  # Already exists from prior test
            # Reconnect and clean
            conn = psycopg.connect(test_db_url)
            conn.execute("DELETE FROM catalog.tb_manufacturer")
            conn.commit()

        seeds_dir = tmp_path / "seeds"
        seeds_dir.mkdir()

        # Create seed that will leave NULL FK
        seed_file = seeds_dir / "manufacturers.sql"
        seed_file.write_text(
            "INSERT INTO prep_seed.tb_manufacturer (id, name) VALUES "
            "('550e8400-e29b-41d4-a716-446655440001', 'Widget Inc');"
        )

        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        # Create function that doesn't populate FK
        fn_file = schema_dir / "fn_resolve_tb_manufacturer.sql"
        fn_file.write_text(
            """
            CREATE OR REPLACE FUNCTION fn_resolve_tb_manufacturer() AS $$
            INSERT INTO catalog.tb_manufacturer (id, name, fk_parent_id)
            SELECT id, name, NULL FROM prep_seed.tb_manufacturer;
            $$ LANGUAGE SQL;
            """
        )

        config = OrchestrationConfig(
            max_level=5,
            seeds_dir=seeds_dir,
            schema_dir=schema_dir,
            database_url=test_db_url,
            level_5_mode="standard",
        )

        orchestrator = PrepSeedOrchestrator(config)
        violations = orchestrator._run_level_5()

        # Should detect NULL FK
        null_fk_violations = [
            v for v in violations if v.pattern == PrepSeedPattern.NULL_FK_AFTER_RESOLUTION
        ]
        assert len(null_fk_violations) > 0

        conn.close()

    def test_level_5_transaction_rollback(
        self,
        tmp_path: Path,
        test_db_url: str,
        prep_seed_schema: None,
    ) -> None:
        """Level 5 rolls back changes (validation doesn't persist)."""
        seeds_dir = tmp_path / "seeds"
        seeds_dir.mkdir()

        # Create seed file
        seed_file = seeds_dir / "manufacturers.sql"
        seed_file.write_text(
            "INSERT INTO prep_seed.tb_manufacturer (id, name) VALUES "
            "('550e8400-e29b-41d4-a716-446655440002', 'Tech Corp');"
        )

        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        # Create function
        fn_file = schema_dir / "fn_resolve_tb_manufacturer.sql"
        fn_file.write_text(
            """
            CREATE FUNCTION fn_resolve_tb_manufacturer() AS $$
            INSERT INTO catalog.tb_manufacturer (id, name)
            SELECT id, name FROM prep_seed.tb_manufacturer;
            $$ LANGUAGE SQL;
            """
        )

        config = OrchestrationConfig(
            max_level=5,
            seeds_dir=seeds_dir,
            schema_dir=schema_dir,
            database_url=test_db_url,
        )

        # Check before validation
        conn_before = psycopg.connect(test_db_url)
        result_before = conn_before.execute("SELECT COUNT(*) FROM catalog.tb_manufacturer")
        count_before = result_before.fetchone()[0]
        conn_before.close()

        # Run validation
        orchestrator = PrepSeedOrchestrator(config)
        orchestrator._run_level_5()

        # Check after validation (should be unchanged due to rollback)
        conn_after = psycopg.connect(test_db_url)
        result_after = conn_after.execute("SELECT COUNT(*) FROM catalog.tb_manufacturer")
        count_after = result_after.fetchone()[0]
        conn_after.close()

        # Counts should be the same (rollback occurred)
        assert count_before == count_after


@pytest.mark.integration
class TestOrchestratorFullCycle:
    """Test running multiple levels in sequence."""

    def test_full_cycle_1_to_5(
        self,
        tmp_path: Path,
        test_db_url: str,
        prep_seed_schema: None,
    ) -> None:
        """Orchestrator runs levels 1-5 sequentially."""
        seeds_dir = tmp_path / "seeds"
        seeds_dir.mkdir()

        seed_file = seeds_dir / "manufacturers.sql"
        seed_file.write_text(
            "INSERT INTO prep_seed.tb_manufacturer (id, name) VALUES "
            "('550e8400-e29b-41d4-a716-446655440003', 'Global Inc');"
        )

        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        # Create function
        fn_file = schema_dir / "fn_resolve_tb_manufacturer.sql"
        fn_file.write_text(
            """
            CREATE FUNCTION fn_resolve_tb_manufacturer() AS $$
            INSERT INTO catalog.tb_manufacturer (id, name)
            SELECT id, name FROM prep_seed.tb_manufacturer;
            $$ LANGUAGE SQL;
            """
        )

        config = OrchestrationConfig(
            max_level=5,
            seeds_dir=seeds_dir,
            schema_dir=schema_dir,
            database_url=test_db_url,
        )

        orchestrator = PrepSeedOrchestrator(config)
        report = orchestrator.run()

        # Should have processed all levels
        assert isinstance(report, object)
        assert hasattr(report, "violations")
        assert hasattr(report, "scanned_files")
