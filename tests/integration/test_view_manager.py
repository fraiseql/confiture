"""Integration tests for ViewManager — view dependency management.

Tests require a running PostgreSQL server accessible via CONFITURE_TEST_DB_URL.
"""

import psycopg
import pytest


@pytest.fixture
def vm_db(clean_test_db: psycopg.Connection) -> psycopg.Connection:
    """Provide a clean database with extra cleanup for confiture schema."""
    conn = clean_test_db

    # Also drop extra schemas and materialized views from previous tests
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS confiture CASCADE")
        cur.execute("DROP SCHEMA IF EXISTS catalog CASCADE")
        # Drop materialized views separately (clean_test_db only drops regular views)
        cur.execute("""
            SELECT schemaname, matviewname FROM pg_matviews
            WHERE schemaname = 'public'
        """)
        for schema, name in cur.fetchall():
            cur.execute(f'DROP MATERIALIZED VIEW IF EXISTS "{schema}"."{name}" CASCADE')
    conn.commit()

    yield conn

    # Cleanup after test
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS confiture CASCADE")
        cur.execute("DROP SCHEMA IF EXISTS catalog CASCADE")
    conn.commit()


def _create_base_tables(conn: psycopg.Connection) -> None:
    """Create base tables used by most tests."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE tb_machine (
                pk_machine INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT DEFAULT 'active'
            )
        """)
        cur.execute("""
            CREATE TABLE tb_part (
                pk_part INTEGER PRIMARY KEY,
                fk_machine INTEGER REFERENCES tb_machine(pk_machine),
                label TEXT NOT NULL
            )
        """)
    conn.commit()


class TestDiscoverDependentViews:
    """Test recursive view dependency discovery."""

    def test_discover_direct_view_dependency(self, vm_db: psycopg.Connection) -> None:
        """A view directly depending on a table is discovered at depth 0."""
        from confiture.core.view_manager import ViewManager

        _create_base_tables(vm_db)
        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE VIEW v_machine AS
                SELECT pk_machine, name FROM tb_machine
            """)
        vm_db.commit()

        vm = ViewManager(vm_db)
        views = vm.discover_dependent_views(schemas=["public"])

        assert len(views) == 1
        assert views[0].name == "v_machine"
        assert views[0].schema == "public"
        assert views[0].depth == 0

    def test_discover_transitive_view_dependency(self, vm_db: psycopg.Connection) -> None:
        """Views-on-views are discovered with correct depth ordering."""
        from confiture.core.view_manager import ViewManager

        _create_base_tables(vm_db)
        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE VIEW v_machine AS
                SELECT pk_machine, name FROM tb_machine
            """)
            cur.execute("""
                CREATE VIEW v_machine_summary AS
                SELECT name, pk_machine FROM v_machine WHERE pk_machine > 0
            """)
        vm_db.commit()

        vm = ViewManager(vm_db)
        views = vm.discover_dependent_views(schemas=["public"])

        assert len(views) == 2
        # Deeper views should come first (for drop order)
        names = [v.name for v in views]
        assert "v_machine" in names
        assert "v_machine_summary" in names

        # v_machine_summary depends on v_machine, so it should have higher depth
        depth_map = {v.name: v.depth for v in views}
        assert depth_map["v_machine_summary"] > depth_map["v_machine"]

    def test_discover_materialized_view(self, vm_db: psycopg.Connection) -> None:
        """Materialized views are included in dependency discovery."""
        from confiture.core.view_manager import ViewManager

        _create_base_tables(vm_db)
        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE MATERIALIZED VIEW mv_machine_stats AS
                SELECT status, COUNT(*) AS cnt FROM tb_machine GROUP BY status
            """)
        vm_db.commit()

        vm = ViewManager(vm_db)
        views = vm.discover_dependent_views(schemas=["public"])

        assert len(views) == 1
        assert views[0].name == "mv_machine_stats"
        assert views[0].kind == "m"

    def test_discover_no_views(self, vm_db: psycopg.Connection) -> None:
        """Tables with no dependent views return empty list."""
        from confiture.core.view_manager import ViewManager

        _create_base_tables(vm_db)

        vm = ViewManager(vm_db)
        views = vm.discover_dependent_views(schemas=["public"])

        assert views == []

    def test_discover_partitioned_table_views(self, vm_db: psycopg.Connection) -> None:
        """Views on partitioned tables are discovered."""
        from confiture.core.view_manager import ViewManager

        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE TABLE tb_events (
                    id INTEGER NOT NULL,
                    event_date DATE NOT NULL,
                    label TEXT
                ) PARTITION BY RANGE (event_date)
            """)
            cur.execute("""
                CREATE TABLE tb_events_2024 PARTITION OF tb_events
                FOR VALUES FROM ('2024-01-01') TO ('2025-01-01')
            """)
            cur.execute("""
                CREATE VIEW v_events AS
                SELECT id, label FROM tb_events
            """)
        vm_db.commit()

        vm = ViewManager(vm_db)
        views = vm.discover_dependent_views(schemas=["public"])

        assert len(views) == 1
        assert views[0].name == "v_events"


