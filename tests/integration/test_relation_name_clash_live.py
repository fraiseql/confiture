"""A create PostgreSQL skips on a name another kind holds is not missing live (#648).

Each tree is applied to the server, which skips the later ``IF NOT EXISTS`` with
a notice; the expected schema keeps the first holder, so neither static drift
nor a diff between the tree and the database it built sees anything.
"""

from pathlib import Path

import psycopg
import pytest

from confiture import platform
from confiture.core.drift import SchemaDriftDetector

SHAPES = {
    "view-then-table": (
        "CREATE VIEW s.x AS SELECT 1 AS a;\nCREATE TABLE IF NOT EXISTS s.x (a int);\n"
    ),
    "table-then-sequence": "CREATE TABLE s.x (a int);\nCREATE SEQUENCE IF NOT EXISTS s.x;\n",
    "sequence-then-table": "CREATE SEQUENCE s.x;\nCREATE TABLE IF NOT EXISTS s.x (a int);\n",
    "view-then-matview": (
        "CREATE VIEW s.x AS SELECT 1 AS a;\n"
        "CREATE MATERIALIZED VIEW IF NOT EXISTS s.x AS SELECT 2 AS b;\n"
    ),
    "index-then-table": (
        "CREATE TABLE s.t (a int);\nCREATE INDEX x ON s.t (a);\n"
        "CREATE TABLE IF NOT EXISTS s.x (a int);\n"
    ),
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_the_skipped_create_is_neither_drift_nor_a_change(
    clean_test_db: psycopg.Connection, test_db_url: str, tmp_path: Path, shape: str
) -> None:
    ddl = "CREATE SCHEMA s;\n" + SHAPES[shape]
    with clean_test_db.cursor() as cur:
        cur.execute(ddl)
    clean_test_db.commit()
    schema_file = tmp_path / "schema.sql"
    schema_file.write_text(ddl)

    report = SchemaDriftDetector(clean_test_db).compare_with_schema_file(str(schema_file))

    assert not report.has_drift, report.to_dict()
    assert platform.diff(ddl, test_db_url).changes == []
