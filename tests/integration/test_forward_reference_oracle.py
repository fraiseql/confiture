"""PostgreSQL's verdict on each forward-reference row: the oracle ``build_004`` is held to.

Each row's tree is built by ``SchemaBuilder`` — the order and the foreign-key
moves the build really makes — and the bundle is applied to an empty database
with ``psql``, as a build is applied. A row whose verdict differs from
PostgreSQL's is a wrong row, and fixing it comes before any rule code.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.unit.linting.forward_reference_rows import ROWS, Row

from confiture.core.builder import SchemaBuilder
from confiture.core.psql_applier import apply_sql_via_psql
from confiture.exceptions import SchemaError


def build_bundle(tmp_path: Path, row: Row) -> str:
    """The bundle ``confiture build`` writes from *row*'s tree."""
    schema = tmp_path / "db" / "schema"
    schema.mkdir(parents=True)
    for name, sql in row.files:
        (schema / name).write_text(sql)
    env = tmp_path / "db" / "environments"
    env.mkdir()
    (env / "test.yaml").write_text(
        "name: test\n"
        f"include_dirs:\n  - {schema}\n"
        "database_url: postgresql://x/y\n"
        f"build:\n  two_pass: {'true' if row.two_pass else 'false'}\n"
    )
    return SchemaBuilder(env="test", project_dir=tmp_path).build()


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_postgresql_agrees_with_the_row(tmp_path: Path, fresh_database: str, row: Row) -> None:
    bundle = build_bundle(tmp_path, row)
    try:
        apply_sql_via_psql(fresh_database, bundle)
    except SchemaError as exc:
        refused, why = True, str(exc)
    else:
        refused, why = False, "applied"
    assert refused == row.refused, why
    if refused:
        assert "does not exist" in why, why
