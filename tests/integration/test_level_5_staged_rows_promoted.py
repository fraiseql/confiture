"""Level 5 reports a staged row the resolution does not promote (#666).

A resolver whose ``INNER JOIN`` finds no parent writes no row for that child: the
staged row is lost and nothing is NULL, so the NULL-FK check sees nothing. The same
stale UUID through a ``LEFT JOIN`` resolver is reported (a NULL FK, or the insert
failing), so whether a broken reference is caught depended on how the resolver was
written. Measured on PostgreSQL 18.4: of four staged customers, two point at a
category whose UUID a rebuild changed.
"""

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from confiture import platform
from confiture.core.seed.validation.prep_seed.orchestrator import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)

DDL = """
CREATE SCHEMA catalog; CREATE SCHEMA prep_seed;
CREATE TABLE catalog.tb_category (
    pk_category BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID NOT NULL UNIQUE,
    identifier TEXT NOT NULL UNIQUE
);
CREATE TABLE catalog.tb_customer (
    pk_customer BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID NOT NULL UNIQUE,
    identifier TEXT NOT NULL UNIQUE,
    fk_category BIGINT {nullability} REFERENCES catalog.tb_category (pk_category)
);
CREATE TABLE prep_seed.tb_customer (
    id UUID NOT NULL UNIQUE,
    identifier TEXT NOT NULL,
    fk_category_id UUID
);
INSERT INTO catalog.tb_category (id, identifier) VALUES
    ('00000000-0000-4000-8000-0000000000b0', 'books'),
    ('00000000-0000-4000-8000-0000000000c0', 'music');
CREATE FUNCTION catalog.fn_resolve_tb_customer() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO catalog.tb_customer (id, identifier, fk_category)
    SELECT s.id, s.identifier, k.pk_category
    FROM prep_seed.tb_customer AS s
    {join} JOIN catalog.tb_category AS k ON k.id = s.fk_category_id;
END $$;
"""

SEEDS = """
INSERT INTO prep_seed.tb_customer (id, identifier, fk_category_id) VALUES
    ('0c0d0e0f-0000-4000-8000-000000000001', 'c1', '00000000-0000-4000-8000-0000000000b0'),
    ('0c0d0e0f-0000-4000-8000-000000000002', 'c2', '00000000-0000-4000-8000-0000000000b0'),
    ('0c0d0e0f-0000-4000-8000-000000000003', 'c3', '00000000-0000-4000-8000-0000000000c0'),
    ('0c0d0e0f-0000-4000-8000-000000000004', 'c4', '00000000-0000-4000-8000-0000000000c0');
"""

#: A rebuild gives ``books`` a new UUID; the seeds still carry the old one.
STALE = "UPDATE catalog.tb_category SET id = gen_random_uuid() WHERE identifier = 'books'"


def _run(
    tmp_path: Path,
    fresh_database_factory: Callable[[str], str],
    *,
    nullability: str,
    join: str,
    stale: bool = True,
    mode: str = "standard",
) -> list[tuple[str, str, str]]:
    ddl = DDL.format(nullability=nullability, join=join)
    url = fresh_database_factory("prep_promoted")
    with psycopg.connect(url) as conn:
        conn.execute(ddl)
        if stale:
            conn.execute(STALE)
    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "10_tables.sql").write_text(ddl)
    (tmp_path / "seeds").mkdir()
    (tmp_path / "seeds" / "10_customers.sql").write_text(SEEDS)
    if mode == "standard":
        report = platform.validate_seeds(
            tmp_path / "seeds",
            schema_dir=tmp_path / "schema",
            max_level=5,
            database=url,
            prep_seed_schema="prep_seed",
            catalog_schema="catalog",
        )
    else:
        config = OrchestrationConfig(
            max_level=5,
            seeds_dir=tmp_path / "seeds",
            schema_dir=tmp_path / "schema",
            database_url=url,
            show_progress=False,
            level_5_mode=mode,
        )
        report = PrepSeedOrchestrator(config).run()
    return [(v.severity.name, v.pattern.name, v.message) for v in report.violations]


@pytest.mark.parametrize("mode", ["standard", "comprehensive"])
def test_an_inner_join_resolver_that_drops_rows_is_critical(
    tmp_path: Path, fresh_database_factory: Callable[[str], str], mode: str
) -> None:
    found = _run(tmp_path, fresh_database_factory, nullability="NOT NULL", join="INNER", mode=mode)

    assert found == [
        (
            "CRITICAL",
            "STAGED_ROW_NOT_PROMOTED",
            "catalog.tb_customer: 2 of 4 staged rows were not promoted "
            "(e.g. 0c0d0e0f-0000-4000-8000-000000000001, 0c0d0e0f-0000-4000-8000-000000000002); "
            "prep_seed.tb_customer.fk_category_id finds no catalog.tb_category row",
        )
    ]


def test_a_left_join_resolver_on_a_nullable_fk_is_still_a_null_fk(
    tmp_path: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    found = _run(tmp_path, fresh_database_factory, nullability="", join="LEFT")

    assert found == [
        (
            "CRITICAL",
            "NULL_FK_AFTER_RESOLUTION",
            "Found 2 NULL values in catalog.tb_customer.fk_category after resolution",
        )
    ]


def test_a_left_join_resolver_on_a_not_null_fk_still_fails_to_resolve(
    tmp_path: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    found = _run(tmp_path, fresh_database_factory, nullability="NOT NULL", join="LEFT")

    assert [(severity, pattern) for severity, pattern, _ in found] == [
        ("ERROR", "MISSING_FK_TRANSFORMATION")
    ]


def test_every_staged_row_promoted_reports_nothing(
    tmp_path: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    found = _run(
        tmp_path, fresh_database_factory, nullability="NOT NULL", join="INNER", stale=False
    )

    assert found == []
