"""``drift --schema`` reads the bundle ``confiture build`` writes, seeds and all (#561).

A full build (schema and seed directories) carries every seed file, and a seed is
often ``COPY … FROM stdin`` with rows that are not SQL. drift handed the bundle to
the parser whole, which refused the first data row (``SCHEMA_202``) and told the
operator to regenerate the file with the command that had just written it. The
bundle is now read like every other tree — ``COPY`` data blanked, never stripped —
so a database built from it has no drift.

Requires a running PostgreSQL server accessible via CONFITURE_TEST_DB_URL.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from confiture.core.builder import SchemaBuilder
from confiture.core.drift import SchemaDriftDetector
from confiture.exceptions import SchemaError

TABLES = """\
CREATE TABLE tb_country (
    pk_country bigint PRIMARY KEY,
    code text NOT NULL UNIQUE,
    label text NOT NULL
);
"""

SEED = """\
COPY tb_country (pk_country, code, label) FROM stdin;
1\tFR\tFrance; d'outre-mer
2\tCI\tCôte d'Ivoire
\\.
"""


def _project(root: Path, seed: str) -> SchemaBuilder:
    schema_dir = root / "db" / "schema"
    seeds_dir = root / "db" / "seeds"
    schema_dir.mkdir(parents=True)
    seeds_dir.mkdir(parents=True)
    (schema_dir / "10_country.sql").write_text(TABLES)
    (seeds_dir / "10_country.sql").write_text(seed)
    environments = root / "db" / "environments"
    environments.mkdir(parents=True)
    (environments / "local.yaml").write_text(
        f"name: local\ninclude_dirs:\n  - {schema_dir}\n  - {seeds_dir}\n"
        "database_url: postgresql://localhost/nonexistent\n"
    )
    return SchemaBuilder(env="local", project_dir=root)


def test_a_database_built_from_a_seeded_bundle_has_no_drift(
    clean_test_db: psycopg.Connection, tmp_path: Path
) -> None:
    builder = _project(tmp_path, SEED)
    bundle = tmp_path / "schema_local.sql"
    builder.build(output_path=bundle)
    assert "FROM stdin" in bundle.read_text()
    with clean_test_db.cursor() as cur:
        cur.execute(builder.build(schema_only=True))
    clean_test_db.commit()

    report = SchemaDriftDetector(clean_test_db).compare_with_schema_file(str(bundle))

    assert report.tables_checked == 1
    assert not report.has_drift, [item.message for item in report.drift_items]


def test_a_statement_the_parser_rejects_is_named_by_its_line(
    clean_test_db: psycopg.Connection, tmp_path: Path
) -> None:
    schema = tmp_path / "schema.sql"
    schema.write_text(TABLES + SEED + "CREATE TABEL broken (id int);\n")

    with pytest.raises(SchemaError) as caught:
        SchemaDriftDetector(clean_test_db).compare_with_schema_file(str(schema))

    assert caught.value.error_code == "SCHEMA_202"
    assert caught.value.context == {"file": str(schema), "line": 10}