class TestSaveAndDropDependentViews:
    """Test saving view definitions and dropping views."""

    def test_save_and_drop_basic_view(self, vm_db: psycopg.Connection) -> None:
        """A basic view is saved and dropped successfully."""
        from confiture.core.view_manager import ViewManager

        _create_base_tables(vm_db)
        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE VIEW v_machine AS
                SELECT pk_machine, name FROM tb_machine
            """)
        vm_db.commit()

        vm = ViewManager(vm_db)
        count = vm.save_and_drop_dependent_views(schemas=["public"])

        assert count == 1

        # View should be gone
        with vm_db.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM pg_views
                WHERE schemaname = 'public' AND viewname = 'v_machine'
            """)
            assert cur.fetchone()[0] == 0

    def test_save_captures_materialized_view_indexes(self, vm_db: psycopg.Connection) -> None:
        """Materialized view indexes are captured during save."""
        from confiture.core.view_manager import ViewManager

        _create_base_tables(vm_db)
        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE MATERIALIZED VIEW mv_machine_stats AS
                SELECT status, COUNT(*) AS cnt FROM tb_machine GROUP BY status
            """)
            cur.execute("""
                CREATE UNIQUE INDEX idx_mv_machine_stats_status
                ON mv_machine_stats (status)
            """)
        vm_db.commit()

        vm = ViewManager(vm_db)
        count = vm.save_and_drop_dependent_views(schemas=["public"])

        assert count == 1

        # Check that index DDL was saved
        saved = vm.get_saved_views()
        assert len(saved) == 1
        assert saved[0].indexes  # Should have at least one index

    def test_save_captures_comments(self, vm_db: psycopg.Connection) -> None:
        """View comments are preserved during save."""
        from confiture.core.view_manager import ViewManager

        _create_base_tables(vm_db)
        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE VIEW v_machine AS
                SELECT pk_machine, name FROM tb_machine
            """)
            cur.execute("COMMENT ON VIEW v_machine IS 'Machine summary view'")
        vm_db.commit()

        vm = ViewManager(vm_db)
        vm.save_and_drop_dependent_views(schemas=["public"])

        saved = vm.get_saved_views()
        assert len(saved) == 1
        assert saved[0].comment == "Machine summary view"

    def test_drop_order_respects_depth(self, vm_db: psycopg.Connection) -> None:
        """Views are dropped deepest-first to avoid dependency errors."""
        from confiture.core.view_manager import ViewManager

        _create_base_tables(vm_db)
        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE VIEW v_machine AS
                SELECT pk_machine, name FROM tb_machine
            """)
            cur.execute("""
                CREATE VIEW v_machine_top AS
                SELECT name FROM v_machine LIMIT 10
            """)
        vm_db.commit()

        vm = ViewManager(vm_db)
        count = vm.save_and_drop_dependent_views(schemas=["public"])

        # Both should be dropped without error (correct order)
        assert count == 2
        with vm_db.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM pg_views
                WHERE schemaname = 'public'
            """)
            assert cur.fetchone()[0] == 0


