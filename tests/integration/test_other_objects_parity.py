"""The live reader names every object of the kinds no typed section holds, as the tree does.

Schemas, extensions, domains, composite and range types, policies, rules, event
triggers, extended statistics, foreign-data wrappers, servers, foreign tables,
publications, conversions, operator families and classes, access methods: a
database built from a tree reads back holding the same ones, by the identity
``ddl_objects`` gives each — at existence depth (``Coverage``).

Requires a superuser on the server accessible via CONFITURE_TEST_DB_URL (an event
trigger, a wrapper and an access method need one).
"""

from collections.abc import Callable

import psycopg
import pytest

from confiture.core import live_catalog
from confiture.core.ddl_objects import shape
from confiture.core.schema_model import DEFINED_OTHER_KINDS
from confiture.core.schema_read import read_text

pytestmark = pytest.mark.integration

TREE = """
CREATE SCHEMA app;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE DOMAIN app.positive AS integer CHECK (VALUE > 0);
CREATE TYPE app.pair AS (a integer, b integer);
CREATE TYPE app.span AS RANGE (subtype = int4);
CREATE TABLE app.t (id integer, label text);
CREATE POLICY own_rows ON app.t USING (true);
CREATE RULE no_delete AS ON DELETE TO app.t DO INSTEAD NOTHING;
CREATE DOMAIN app.label AS varchar(40) COLLATE "C" DEFAULT 'none' NOT NULL
    CONSTRAINT label_short CHECK (length(VALUE) < 30) CHECK (VALUE <> '');
CREATE DOMAIN app.counts AS int4[];
CREATE TYPE app.tagged AS (tag text COLLATE "C", n bigint);
CREATE TYPE app.floatrange AS RANGE (subtype = float8, subtype_diff = float8mi);
CREATE TYPE app.textspan AS RANGE (subtype = text, collation = "C");
CREATE POLICY writers ON app.t AS RESTRICTIVE FOR UPDATE TO PUBLIC
    USING (id > 0) WITH CHECK (label IN ('a', 'b'));
CREATE RULE log_insert AS ON INSERT TO app.t WHERE NEW.id > 0
    DO ALSO UPDATE app.t SET label = 'seen' WHERE id = NEW.id;
CREATE STATISTICS app.t_stats ON id, label FROM app.t;
CREATE FUNCTION app.fn_ddl() RETURNS event_trigger LANGUAGE plpgsql AS $$ BEGIN END $$;
CREATE EVENT TRIGGER on_ddl ON ddl_command_end EXECUTE FUNCTION app.fn_ddl();
CREATE FOREIGN DATA WRAPPER app_wrapper;
CREATE SERVER app_server FOREIGN DATA WRAPPER app_wrapper;
CREATE FOREIGN TABLE app.remote (id integer) SERVER app_server;
CREATE PUBLICATION app_pub FOR TABLE app.t;
CREATE CONVERSION app.latin_to_utf8 FOR 'LATIN1' TO 'UTF8' FROM iso8859_1_to_utf8;
CREATE OPERATOR FAMILY app.int_family USING btree;
CREATE ACCESS METHOD app_heap TYPE TABLE HANDLER heap_tableam_handler;
"""


def test_a_database_built_from_a_tree_names_the_same_objects(
    fresh_database_factory: Callable[[str], str],
) -> None:
    url = fresh_database_factory("confiture_others")
    with psycopg.connect(url, autocommit=True) as conn:
        if not conn.execute(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ).fetchone()[0]:
            pytest.skip("needs a superuser: an event trigger, a wrapper, an access method")
        conn.execute(TREE)
        live = live_catalog.read(conn, schemas=["app", "public"], other_objects=True)
        conn.execute("DROP EVENT TRIGGER on_ddl")

    parsed = read_text(TREE).model

    def named(model) -> list[tuple[str, str, str]]:
        return sorted((ref.kind, ref.schema, ref.name) for ref in model.other_objects)

    assert named(live) == named(parsed)
    assert live.coverage.depth("other_objects") == "existence"
    # A domain, a type, a policy and a rule are read whole, and read back as the
    # tree wrote them once PostgreSQL's analysis is set aside (#708): no false change.
    defined = {ref for ref, obj in live.other_objects.items() if obj.definition is not None}
    assert {ref.kind for ref in defined} == DEFINED_OTHER_KINDS
    assert all(
        obj.definition is None for ref, obj in live.other_objects.items() if ref not in defined
    )
    assert {
        ref.name: shape(obj.definition)
        for ref, obj in live.other_objects.items()
        if obj.definition is not None
    } == {ref.name: shape(parsed.other_objects[ref].definition) for ref in defined}


def test_without_asking_the_section_is_not_read(fresh_database: str) -> None:
    with psycopg.connect(fresh_database) as conn:
        live = live_catalog.read(conn, schemas=["public"])
    assert live.other_objects == {}
    assert live.coverage.depth("other_objects") is None
