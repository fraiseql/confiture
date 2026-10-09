"""A database whose key is plain where the tree declares it temporal has drifted (#604).

PostgreSQL 18 only: an older server cannot hold a temporal key, so there is
nothing to drift from.
"""

from pathlib import Path

import psycopg
import pytest

from confiture.core.drift import DriftSeverity, DriftType, SchemaDriftDetector

TABLES = (
    "CREATE TABLE p (id INT4RANGE, valid DATERANGE, CONSTRAINT p_pkey PRIMARY KEY {key});\n"
    "CREATE TABLE c (id INT4RANGE, valid DATERANGE,"
    " CONSTRAINT c_fk FOREIGN KEY {fk} REFERENCES p {fk});\n"
)
TEMPORAL = TABLES.format(key="(id, valid WITHOUT OVERLAPS)", fk="(id, PERIOD valid)")
PLAIN = TABLES.format(key="(id, valid)", fk="(id, valid)")


def _drift(url: str, built: str, declared: str, tmp_path: Path) -> list[tuple[str, str, str]]:
    schema = tmp_path / "schema.sql"
    schema.write_text(declared, encoding="utf-8")
    with psycopg.connect(url, autocommit=True) as conn:
        (version,) = conn.execute("SHOW server_version_num").fetchone() or ("0",)
        if int(version) < 180000:
            pytest.skip("temporal keys need PostgreSQL 18")
        conn.execute(built)
    with psycopg.connect(url) as conn:
        report = SchemaDriftDetector(conn).compare_with_schema_file(str(schema))
    return sorted(
        (item.drift_type.value, item.severity.value, item.object_name)
        for item in report.drift_items
    )


@pytest.mark.parametrize(
    ("built", "declared"),
    [
        pytest.param(PLAIN, TEMPORAL, id="declared-temporal-held-plain"),
        pytest.param(TEMPORAL, PLAIN, id="declared-plain-held-temporal"),
    ],
)
def test_a_key_that_lost_or_gained_its_period_is_a_mismatch(
    fresh_database: str, tmp_path: Path, built: str, declared: str
) -> None:
    mismatch = (DriftType.CONSTRAINT_MISMATCH.value, DriftSeverity.CRITICAL.value)
    assert _drift(fresh_database, built, declared, tmp_path) == [
        (*mismatch, "public.c.c_fk"),
        (*mismatch, "public.p.p_pkey"),
    ]


#: Two unnamed keys on the same columns, one temporal: PostgreSQL names them
#: ``u_id_valid_key`` and ``u_id_valid_key1``, and each pairs with its own.
UNNAMED = (
    "CREATE TABLE u (id INT4RANGE, valid DATERANGE,"
    " UNIQUE (id, valid), UNIQUE (id, valid WITHOUT OVERLAPS));\n"
)
REVERSED = (
    "CREATE TABLE u (id INT4RANGE, valid DATERANGE,"
    " UNIQUE (id, valid WITHOUT OVERLAPS), UNIQUE (id, valid));\n"
)


@pytest.mark.parametrize(
    ("built", "declared"),
    [
        pytest.param(TEMPORAL, TEMPORAL, id="named"),
        pytest.param(UNNAMED, UNNAMED, id="unnamed-beside-a-plain-one"),
        pytest.param(UNNAMED, REVERSED, id="unnamed-declared-in-another-order"),
    ],
)
def test_a_temporal_key_built_from_its_tree_has_not_drifted(
    fresh_database: str, tmp_path: Path, built: str, declared: str
) -> None:
    assert _drift(fresh_database, built, declared, tmp_path) == []