class TestRecreateSavedViews:
    """Test recreating views from saved definitions."""

    def test_recreate_basic_view(self, vm_db: psycopg.Connection) -> None:
        """A basic view is recreated after save-drop-alter cycle."""
        from confiture.core.view_manager import ViewManager

        _create_base_tables(vm_db)
        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE VIEW v_machine AS
                SELECT pk_machine, name FROM tb_machine
            """)
        vm_db.commit()

        vm = ViewManager(vm_db)
        vm.save_and_drop_dependent_views(schemas=["public"])

        # ALTER the table (the whole point)
        with vm_db.cursor() as cur:
            cur.execute("ALTER TABLE tb_machine ALTER COLUMN pk_machine TYPE BIGINT")
        vm_db.commit()

        # Recreate
        count = vm.recreate_saved_views()
        assert count == 1

        # View should exist again
        with vm_db.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM pg_views
                WHERE schemaname = 'public' AND viewname = 'v_machine'
            """)
            assert cur.fetchone()[0] == 1

    def test_recreate_transitive_views(self, vm_db: psycopg.Connection) -> None:
        """Views-on-views are recreated in correct forward order."""
        from confiture.core.view_manager import ViewManager

        _create_base_tables(vm_db)
        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE VIEW v_machine AS
                SELECT pk_machine, name FROM tb_machine
            """)
            cur.execute("""
                CREATE VIEW v_machine_summary AS
                SELECT name FROM v_machine
            """)
        vm_db.commit()

        vm = ViewManager(vm_db)
        vm.save_and_drop_dependent_views(schemas=["public"])

        with vm_db.cursor() as cur:
            cur.execute("ALTER TABLE tb_machine ALTER COLUMN pk_machine TYPE BIGINT")
        vm_db.commit()

        count = vm.recreate_saved_views()
        assert count == 2

        # Both views should exist
        with vm_db.cursor() as cur:
            cur.execute("""
                SELECT viewname FROM pg_views
                WHERE schemaname = 'public' ORDER BY viewname
            """)
            names = [row[0] for row in cur.fetchall()]
            assert "v_machine" in names
            assert "v_machine_summary" in names

    def test_recreate_materialized_view_with_index(self, vm_db: psycopg.Connection) -> None:
        """Materialized views are recreated with their indexes."""
        from confiture.core.view_manager import ViewManager

        _create_base_tables(vm_db)
        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE MATERIALIZED VIEW mv_machine_stats AS
                SELECT status, COUNT(*) AS cnt FROM tb_machine GROUP BY status
            """)
            cur.execute("""
                CREATE UNIQUE INDEX idx_mv_machine_stats_status
                ON mv_machine_stats (status)
            """)
        vm_db.commit()

        vm = ViewManager(vm_db)
        vm.save_and_drop_dependent_views(schemas=["public"])

        count = vm.recreate_saved_views()
        assert count == 1

        # Check materialized view exists
        with vm_db.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM pg_matviews
                WHERE schemaname = 'public' AND matviewname = 'mv_machine_stats'
            """)
            assert cur.fetchone()[0] == 1

            # Check index was recreated
            cur.execute("""
                SELECT COUNT(*) FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = 'idx_mv_machine_stats_status'
            """)
            assert cur.fetchone()[0] == 1

    def test_recreate_restores_comments(self, vm_db: psycopg.Connection) -> None:
        """View comments are restored after recreation."""
        from confiture.core.view_manager import ViewManager

        _create_base_tables(vm_db)
        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE VIEW v_machine AS
                SELECT pk_machine, name FROM tb_machine
            """)
            cur.execute("COMMENT ON VIEW v_machine IS 'Machine summary view'")
        vm_db.commit()

        vm = ViewManager(vm_db)
        vm.save_and_drop_dependent_views(schemas=["public"])

        with vm_db.cursor() as cur:
            cur.execute("ALTER TABLE tb_machine ALTER COLUMN pk_machine TYPE BIGINT")
        vm_db.commit()

        vm.recreate_saved_views()

        # Check comment was restored
        with vm_db.cursor() as cur:
            cur.execute("""
                SELECT obj_description(c.oid)
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = 'v_machine'
            """)
            assert cur.fetchone()[0] == "Machine summary view"

    def test_full_alter_column_type_workflow(self, vm_db: psycopg.Connection) -> None:
        """End-to-end: save views, ALTER multiple columns, recreate views."""
        from confiture.core.view_manager import ViewManager

        # Create a realistic schema
        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE TABLE tb_machine (
                    pk_machine INTEGER PRIMARY KEY,
                    name TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE tb_part (
                    pk_part INTEGER PRIMARY KEY,
                    fk_machine INTEGER REFERENCES tb_machine(pk_machine),
                    label TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE VIEW v_machine_parts AS
                SELECT m.pk_machine, m.name, p.label
                FROM tb_machine m
                JOIN tb_part p ON p.fk_machine = m.pk_machine
            """)
            cur.execute("""
                CREATE MATERIALIZED VIEW mv_part_count AS
                SELECT fk_machine, COUNT(*) AS cnt
                FROM tb_part GROUP BY fk_machine
            """)
            cur.execute("""
                CREATE UNIQUE INDEX idx_mv_part_count_fk
                ON mv_part_count (fk_machine)
            """)
            cur.execute("COMMENT ON VIEW v_machine_parts IS 'Machine parts joined view'")
            cur.execute("COMMENT ON MATERIALIZED VIEW mv_part_count IS 'Part count per machine'")
        vm_db.commit()

        vm = ViewManager(vm_db)

        # Step 1: Save and drop
        dropped = vm.save_and_drop_dependent_views(schemas=["public"])
        assert dropped >= 2

        # Step 2: ALTER columns (the reason we need this feature)
        with vm_db.cursor() as cur:
            cur.execute("ALTER TABLE tb_part DROP CONSTRAINT tb_part_fk_machine_fkey")
            cur.execute("ALTER TABLE tb_machine ALTER COLUMN pk_machine TYPE BIGINT")
            cur.execute("ALTER TABLE tb_part ALTER COLUMN pk_part TYPE BIGINT")
            cur.execute("ALTER TABLE tb_part ALTER COLUMN fk_machine TYPE BIGINT")
            cur.execute("""
                ALTER TABLE tb_part
                ADD CONSTRAINT tb_part_fk_machine_fkey
                FOREIGN KEY (fk_machine) REFERENCES tb_machine(pk_machine)
            """)
        vm_db.commit()

        # Step 3: Recreate
        recreated = vm.recreate_saved_views()
        assert recreated >= 2

        # Verify everything is back
        with vm_db.cursor() as cur:
            # Regular view exists
            cur.execute("""
                SELECT COUNT(*) FROM pg_views
                WHERE schemaname = 'public' AND viewname = 'v_machine_parts'
            """)
            assert cur.fetchone()[0] == 1

            # Materialized view exists
            cur.execute("""
                SELECT COUNT(*) FROM pg_matviews
                WHERE schemaname = 'public' AND matviewname = 'mv_part_count'
            """)
            assert cur.fetchone()[0] == 1

            # Index exists
            cur.execute("""
                SELECT COUNT(*) FROM pg_indexes
                WHERE indexname = 'idx_mv_part_count_fk'
            """)
            assert cur.fetchone()[0] == 1

            # Comments preserved
            cur.execute("""
                SELECT obj_description(c.oid)
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = 'v_machine_parts'
            """)
            assert cur.fetchone()[0] == "Machine parts joined view"


class TestInstallHelpers:
    """Test SQL helper function installation."""

    def test_install_creates_schema_and_functions(self, vm_db: psycopg.Connection) -> None:
        """install_helpers() creates confiture schema with helper functions."""
        from confiture.core.view_manager import ViewManager

        vm = ViewManager(vm_db)
        assert not vm.helpers_installed()

        vm.install_helpers()

        assert vm.helpers_installed()

        # Verify schema exists
        with vm_db.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM pg_namespace WHERE nspname = 'confiture'
            """)
            assert cur.fetchone()[0] == 1

    def test_install_is_idempotent(self, vm_db: psycopg.Connection) -> None:
        """install_helpers() can be called multiple times safely."""
        from confiture.core.view_manager import ViewManager

        vm = ViewManager(vm_db)
        vm.install_helpers()
        vm.install_helpers()  # Should not raise
        assert vm.helpers_installed()

    def test_sql_helpers_full_workflow(self, vm_db: psycopg.Connection) -> None:
        """SQL functions produce correct results for save-drop-alter-recreate."""
        from confiture.core.view_manager import ViewManager

        vm = ViewManager(vm_db)
        vm.install_helpers()

        # Create schema
        _create_base_tables(vm_db)
        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE VIEW v_machine AS
                SELECT pk_machine, name FROM tb_machine
            """)
            cur.execute("""
                CREATE MATERIALIZED VIEW mv_machine_stats AS
                SELECT status, COUNT(*) AS cnt FROM tb_machine GROUP BY status
            """)
            cur.execute("""
                CREATE UNIQUE INDEX idx_mv_stats_status ON mv_machine_stats (status)
            """)
            cur.execute("COMMENT ON VIEW v_machine IS 'Machine list'")
        vm_db.commit()

        # Use SQL functions directly
        with vm_db.cursor() as cur:
            cur.execute("SELECT confiture.save_and_drop_dependent_views(ARRAY['public'])")
            dropped = cur.fetchone()[0]
            assert dropped == 2
        vm_db.commit()

        # Views should be gone
        with vm_db.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM pg_views
                WHERE schemaname = 'public' AND viewname = 'v_machine'
            """)
            assert cur.fetchone()[0] == 0

        # ALTER column type
        with vm_db.cursor() as cur:
            cur.execute("ALTER TABLE tb_machine ALTER COLUMN pk_machine TYPE BIGINT")
        vm_db.commit()

        # Recreate using SQL function
        with vm_db.cursor() as cur:
            cur.execute("SELECT confiture.recreate_saved_views()")
            recreated = cur.fetchone()[0]
            assert recreated == 2
        vm_db.commit()

        # Verify views are back
        with vm_db.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM pg_views
                WHERE schemaname = 'public' AND viewname = 'v_machine'
            """)
            assert cur.fetchone()[0] == 1

            cur.execute("""
                SELECT COUNT(*) FROM pg_matviews
                WHERE schemaname = 'public' AND matviewname = 'mv_machine_stats'
            """)
            assert cur.fetchone()[0] == 1

            # Index restored
            cur.execute("""
                SELECT COUNT(*) FROM pg_indexes
                WHERE indexname = 'idx_mv_stats_status'
            """)
            assert cur.fetchone()[0] == 1

            # Comment restored
            cur.execute("""
                SELECT obj_description(c.oid)
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = 'v_machine'
            """)
            assert cur.fetchone()[0] == "Machine list"

    def test_sql_helpers_transitive_views(self, vm_db: psycopg.Connection) -> None:
        """SQL functions handle views-on-views correctly."""
        from confiture.core.view_manager import ViewManager

        vm = ViewManager(vm_db)
        vm.install_helpers()

        _create_base_tables(vm_db)
        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE VIEW v_machine AS
                SELECT pk_machine, name FROM tb_machine
            """)
            cur.execute("""
                CREATE VIEW v_machine_top AS
                SELECT name FROM v_machine LIMIT 5
            """)
        vm_db.commit()

        with vm_db.cursor() as cur:
            cur.execute("SELECT confiture.save_and_drop_dependent_views(ARRAY['public'])")
            assert cur.fetchone()[0] == 2
        vm_db.commit()

        with vm_db.cursor() as cur:
            cur.execute("ALTER TABLE tb_machine ALTER COLUMN pk_machine TYPE BIGINT")
        vm_db.commit()

        with vm_db.cursor() as cur:
            cur.execute("SELECT confiture.recreate_saved_views()")
            assert cur.fetchone()[0] == 2
        vm_db.commit()

        with vm_db.cursor() as cur:
            cur.execute("""
                SELECT viewname FROM pg_views
                WHERE schemaname = 'public' ORDER BY viewname
            """)
            names = [r[0] for r in cur.fetchall()]
            assert "v_machine" in names
            assert "v_machine_top" in names


