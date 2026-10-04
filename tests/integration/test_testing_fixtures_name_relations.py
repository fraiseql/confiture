"""The test fixtures name the relation they were given, quoted, on a real server.

``DataValidator.get_row_count`` counts the rows of a bare or ``schema.table``
argument and ``MigrationRunner.get_applied_migrations`` reads the configured
ledger, bare or schema-qualified. Each composes a statement around a name, and
only PostgreSQL can say the statement reaches the relation meant: a name with
a capital is one PostgreSQL holds quoted, and an unquoted spelling of it is
another relation. ``get_row_count`` answers ``0`` for any error, so a count
that is not ``0`` is the proof the statement ran.
"""

from pathlib import Path

import psycopg

from confiture.core.schema_sources import read_schema
from confiture.core.seed.validation.prep_seed.level_4_runtime import Level4RuntimeValidator
from confiture.core.seed.validation.prep_seed.resolvers import find_resolvers
from confiture.testing.fixtures.data_validator import DataValidator
from confiture.testing.fixtures.migration_runner import MigrationRunner


def _widgets(conn: psycopg.Connection) -> None:
    conn.execute('CREATE SCHEMA "Shop"')
    conn.execute('CREATE TABLE "Shop"."Widget" (id INT)')
    conn.execute('INSERT INTO "Shop"."Widget" VALUES (1), (2), (3)')
    conn.execute('CREATE TABLE "Gadget" (id INT)')
    conn.execute('INSERT INTO "Gadget" VALUES (1), (2)')
    conn.commit()


def test_a_qualified_mixed_case_table_is_counted(clean_test_db: psycopg.Connection) -> None:
    _widgets(clean_test_db)
    assert DataValidator(clean_test_db).get_row_count("Shop.Widget") == 3


def test_a_bare_mixed_case_table_is_counted(clean_test_db: psycopg.Connection) -> None:
    _widgets(clean_test_db)
    assert DataValidator(clean_test_db).get_row_count("Gadget") == 2


def test_a_qualified_ledger_is_read(clean_test_db: psycopg.Connection) -> None:
    clean_test_db.execute("CREATE SCHEMA audit")
    clean_test_db.execute(
        "CREATE TABLE audit.tb_migrations (slug TEXT, applied_at TIMESTAMPTZ DEFAULT now())"
    )
    clean_test_db.execute(
        "INSERT INTO audit.tb_migrations (slug, applied_at) VALUES "
        "('002_b', '2026-01-02'), ('001_a', '2026-01-01')"
    )
    clean_test_db.commit()
    runner = MigrationRunner(clean_test_db, tracking_table="audit.tb_migrations")

    assert runner.get_applied_migrations() == ["001_a", "002_b"]


def test_an_absent_ledger_reads_as_nothing_applied(clean_test_db: psycopg.Connection) -> None:
    assert MigrationRunner(clean_test_db).get_applied_migrations() == []


def test_level_4_runs_under_a_savepoint_name_that_needs_quoting(
    clean_test_db: psycopg.Connection, tmp_path: Path
) -> None:
    ddl = (
        "CREATE TABLE tb_widget (id INT);\n"
        "CREATE FUNCTION fn_resolve_widget() RETURNS void LANGUAGE sql AS $$\n"
        "    INSERT INTO tb_widget VALUES (1);\n"
        "$$;\n"
    )
    clean_test_db.execute(ddl)
    (tmp_path / "widget.sql").write_text(ddl)
    (resolver,) = find_resolvers(read_schema(tmp_path), catalog_schema="catalog")

    validator = Level4RuntimeValidator()
    assert validator.dry_run_resolution(resolver, clean_test_db, savepoint_name="Sp 1") == []
    assert clean_test_db.execute("SELECT count(*) FROM tb_widget").fetchone() == (0,)
