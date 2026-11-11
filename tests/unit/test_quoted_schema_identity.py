"""A schema is folded as PostgreSQL folds it: unquoted lowercased, quoted kept.

The seam refuses a name that needs quotes (``DIFFER_403``,
``test_seam_refuses_quoted_names``); this is the layer behind that refusal,
read through ``read_schema``, which reads such a tree so lint can report it.

An identity is the key a consumer composes SQL from, so it has to name the
object. ``"Sales"."Tb"`` is table ``Tb`` in schema ``Sales``; ``sales`` is
another schema, and ``('sales', 'Tb')`` names nothing. The parser already folds
an unquoted part and keeps a quoted one, so each reader takes the schema as the
parser (or the catalog) holds it, the same as the name. The unqualified and
``public.`` spellings still share one bucket.
"""

from confiture.core.ddl_objects import objects_in
from confiture.core.model_facts import resolve
from confiture.core.schema_model import SchemaModel, routine_ref
from confiture.core.schema_sources import read_schema
from confiture.core.sql_lexer import parse_file


def parse_schema(sql: str) -> SchemaModel:
    return read_schema(sql).model


QUOTED = """
CREATE SCHEMA "Sales";
CREATE TYPE "Sales"."Status" AS ENUM ('new', 'done');
CREATE SEQUENCE "Sales"."Seq";
CREATE TABLE "Sales"."Tb" (id bigint PRIMARY KEY);
CREATE VIEW "Sales"."V" AS SELECT id FROM "Sales"."Tb";
CREATE FUNCTION "Sales"."Fn"() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;
"""


def test_a_quoted_schema_keeps_its_case_in_every_identity() -> None:
    model = parse_schema(QUOTED)
    identities = {
        *(ref.identity for ref in model.tables),
        *(ref.identity for ref in model.views),
        *(ref.identity for ref in model.enum_types),
        *(ref.identity for ref in model.sequences),
        *((r.schema, r.name) for r in model.all_routines()),
    }
    assert identities == {
        ("Sales", "Tb"),
        ("Sales", "V"),
        ("Sales", "Status"),
        ("Sales", "Seq"),
        ("Sales", "Fn"),
    }


def test_a_routine_ref_keeps_a_quoted_schema() -> None:
    (routine,) = parse_schema(QUOTED).all_routines()
    assert routine_ref(routine).identity == ("Sales", "Fn")


def test_an_unquoted_schema_is_still_folded() -> None:
    model = parse_schema("CREATE SCHEMA Sales; CREATE TABLE Sales.Tb (id bigint);")
    assert [ref.identity for ref in model.tables] == [("sales", "tb")]


def test_an_unqualified_table_and_public_are_one_bucket() -> None:
    model = parse_schema("CREATE TABLE t (id bigint); CREATE TABLE public.t (id bigint);")
    assert [ref.identity for ref in model.tables] == [("public", "t")]


def test_the_object_list_keeps_a_quoted_schema_and_name() -> None:
    sql = 'CREATE SCHEMA "Sales"; CREATE DOMAIN "Sales"."Money" AS numeric;'
    refs = {(ref.kind, ref.schema, ref.name) for ref in objects_in([parse_file(sql)])}
    assert ("domain", "Sales", "Money") in refs


def test_the_object_list_folds_a_drop_of_a_quoted_name() -> None:
    sql = 'CREATE SCHEMA "Sales"; CREATE VIEW "Sales"."V" AS SELECT 1 AS x; DROP VIEW "Sales"."V";'
    assert not [ref for ref in objects_in([parse_file(sql)]) if ref.kind == "view"]


def test_a_typed_name_resolves_to_its_quoted_schema() -> None:
    refs = list(parse_schema(QUOTED).tables)
    found = resolve(refs, '"Sales"."Tb"')
    assert found is not None
    assert found.identity == ("Sales", "Tb")