class TestEdgeCases:
    """Test edge cases and hardening scenarios."""

    def test_materialized_view_with_data_is_refreshed(self, vm_db: psycopg.Connection) -> None:
        """Materialized views with data are recreated and refreshed."""
        from confiture.core.view_manager import ViewManager

        _create_base_tables(vm_db)
        with vm_db.cursor() as cur:
            # Insert data so the matview has rows
            cur.execute("INSERT INTO tb_machine VALUES (1, 'Machine A', 'active')")
            cur.execute("INSERT INTO tb_machine VALUES (2, 'Machine B', 'inactive')")
            cur.execute("""
                CREATE MATERIALIZED VIEW mv_machine_stats AS
                SELECT status, COUNT(*) AS cnt FROM tb_machine GROUP BY status
            """)
        vm_db.commit()

        # Verify matview has data
        with vm_db.cursor() as cur:
            cur.execute("SELECT SUM(cnt) FROM mv_machine_stats")
            assert cur.fetchone()[0] == 2

        vm = ViewManager(vm_db)
        vm.save_and_drop_dependent_views(schemas=["public"])

        with vm_db.cursor() as cur:
            cur.execute("ALTER TABLE tb_machine ALTER COLUMN pk_machine TYPE BIGINT")
        vm_db.commit()

        vm.recreate_saved_views()

        # Matview should have data (was refreshed)
        with vm_db.cursor() as cur:
            cur.execute("SELECT SUM(cnt) FROM mv_machine_stats")
            assert cur.fetchone()[0] == 2

    def test_view_with_special_characters_in_comment(self, vm_db: psycopg.Connection) -> None:
        """Comments containing single quotes are preserved correctly."""
        from confiture.core.view_manager import ViewManager

        _create_base_tables(vm_db)
        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE VIEW v_machine AS
                SELECT pk_machine, name FROM tb_machine
            """)
            cur.execute("COMMENT ON VIEW v_machine IS 'Machine''s summary view'")
        vm_db.commit()

        vm = ViewManager(vm_db)
        vm.save_and_drop_dependent_views(schemas=["public"])

        with vm_db.cursor() as cur:
            cur.execute("ALTER TABLE tb_machine ALTER COLUMN pk_machine TYPE BIGINT")
        vm_db.commit()

        vm.recreate_saved_views()

        with vm_db.cursor() as cur:
            cur.execute("""
                SELECT obj_description(c.oid)
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = 'v_machine'
            """)
            assert cur.fetchone()[0] == "Machine's summary view"

    def test_multiple_views_on_same_table(self, vm_db: psycopg.Connection) -> None:
        """Multiple independent views on the same table are all handled."""
        from confiture.core.view_manager import ViewManager

        _create_base_tables(vm_db)
        with vm_db.cursor() as cur:
            cur.execute("""
                CREATE VIEW v_machine_names AS
                SELECT pk_machine, name FROM tb_machine
            """)
            cur.execute("""
                CREATE VIEW v_machine_status AS
                SELECT pk_machine, status FROM tb_machine
            """)
            cur.execute("""
                CREATE VIEW v_machine_all AS
                SELECT * FROM tb_machine
            """)
        vm_db.commit()

        vm = ViewManager(vm_db)
        dropped = vm.save_and_drop_dependent_views(schemas=["public"])
        assert dropped == 3

        with vm_db.cursor() as cur:
            cur.execute("ALTER TABLE tb_machine ALTER COLUMN pk_machine TYPE BIGINT")
        vm_db.commit()

        recreated = vm.recreate_saved_views()
        assert recreated == 3

    def test_no_views_returns_zero(self, vm_db: psycopg.Connection) -> None:
        """save_and_drop with no dependent views returns 0 gracefully."""
        from confiture.core.view_manager import ViewManager

        _create_base_tables(vm_db)

        vm = ViewManager(vm_db)
        count = vm.save_and_drop_dependent_views(schemas=["public"])
        assert count == 0

        # Recreate should also return 0
        count = vm.recreate_saved_views()
        assert count == 0

    def test_schemas_default_none_scans_all_user_schemas(self, vm_db: psycopg.Connection) -> None:
        """Passing schemas=None discovers views across all user schemas."""
        from confiture.core.view_manager import ViewManager

        with vm_db.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS catalog")
            cur.execute("""
                CREATE TABLE catalog.tb_product (
                    pk_product INTEGER PRIMARY KEY, name TEXT
                )
            """)
            cur.execute("""
                CREATE VIEW public.v_all_products AS
                SELECT pk_product, name FROM catalog.tb_product
            """)
        vm_db.commit()

        vm = ViewManager(vm_db)
        # schemas=None should find the view
        views = vm.discover_dependent_views()
        assert len(views) >= 1
        assert any(v.name == "v_all_products" for v in views)

        # Full workflow with default
        dropped = vm.save_and_drop_dependent_views()
        assert dropped >= 1

        with vm_db.cursor() as cur:
            cur.execute("ALTER TABLE catalog.tb_product ALTER COLUMN pk_product TYPE BIGINT")
        vm_db.commit()

        recreated = vm.recreate_saved_views()
        assert recreated >= 1


class TestCrossSchemaViews:
    """Test views spanning multiple schemas."""

    def test_cross_schema_dependency(self, vm_db: psycopg.Connection) -> None:
        """Views in schema B depending on tables in schema A are handled."""
        from confiture.core.view_manager import ViewManager

        with vm_db.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS catalog")
            cur.execute("""
                CREATE TABLE catalog.tb_product (
                    pk_product INTEGER PRIMARY KEY,
                    name TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE VIEW public.v_product_list AS
                SELECT pk_product, name FROM catalog.tb_product
            """)
        vm_db.commit()

        vm = ViewManager(vm_db)
        views = vm.discover_dependent_views(schemas=["catalog", "public"])

        assert len(views) == 1
        assert views[0].name == "v_product_list"

    def test_cross_schema_save_drop_recreate(self, vm_db: psycopg.Connection) -> None:
        """Cross-schema views survive the full save-drop-alter-recreate cycle."""
        from confiture.core.view_manager import ViewManager

        with vm_db.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS catalog")
            cur.execute("""
                CREATE TABLE catalog.tb_product (
                    pk_product INTEGER PRIMARY KEY,
                    name TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE VIEW public.v_product_list AS
                SELECT pk_product, name FROM catalog.tb_product
            """)
        vm_db.commit()

        vm = ViewManager(vm_db)
        vm.save_and_drop_dependent_views(schemas=["catalog", "public"])

        with vm_db.cursor() as cur:
            cur.execute("ALTER TABLE catalog.tb_product ALTER COLUMN pk_product TYPE BIGINT")
        vm_db.commit()

        count = vm.recreate_saved_views()
        assert count == 1

        with vm_db.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM pg_views
                WHERE schemaname = 'public' AND viewname = 'v_product_list'
            """)
            assert cur.fetchone()[0] == 1
