"""A key with no ``REFERENCES`` is judged by what its resolver joins, then by its name (#530).

A key into a partitioned table cannot declare ``REFERENCES``, so ``fk_origin`` (named
for its role) drew a false ``MISSING_FK_TRANSFORMATION`` against a resolver that
matches ``tb_sample.id = s.fk_origin_id``. The convention ``tb_<role>`` decides only
when the resolver never reads ``<fk>_id`` at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture import platform
from confiture.core.seed.validation.prep_seed.models import PrepSeedPattern

TABLES = """
CREATE SCHEMA catalog;
CREATE SCHEMA prep_seed;
CREATE TABLE catalog.tb_sample (
    pk_sample BIGINT GENERATED ALWAYS AS IDENTITY,
    id UUID NOT NULL,
    taken_on DATE NOT NULL,
    PRIMARY KEY (pk_sample, taken_on)
) PARTITION BY RANGE (taken_on);
CREATE TABLE catalog.tb_event (
    pk_event BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID NOT NULL UNIQUE,
    fk_origin BIGINT,
    fk_sample BIGINT
);
CREATE TABLE prep_seed.tb_sample (id UUID NOT NULL, taken_on DATE NOT NULL);
CREATE TABLE prep_seed.tb_event (id UUID NOT NULL, fk_origin_id UUID, fk_sample_id UUID);
"""

_SUBQUERY = "(SELECT pk_sample FROM catalog.tb_sample WHERE id = s.{key}_id)"
_JOIN = "p.pk_sample"


def _resolver(origin: str, sample: str, joins: str = "") -> str:
    return f"""
CREATE FUNCTION catalog.fn_resolve_tb_event() RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO catalog.tb_event (id, fk_origin, fk_sample)
    SELECT s.id, {origin}, {sample}
    FROM prep_seed.tb_event s {joins};
END $$;
"""


def _messages(tmp_path: Path, ddl: str) -> list[str]:
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "10_tables.sql").write_text(ddl)
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    report = platform.validate_seeds(seeds, schema_dir=schema, max_level=3)
    return [
        v.message
        for v in report.violations
        if v.pattern == PrepSeedPattern.MISSING_FK_TRANSFORMATION
    ]


def test_a_role_named_key_read_by_a_scalar_subquery_is_resolved(tmp_path: Path) -> None:
    resolver = _resolver(_SUBQUERY.format(key="fk_origin"), _SUBQUERY.format(key="fk_sample"))

    assert _messages(tmp_path, TABLES + resolver) == []


def test_a_role_named_key_read_by_a_join_is_resolved(tmp_path: Path) -> None:
    resolver = _resolver(
        "o.pk_sample",
        "p.pk_sample",
        "LEFT JOIN catalog.tb_sample o ON o.id = s.fk_origin_id "
        "LEFT JOIN catalog.tb_sample p ON p.id = s.fk_sample_id",
    )

    assert _messages(tmp_path, TABLES + resolver) == []


@pytest.mark.parametrize("unmapped", ["fk_origin", "fk_sample"])
def test_a_key_the_resolver_never_reads_is_still_an_error(tmp_path: Path, unmapped: str) -> None:
    columns = {
        "fk_origin": _SUBQUERY.format(key="fk_origin"),
        "fk_sample": _SUBQUERY.format(key="fk_sample"),
    }
    columns[unmapped] = "NULL::bigint"

    (message,) = _messages(tmp_path, TABLES + _resolver(columns["fk_origin"], columns["fk_sample"]))

    assert f"on {unmapped}_id" in message
