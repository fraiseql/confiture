"""Levels 4 and 5 check the table each resolver fills, in whatever schema (#458).

The issue's repro: ``catalog.tb_color`` is shared reference data,
``tenant.tb_widget`` a per-tenant table, and the one widget seeded points at a
color that is not seeded, so after resolution ``tenant.tb_widget.fk_color`` is
NULL. Level 4 reported ``catalog.tb_widget`` missing, and level 5's NULL-FK
check never looked at ``tenant.tb_widget``: the real CRITICAL was missed.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg

from confiture import platform
from confiture.core.seed.validation.prep_seed.models import PrepSeedPattern, ViolationSeverity

TABLES = """
CREATE SCHEMA catalog; CREATE SCHEMA tenant; CREATE SCHEMA prep_seed;
CREATE TABLE catalog.tb_color (
    pk_color BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID NOT NULL UNIQUE,
    name TEXT NOT NULL
);
CREATE TABLE tenant.tb_widget (
    pk_widget BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID NOT NULL UNIQUE,
    fk_color BIGINT REFERENCES catalog.tb_color (pk_color)
);
CREATE TABLE prep_seed.tb_color (id UUID NOT NULL, name TEXT NOT NULL);
CREATE TABLE prep_seed.tb_widget (id UUID NOT NULL, fk_color_id UUID);

CREATE FUNCTION catalog.fn_resolve_tb_color() RETURNS void LANGUAGE plpgsql AS $$
BEGIN INSERT INTO catalog.tb_color (id, name) SELECT id, name FROM prep_seed.tb_color; END $$;
CREATE FUNCTION tenant.fn_resolve_tb_widget() RETURNS void LANGUAGE plpgsql AS $$
BEGIN INSERT INTO tenant.tb_widget (id, fk_color)
      SELECT w.id, c.pk_color FROM prep_seed.tb_widget w
      LEFT JOIN catalog.tb_color c ON c.id = w.fk_color_id; END $$;
"""

COLOR = "00000000-0000-0000-0000-000000000001"

SEEDS = f"""
INSERT INTO prep_seed.tb_color (id, name) VALUES ('{COLOR}', 'red');
INSERT INTO prep_seed.tb_widget (id, fk_color_id)
VALUES ('00000000-0000-0000-0000-000000000002', '{{color}}');
"""

#: A color that is not seeded: the widget's ``fk_color`` resolves to NULL.
DANGLING = "00000000-0000-0000-0000-000000000009"


def _run(
    tmp_path: Path, fresh_database_factory: Callable[[str], str], ddl: str, color: str
) -> platform.PrepSeedReport:
    url = fresh_database_factory("prep_final")
    with psycopg.connect(url) as conn:
        conn.execute(ddl)
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "10_tables.sql").write_text(ddl)
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "10_seed.sql").write_text(SEEDS.replace("{color}", color))
    return platform.validate_seeds(seeds, schema_dir=schema, max_level=5, database=url)


def _found(report: platform.PrepSeedReport) -> list[tuple[str, str, str]]:
    return [(v.severity.name, v.pattern.name, v.message) for v in report.violations]


def test_a_null_fk_in_a_table_outside_catalog_schema_is_critical(
    tmp_path: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    report = _run(tmp_path, fresh_database_factory, TABLES, DANGLING)
    assert _found(report) == [
        (
            "CRITICAL",
            "NULL_FK_AFTER_RESOLUTION",
            "Found 1 NULL values in tenant.tb_widget.fk_color after resolution",
        )
    ]


def test_the_control_all_in_catalog_is_still_critical(
    tmp_path: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    report = _run(tmp_path, fresh_database_factory, TABLES.replace("tenant.", "catalog."), DANGLING)
    assert _found(report) == [
        (
            "CRITICAL",
            "NULL_FK_AFTER_RESOLUTION",
            "Found 1 NULL values in catalog.tb_widget.fk_color after resolution",
        )
    ]


def test_a_clean_multi_schema_tree_reports_nothing(
    tmp_path: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    report = _run(tmp_path, fresh_database_factory, TABLES, COLOR)
    assert _found(report) == []


def test_resolvers_run_parents_first_across_schemas(
    tmp_path: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    """``tenant.tb_a`` references ``tenant.tb_b``: by name ``tb_a`` resolves
    first and its ``fk_b`` is NULL. Parents first is decided on the final tables,
    wherever they are."""
    ddl = """
CREATE SCHEMA tenant; CREATE SCHEMA prep_seed;
CREATE TABLE tenant.tb_b (pk_b BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, id UUID NOT NULL UNIQUE);
CREATE TABLE tenant.tb_a (pk_a BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, id UUID NOT NULL UNIQUE,
                          fk_b BIGINT REFERENCES tenant.tb_b (pk_b));
CREATE TABLE prep_seed.tb_b (id UUID NOT NULL);
CREATE TABLE prep_seed.tb_a (id UUID NOT NULL, fk_b_id UUID);
CREATE FUNCTION tenant.fn_resolve_tb_b() RETURNS void LANGUAGE plpgsql AS $$
BEGIN INSERT INTO tenant.tb_b (id) SELECT id FROM prep_seed.tb_b; END $$;
CREATE FUNCTION tenant.fn_resolve_tb_a() RETURNS void LANGUAGE plpgsql AS $$
BEGIN INSERT INTO tenant.tb_a (id, fk_b)
      SELECT a.id, b.pk_b FROM prep_seed.tb_a a LEFT JOIN tenant.tb_b b ON b.id = a.fk_b_id; END $$;
"""
    url = fresh_database_factory("prep_final")
    with psycopg.connect(url) as conn:
        conn.execute(ddl)
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "10_tables.sql").write_text(ddl)
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "10_seed.sql").write_text(
        f"INSERT INTO prep_seed.tb_b (id) VALUES ('{COLOR}');\n"
        f"INSERT INTO prep_seed.tb_a (id, fk_b_id) "
        f"VALUES ('00000000-0000-0000-0000-000000000002', '{COLOR}');\n"
    )
    report = platform.validate_seeds(seeds, schema_dir=schema, max_level=5, database=url)
    assert [v for v in report.violations if v.severity == ViolationSeverity.CRITICAL] == [], _found(
        report
    )
    assert not [v for v in report.violations if v.pattern == PrepSeedPattern.MISSING_FK_MAPPING]
