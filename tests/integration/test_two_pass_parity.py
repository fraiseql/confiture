"""A two-pass build applies the constraints a one-pass build applies (#511).

``build.two_pass`` moves each foreign key out of its ``CREATE TABLE`` and adds
it at the end. Moving a key must not change it: the tree below is in an order
one pass can apply, both bundles are applied to empty databases, and PostgreSQL
is asked what each constraint is. Each table covers a shape the regex reader got
wrong — no referenced column list, ``MATCH FULL``, ``SET NULL (col)``, a string
literal spelling ``REFERENCES``, deferral on a column.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from confiture.core.builder import SchemaBuilder
from confiture.core.psql_applier import apply_sql_via_psql

pytestmark = pytest.mark.integration

TREE = """\
CREATE SCHEMA app;
CREATE TABLE app.org (id bigint PRIMARY KEY, x int, y int, UNIQUE (x, y));
CREATE TABLE app.member (
    id bigint PRIMARY KEY,
    note text DEFAULT 'see REFERENCES manual (note)',
    org_fk bigint REFERENCES app.org,
    org_id bigint CONSTRAINT member_org REFERENCES app.org (id) DEFERRABLE INITIALLY DEFERRED NOT NULL,
    x int,
    y int,
    -- a composite key the model cannot hold whole: it stays in the table
    CONSTRAINT member_xy FOREIGN KEY (x, y) REFERENCES app.org (x, y) MATCH FULL ON DELETE CASCADE,
    CONSTRAINT member_xy_null FOREIGN KEY (x, y) REFERENCES app.org (x, y) ON DELETE SET NULL (x),
    FOREIGN KEY (org_id) REFERENCES app.org ON UPDATE CASCADE
);
"""

_CONSTRAINTS = """
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'app.member'::regclass
ORDER BY conname
"""


def _constraints(url: str) -> list[tuple[str, str]]:
    with psycopg.connect(url) as conn:
        return conn.execute(_CONSTRAINTS).fetchall()


def _bundle(tmp_path: Path, *, two_pass: bool) -> str:
    root = tmp_path / ("two" if two_pass else "one")
    schema = root / "db" / "schema"
    schema.mkdir(parents=True)
    (schema / "00_tree.sql").write_text(TREE)
    env = root / "db" / "environments"
    env.mkdir()
    (env / "test.yaml").write_text(
        f"name: test\ninclude_dirs:\n  - {schema}\ndatabase_url: postgresql://x/y\n"
        f"build:\n  two_pass: {'true' if two_pass else 'false'}\n"
    )
    return SchemaBuilder(env="test", project_dir=root).build()


def test_both_builds_apply_the_same_constraints(
    tmp_path: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    one, two = fresh_database_factory("confiture_t"), fresh_database_factory("confiture_t")
    two_pass_bundle = _bundle(tmp_path, two_pass=True)
    apply_sql_via_psql(one, _bundle(tmp_path, two_pass=False))
    apply_sql_via_psql(two, two_pass_bundle)

    assert "ALTER TABLE app.member" in two_pass_bundle
    assert _constraints(two) == _constraints(one)
