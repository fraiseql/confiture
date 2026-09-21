"""What a live database holds, in the kinds a DDL tree declares (#303).

``live_catalog.read(…, routines=True, views=True, triggers=True)`` reads them
into the schema model — ``confiture drift``'s live side. The traps this reads
around, each measured rather than assumed:

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

from confiture.core import live_catalog
from confiture.core.psql_applier import apply_sql_via_psql
from confiture.core.schema_model import SchemaModel

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "live_drift_corpus"
FILES = ("010_schema.sql", "020_tables.sql", "030_types.sql", "040_indexes.sql", "050_objects.sql")


def _read(conn: psycopg.Connection, schemas: list[str]) -> SchemaModel:
    return live_catalog.read(conn, schemas=schemas, routines=True, views=True, triggers=True)


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
        yield _read(conn, ["core", "public"])


def names(model: SchemaModel, kind: str) -> set[str]:
    views = {f"{v.schema}.{v.name}" for v in model.views.values() if v.kind == kind}
    routines = {f"{r.schema}.{r.name}" for r in model.all_routines() if r.kind == kind}
    triggers = {t.qualified for t in model.triggers.values()} if kind == "trigger" else set()
    return views | routines | triggers


def routine(model: SchemaModel, name: str):
    return next(r for r in model.all_routines() if r.name == name)


def test_views_and_matviews(objects) -> None:
    assert names(objects, "view") == {"core.v_widget"}
    assert names(objects, "matview") == {"core.mv_widget"}


def test_a_trigger_is_keyed_table_first(objects) -> None:
    assert names(objects, "trigger") == {"core.tb_widget.trg_touch"}


def test_the_internal_triggers_of_a_foreign_key_are_not_objects(objects) -> None:
    """A FK creates one internal trigger per side; reporting them would put two
    extra items on every foreign key in the schema."""
    assert len(objects.triggers) == 1


def test_routines(objects) -> None:
    assert names(objects, "function") >= {"core.fn_touch", "core.fn_seen", "core.fn_gone"}
    assert names(objects, "procedure") == {"core.pr_noop"}


def test_a_routine_carries_its_input_types_only(objects) -> None:
    """`OUT` parameters are not part of a signature, and neither are names."""
    assert routine(objects, "fn_out").signature_key == ((None, "integer"),)


def test_a_signature_is_canonical(objects) -> None:
    """`timestamptz` and `timestamp with time zone` are one type (#275)."""
    assert routine(objects, "fn_seen").signature_key == ((None, "timestamptz"),)
    assert routine(objects, "fn_gone").signature_key == ((None, "bigint"),)


def test_a_trigger_function_is_read(objects) -> None:
    """The DDL side has no trigger filter, so neither has this."""
    assert "core.fn_touch" in names(objects, "function")


def test_an_extension_owned_routine_is_not_an_object(objects) -> None:
    """`citext` installs a dozen functions into `public`; none of them is the
    tree's, and reporting them would drown every real finding."""
    public = {r.name for r in objects.all_routines() if r.schema == "public"}
    assert public == set(), sorted(public)


def test_a_schema_the_tree_does_not_declare_is_not_read(fresh_database: str) -> None:
    sql = "\n".join((CORPUS / name).read_text(encoding="utf-8") for name in FILES)
    apply_sql_via_psql(fresh_database, sql=sql)
    with psycopg.connect(fresh_database) as conn:
        found = _read(conn, ["public"])
    assert (found.routines, found.views, found.triggers) == ({}, {}, {})


def test_nothing_is_read_that_nobody_asked_for(fresh_database: str) -> None:
    """Silence from a kind nobody asked the catalogue about is not evidence of absence,
    so a model read without them holds none — and ``compare_schemas`` compares them
    only when told they were read."""
    sql = "\n".join((CORPUS / name).read_text(encoding="utf-8") for name in FILES)
    apply_sql_via_psql(fresh_database, sql=sql)
    with psycopg.connect(fresh_database) as conn:
        found = live_catalog.read(conn, schemas=["core"])
    assert (found.routines, found.views, found.triggers) == ({}, {}, {})
