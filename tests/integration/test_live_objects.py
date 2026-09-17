"""What a live database holds, in the kinds a DDL tree declares (#303).

The traps this reads around, each measured rather than assumed:

* a ``FOREIGN KEY`` creates **internal** triggers on both tables, so without
  ``NOT tgisinternal`` every FK in a schema is two extra triggers;
* ``citext`` installs a dozen functions, so without the ``pg_depend deptype = 'e'``
  exclusion a pristine database reports dozens of extra routines;
* ``pg_get_function_identity_arguments`` includes parameter *names* and ``OUT``
  parameters, which the expected side counts as neither.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from confiture.core.live_objects import LiveObjectCatalog
from confiture.core.psql_applier import apply_sql_via_psql

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "live_drift_corpus"
FILES = ("010_schema.sql", "020_tables.sql", "030_types.sql", "040_indexes.sql", "050_objects.sql")


@pytest.fixture
def objects(fresh_database: str):
    sql = "\n".join((CORPUS / name).read_text(encoding="utf-8") for name in FILES)
    apply_sql_via_psql(fresh_database, sql=sql)
    extra = """
    CREATE TABLE core.tb_child (
        id BIGINT PRIMARY KEY,
        widget_id BIGINT REFERENCES core.tb_widget(id)
    );
    CREATE FUNCTION core.fn_out(a integer, OUT b integer, OUT c integer)
    LANGUAGE sql AS $$ SELECT 1, 2 $$;
    """
    apply_sql_via_psql(fresh_database, sql=extra)
    with psycopg.connect(fresh_database) as conn:
        yield LiveObjectCatalog(conn).read(["core", "public"])


def names(objects, kind: str) -> set[str]:
    return {f"{obj.schema}.{obj.name}" for obj in objects.of_kind(kind)}


def test_views_and_matviews(objects) -> None:
    assert names(objects, "view") == {"core.v_widget"}
    assert names(objects, "matview") == {"core.mv_widget"}


def test_a_trigger_is_keyed_table_first(objects) -> None:
    assert names(objects, "trigger") == {"core.tb_widget.trg_touch"}


def test_the_internal_triggers_of_a_foreign_key_are_not_objects(objects) -> None:
    """A FK creates one internal trigger per side; reporting them would put two
    extra items on every foreign key in the schema."""
    assert not any("RI_Constraint" in obj.name for obj in objects.of_kind("trigger"))
    assert len(objects.of_kind("trigger")) == 1


def test_routines(objects) -> None:
    assert names(objects, "function") >= {"core.fn_touch", "core.fn_seen", "core.fn_gone"}
    assert names(objects, "procedure") == {"core.pr_noop"}


def test_a_routine_carries_its_input_types_only(objects) -> None:
    """`OUT` parameters are not part of a signature, and neither are names."""
    out = next(obj for obj in objects.of_kind("function") if obj.name == "fn_out")
    assert out.signature == ((None, "integer"),)


def test_a_signature_is_canonical(objects) -> None:
    """`timestamptz` and `timestamp with time zone` are one type (#275)."""
    seen = next(obj for obj in objects.of_kind("function") if obj.name == "fn_seen")
    assert seen.signature == ((None, "timestamptz"),)
    gone = next(obj for obj in objects.of_kind("function") if obj.name == "fn_gone")
    assert gone.signature == ((None, "bigint"),)


def test_a_trigger_function_is_read(objects) -> None:
    """The source parser has no trigger filter, so neither has this."""
    assert "core.fn_touch" in names(objects, "function")


def test_an_extension_owned_routine_is_not_an_object(objects) -> None:
    """`citext` installs a dozen functions into `public`; none of them is the
    tree's, and reporting them would drown every real finding."""
    public_functions = {obj.name for obj in objects.of_kind("function") if obj.schema == "public"}
    assert public_functions == set(), sorted(public_functions)


def test_the_catalog_reads_only_the_kinds_something_compares(fresh_database: str) -> None:
    """An extension is not among them, on purpose.

    ``ddl_objects`` tracks ``CREATE EXTENSION``, so the expected side is there for
    the taking — and the comparison does not exist. Reading a fact nothing
    compares is what published three drift types confiture cannot emit.
    """
    with psycopg.connect(fresh_database) as conn:
        catalog = LiveObjectCatalog(conn)
    assert set(catalog.KINDS) == {
        "view",
        "matview",
        "trigger",
        "function",
        "procedure",
        "aggregate",
    }
    assert not hasattr(catalog, "extensions")


def test_a_schema_the_tree_does_not_declare_is_not_read(fresh_database: str) -> None:
    sql = "\n".join((CORPUS / name).read_text(encoding="utf-8") for name in FILES)
    apply_sql_via_psql(fresh_database, sql=sql)
    with psycopg.connect(fresh_database) as conn:
        found = LiveObjectCatalog(conn).read(["public"])
    assert found.objects == []
