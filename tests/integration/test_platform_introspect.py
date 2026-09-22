"""``confiture.platform.introspect`` reads a database into the model the seam publishes.

A URL is the call's own connection; a connection is the caller's, and its
transaction with it — which is what lets a caller introspect a schema it has
created and not yet committed. What comes back is the model and nothing of the
driver's, and its wire is the published one.
"""

from __future__ import annotations

import json

import psycopg
from jsonschema import Draft202012Validator
from tests.unit.test_platform_leaks_no_driver_types import driver_objects

from confiture import platform
from confiture.core.schema_exporter import load_schema

DDL = """
CREATE SCHEMA app;
CREATE TYPE app.status AS ENUM ('new', 'done');
CREATE TABLE app.parent (pk_parent BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, id UUID UNIQUE);
CREATE TABLE app.child (
    id UUID PRIMARY KEY,
    fk_parent BIGINT REFERENCES app.parent (pk_parent),
    status app.status NOT NULL DEFAULT 'new'
);
CREATE VIEW app.v_child AS SELECT id FROM app.child;
CREATE FUNCTION app.touch() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;
CREATE TRIGGER trg_touch BEFORE UPDATE ON app.child FOR EACH ROW EXECUTE FUNCTION app.touch();
"""


def test_introspect_by_url_reads_every_kind(fresh_database: str) -> None:
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(DDL)
    model = platform.introspect(fresh_database, schemas=["app"])
    assert sorted(ref.name for ref in model.tables) == ["child", "parent"]
    assert [e.values for e in model.enum_types.values()] == [("new", "done")]
    assert [v.name for v in model.views.values()] == ["v_child"]
    assert [r.name for r in model.all_routines()] == ["touch"]
    assert [t.name for t in model.triggers.values()] == ["trg_touch"]
    assert driver_objects(model) == set()


def test_introspect_defaults_to_every_user_schema(fresh_database: str) -> None:
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(DDL)
        conn.execute("CREATE TABLE public.lone (x INT)")
    model = platform.introspect(fresh_database)
    assert {(ref.schema, ref.name) for ref in model.tables} == {
        ("app", "child"),
        ("app", "parent"),
        ("public", "lone"),
    }


def test_introspect_reads_inside_the_callers_transaction(fresh_database: str) -> None:
    with psycopg.connect(fresh_database) as conn:
        conn.execute(DDL)
        model = platform.introspect(conn, schemas=["app"])
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS
        conn.rollback()
    assert len(model.tables) == 2
    assert platform.introspect(fresh_database, schemas=["app"]).tables == {}


def test_the_introspected_wire_is_the_published_one(fresh_database: str) -> None:
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(DDL)
    model = platform.introspect(fresh_database, schemas=["app"])
    validator = Draft202012Validator(load_schema("schema-model.schema.json"))
    assert list(validator.iter_errors(json.loads(model.to_json()))) == []
    assert platform.SchemaModel.from_json(model.to_json()) == model
