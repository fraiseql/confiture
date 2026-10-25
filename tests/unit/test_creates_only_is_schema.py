"""A file under a seed path that only creates schema objects is schema (#748).

The prep-seed guide's layout puts the staging tables in ``db/schema/prep_seed/``,
and ``prep_seed`` holds ``seed`` as a word, so the path alone filed their
``CREATE TABLE``s as seeds: ``build --schema-only`` left them out, and
``migrate rebuild --seed`` applied them after the whole schema.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.builder import SchemaBuilder
from confiture.core.seed.paths import is_seed_file

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE prep_seed.tb_a (id uuid PRIMARY KEY);",
        "-- staging\nCREATE TABLE prep_seed.tb_a (id uuid);\n"
        "CREATE INDEX ON prep_seed.tb_a (id);\nCOMMENT ON TABLE prep_seed.tb_a IS 'x';",
        "CREATE VIEW prep_seed.v AS SELECT 1 AS one;",
        "CREATE FUNCTION prep_seed.f() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;",
    ],
)
def test_a_file_that_only_creates_objects_is_schema(tmp_path: Path, sql: str):
    path = tmp_path / "db" / "schema" / "prep_seed" / "tb_a.sql"
    path.parent.mkdir(parents=True)
    path.write_text(sql)
    assert not is_seed_file(path, anchor=tmp_path / "db")


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO t VALUES (1);",
        "CREATE TABLE t (id int);\nINSERT INTO t VALUES (1);",
        "COPY t (id) FROM stdin;\n1\n\\.\n",
        "ALTER TABLE t DISABLE TRIGGER ALL;",
        "CREATE TEMP TABLE s (id int);",
        "SELECT setval('t_id_seq', 10);",
        "CREATE TABLE t AS SELECT 1 AS one;",
        "-- only a comment\n",
        "CREATE TABLE (;",
    ],
)
def test_anything_else_under_a_seed_path_stays_a_seed(tmp_path: Path, sql: str):
    path = tmp_path / "db" / "seeds" / "01.sql"
    path.parent.mkdir(parents=True)
    path.write_text(sql)
    assert is_seed_file(path, anchor=tmp_path / "db")


def test_a_creates_only_file_outside_a_seed_path_is_schema(tmp_path: Path):
    path = tmp_path / "db" / "schema" / "tb_a.sql"
    path.parent.mkdir(parents=True)
    path.write_text("INSERT INTO t VALUES (1);")
    assert not is_seed_file(path, anchor=tmp_path / "db")


@pytest.mark.parametrize(
    "path",
    [
        "06-prep-seed-validation/db/schema/prep_seed/tb_manufacturer.sql",
        "08-generated-seeds/db/schema/10_prep_seed/10_tb_vendor.sql",
        "08-generated-seeds/db/schema/10_prep_seed/20_tb_product.sql",
    ],
)
def test_the_examples_staging_tables_are_schema(path: str):
    file = EXAMPLES / path
    assert not is_seed_file(file, anchor=file.parents[3])


_ENV = """\
name: local
database_url: postgresql://localhost/app
include_dirs:
  - db/schema
  - db/seeds
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(_ENV)
    for rel, sql in {
        "db/schema/10_prep_seed/tb_a.sql": "CREATE TABLE prep_seed.tb_a (id uuid);",
        "db/schema/20_catalog/tb_b.sql": "CREATE TABLE catalog.tb_b (id bigint);",
        "db/seeds/00_staging.sql": "CREATE TABLE prep_seed.tb_c (id uuid);",
        "db/seeds/10_rows.sql": "INSERT INTO prep_seed.tb_a VALUES (gen_random_uuid());",
    }.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(sql)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_the_builder_files_them_with_the_schema(project: Path):
    schema, seeds = SchemaBuilder(env="local", project_dir=project).categorize_sql_files()
    assert [p.name for p in schema] == ["tb_a.sql", "tb_b.sql", "00_staging.sql"]
    assert [p.name for p in seeds] == ["10_rows.sql"]


def test_build_schema_only_keeps_them(project: Path):
    out = project / "schema.sql"
    result = CliRunner().invoke(
        app, ["build", "--schema-only", "--output", str(out), "--project-dir", str(project)]
    )
    assert result.exit_code == 0, result.output
    built = out.read_text()
    assert "prep_seed.tb_a" in built
    assert "prep_seed.tb_c" in built
    assert "INSERT" not in built
