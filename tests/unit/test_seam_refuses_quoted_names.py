"""The seam hands out no name that needs quotes: ``parse_schema`` refuses it (``DIFFER_403``).

confiture supports a name only as PostgreSQL writes it bare. Lint reports such a
name (``naming_003``/``naming_004``) and the differ refuses it; a model the seam
returns is what a consumer composes SQL from, so it is refused there too, with
the object and where it is written. ``introspect`` refuses the same way
(``tests/integration/test_platform_introspect.py``).
"""

from pathlib import Path

import pytest

from confiture import platform
from confiture.exceptions import DifferError


@pytest.mark.parametrize(
    ("ddl", "named"),
    [
        ('CREATE SCHEMA "Sales"; CREATE TABLE "Sales".tb (id bigint);', '"Sales"'),
        ('CREATE TABLE "Tb" (id bigint);', '"Tb"'),
        ('CREATE TABLE tb ("Id" bigint);', '"Id"'),
        ('CREATE TABLE tb (id bigint); CREATE INDEX "Ix" ON tb (id);', '"Ix"'),
        ("CREATE TYPE \"Status\" AS ENUM ('a');", '"Status"'),
        ('CREATE FUNCTION "Fn"() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;', '"Fn"'),
        ('CREATE VIEW "user" AS SELECT 1 AS x;', '"user"'),
    ],
)
def test_parse_schema_refuses_a_name_that_needs_quotes(ddl: str, named: str) -> None:
    with pytest.raises(DifferError) as refused:
        platform.parse_schema(ddl)
    assert refused.value.error_code == "DIFFER_403"
    assert named in str(refused.value)


def test_parse_schema_reads_a_tree_of_bare_names() -> None:
    model = platform.parse_schema("CREATE SCHEMA Sales; CREATE TABLE Sales.Tb (Id bigint);")
    assert [ref.identity for ref in model.tables] == [("sales", "tb")]


def test_the_refusal_says_where_the_tree_writes_the_name(tmp_path: Path) -> None:
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "10_tables.sql").write_text(
        'CREATE TABLE tb (id bigint);\n\nCREATE TABLE "Tb" (id bigint);\n'
    )
    with pytest.raises(DifferError, match=r"10_tables\.sql:3"):
        platform.parse_schema(schema)
