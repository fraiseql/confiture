"""What ``introspect`` and the function introspector answer on a real database.

Both read through ``core/live_catalog``; these pin their answers on a schema built
to hold each case the old per-table queries handled — a composite foreign key
declared in a different column order than the key it references, a reference into
another schema, a quoted identifier, a partitioned table and its partition, a view,
and routines with every parameter mode — so a reader that answers differently
fails here, whatever it answers in a unit test.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import psycopg
import pytest

from confiture.core.introspection.functions import FunctionIntrospector
from confiture.core.introspection.tables import SchemaIntrospector
from confiture.models.function_info import FunctionInfo
from confiture.models.introspection import IntrospectionResult

DDL = """
CREATE EXTENSION IF NOT EXISTS citext;
CREATE SCHEMA app;
CREATE SCHEMA other;
CREATE TYPE app.mood AS ENUM ('sad', 'happy');
CREATE TABLE other.tb_ext (id BIGINT PRIMARY KEY, code TEXT UNIQUE);
CREATE TABLE app.tb_pair (a INT, b INT, label VARCHAR(50) NOT NULL, PRIMARY KEY (a, b));
CREATE TABLE app.tb_parent (
    pk_parent BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id UUID NOT NULL
);
CREATE TABLE app."tb_Mixed" (
    "UserId" BIGINT PRIMARY KEY,
    amount NUMERIC(10, 2),
    tags TEXT[],
    mood app.mood,
    at TIMESTAMPTZ DEFAULT now(),
    email citext
);
CREATE TABLE app.tb_child (
    pk_child BIGSERIAL PRIMARY KEY,
    id UUID,
    pa INT,
    pb INT,
    fk_parent BIGINT NOT NULL,
    ext_id BIGINT,
    CONSTRAINT zz_pair FOREIGN KEY (pb, pa) REFERENCES app.tb_pair (b, a),
    CONSTRAINT aa_parent FOREIGN KEY (fk_parent) REFERENCES app.tb_parent (pk_parent),
    CONSTRAINT mm_ext FOREIGN KEY (ext_id) REFERENCES other.tb_ext (id),
    CONSTRAINT ck_pa CHECK (pa > 0)
);
CREATE INDEX ix_child_id ON app.tb_child (id) WHERE id IS NOT NULL;
CREATE TABLE app.tb_part (id INT, at DATE) PARTITION BY RANGE (at);
CREATE TABLE app.tb_part_2026 PARTITION OF app.tb_part
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE TABLE app.log (id INT);
CREATE VIEW app.tb_view AS SELECT 1 AS x;
CREATE MATERIALIZED VIEW app.mv_child AS SELECT pk_child FROM app.tb_child;

CREATE FUNCTION app.fn_add(a INTEGER, b INTEGER DEFAULT 1) RETURNS INTEGER
    LANGUAGE sql IMMUTABLE AS $$ SELECT a + b $$;
COMMENT ON FUNCTION app.fn_add(INTEGER, INTEGER) IS 'adds';
CREATE FUNCTION app.fn_add(a TEXT) RETURNS TEXT LANGUAGE sql AS $$ SELECT a $$;
CREATE FUNCTION app.fn_out(x INT, OUT y INT, INOUT z TEXT)
    LANGUAGE sql STABLE AS $$ SELECT x, z $$;
CREATE FUNCTION app.fn_var(VARIADIC xs INT[]) RETURNS INT LANGUAGE sql AS $$ SELECT 1 $$;
CREATE FUNCTION app.fn_tab(INT) RETURNS TABLE (k INT, v TEXT)
    LANGUAGE sql AS $$ SELECT 1, 'a' $$;
CREATE FUNCTION app.fn_arr(a VARCHAR(10)[], b app.mood, c app."tb_Mixed") RETURNS SETOF INT
    LANGUAGE sql AS $$ SELECT 1 $$;
CREATE FUNCTION app.fn_trg() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;
CREATE FUNCTION app.fn_sec() RETURNS void LANGUAGE sql SECURITY DEFINER
    SET search_path = pg_catalog COST 5 AS $$ SELECT $$;
CREATE PROCEDURE app.pr_do(IN a INT, INOUT b INT) LANGUAGE plpgsql AS $$ BEGIN b := a; END $$;
CREATE AGGREGATE app.agg_sum(INT) (sfunc = int4pl, stype = INT);
CREATE TRIGGER trg_touch BEFORE UPDATE ON app.tb_child
    FOR EACH ROW EXECUTE FUNCTION app.fn_trg();
"""


@pytest.fixture
def conn(fresh_database_factory: Callable[[str], str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(fresh_database_factory("confiture_intro"), autocommit=True) as c:
        c.execute(DDL)
        yield c


def shape(result: IntrospectionResult) -> list[tuple]:
    return [
        (
            t.name,
            [(c.name, c.pg_type, c.nullable, c.is_primary_key) for c in t.columns],
            [(f.from_table, f.to_table, f.via_column, f.on_column) for f in t.outbound_fks],
            [(f.from_table, f.to_table, f.via_column, f.on_column) for f in t.inbound_fks],
            None if t.hints is None else (t.hints.surrogate_pk, t.hints.natural_id),
        )
        for t in result.tables
    ]


LOG = ("log", [("id", "integer", True, False)], [], [], (None, "id"))
TABLES = [
    (
        "tb_Mixed",
        [
            ("UserId", "bigint", False, True),
            ("amount", "numeric(10,2)", True, False),
            ("tags", "text[]", True, False),
            ("mood", "app.mood", True, False),
            ("at", "timestamp with time zone", True, False),
            ("email", "citext", True, False),
        ],
        [],
        [],
        None,
    ),
    (
        "tb_child",
        [
            ("pk_child", "bigint", False, True),
            ("id", "uuid", True, False),
            ("pa", "integer", True, False),
            ("pb", "integer", True, False),
            ("fk_parent", "bigint", False, False),
            ("ext_id", "bigint", True, False),
        ],
        # Constraint-name order (aa_, mm_, zz_), then key order within one.
        [
            (None, "tb_parent", "fk_parent", "pk_parent"),
            (None, "tb_ext", "ext_id", "id"),
            (None, "tb_pair", "pb", "b"),
            (None, "tb_pair", "pa", "a"),
        ],
        [],
        ("pk_child", "id"),
    ),
    (
        "tb_pair",
        [
            ("a", "integer", False, True),
            ("b", "integer", False, True),
            ("label", "character varying(50)", False, False),
        ],
        [],
        [("tb_child", None, "pb", "b"), ("tb_child", None, "pa", "a")],
        None,
    ),
    (
        "tb_parent",
        [("pk_parent", "bigint", False, True), ("id", "uuid", False, False)],
        [],
        [("tb_child", None, "fk_parent", "pk_parent")],
        ("pk_parent", "id"),
    ),
    # The partition is a table (relkind 'r'); its partitioned parent is not read.
    (
        "tb_part_2026",
        [("id", "integer", True, False), ("at", "date", True, False)],
        [],
        [],
        (None, "id"),
    ),
]


def test_introspect_reads_the_tb_tables(conn: psycopg.Connection) -> None:
    result = SchemaIntrospector(conn).introspect(schema="app")
    assert shape(result) == TABLES
    assert result.schema == "app"
    assert result.database == conn.info.dbname


def test_introspect_all_tables_adds_the_rest(conn: psycopg.Connection) -> None:
    result = SchemaIntrospector(conn).introspect(schema="app", all_tables=True)
    assert shape(result) == [LOG, *TABLES]


def test_introspect_without_hints(conn: psycopg.Connection) -> None:
    result = SchemaIntrospector(conn).introspect(schema="app", include_hints=False)
    assert [t.hints for t in result.tables] == [None] * len(TABLES)


def routine(info: FunctionInfo) -> tuple:
    return (
        info.schema,
        info.name,
        [(p.name, p.pg_type, p.mode.value) for p in info.params],
        info.return_type,
        info.returns_set,
        info.volatility.value,
        info.is_procedure,
        info.language,
        info.source,
        info.estimated_cost,
        info.comment,
        info.security_definer,
        info.search_path_pinned,
    )


FN_ADD_INT = (
    "app",
    "fn_add",
    [("a", "integer", "IN"), ("b", "integer", "IN")],
    "integer",
    False,
    "IMMUTABLE",
    False,
    "sql",
    " SELECT a + b ",
    100.0,
    "adds",
    False,
    False,
)
FN_ADD_TEXT = (
    "app",
    "fn_add",
    [("a", "text", "IN")],
    "text",
    False,
    "VOLATILE",
    False,
    "sql",
    " SELECT a ",
    100.0,
    None,
    False,
    False,
)
FN_ARR = (
    "app",
    "fn_arr",
    [("a", "character varying[]", "IN"), ("b", "app.mood", "IN"), ("c", 'app."tb_Mixed"', "IN")],
    "SETOF integer",
    True,
    "VOLATILE",
    False,
    "sql",
    " SELECT 1 ",
    100.0,
    None,
    False,
    False,
)
FN_OUT = (
    "app",
    "fn_out",
    [("x", "integer", "IN"), ("y", "integer", "OUT"), ("z", "text", "INOUT")],
    "record",
    False,
    "STABLE",
    False,
    "sql",
    " SELECT x, z ",
    100.0,
    None,
    False,
    False,
)
FN_SEC = (
    "app",
    "fn_sec",
    [],
    "void",
    False,
    "VOLATILE",
    False,
    "sql",
    " SELECT ",
    5.0,
    None,
    True,
    True,
)
FN_TAB = (
    "app",
    "fn_tab",
    [("", "integer", "IN"), ("k", "integer", "TABLE"), ("v", "text", "TABLE")],
    "TABLE(k integer, v text)",
    True,
    "VOLATILE",
    False,
    "sql",
    " SELECT 1, 'a' ",
    100.0,
    None,
    False,
    False,
)
FN_TRG = (
    "app",
    "fn_trg",
    [],
    "trigger",
    False,
    "VOLATILE",
    False,
    "plpgsql",
    " BEGIN RETURN NEW; END ",
    100.0,
    None,
    False,
    False,
)
FN_VAR = (
    "app",
    "fn_var",
    [("xs", "integer[]", "VARIADIC")],
    "integer",
    False,
    "VOLATILE",
    False,
    "sql",
    " SELECT 1 ",
    100.0,
    None,
    False,
    False,
)
PR_DO = (
    "app",
    "pr_do",
    [("a", "integer", "IN"), ("b", "integer", "INOUT")],
    None,
    False,
    "VOLATILE",
    True,
    "plpgsql",
    " BEGIN b := a; END ",
    100.0,
    None,
    False,
    False,
)


def test_functions_and_procedures_without_triggers(conn: psycopg.Connection) -> None:
    """Aggregates are not read; a trigger function only when asked for."""
    catalog = FunctionIntrospector(conn).introspect(schema="app")
    assert [routine(f) for f in catalog.functions] == [
        FN_ADD_INT,
        FN_ADD_TEXT,
        FN_ARR,
        FN_OUT,
        FN_SEC,
        FN_TAB,
        FN_VAR,
        PR_DO,
    ]
    assert catalog.schema == "app"
    assert catalog.database == conn.info.dbname


def test_trigger_functions_when_asked_for(conn: psycopg.Connection) -> None:
    catalog = FunctionIntrospector(conn).introspect(schema="app", include_triggers=True)
    assert [f.name for f in catalog.functions] == [
        "fn_add",
        "fn_add",
        "fn_arr",
        "fn_out",
        "fn_sec",
        "fn_tab",
        "fn_trg",
        "fn_var",
        "pr_do",
    ]
    assert routine(catalog.by_name("fn_trg")[0]) == FN_TRG


def test_a_name_pattern_is_like(conn: psycopg.Connection) -> None:
    catalog = FunctionIntrospector(conn).introspect(schema="app", name_pattern=r"fn\_a%")
    assert [routine(f) for f in catalog.functions] == [FN_ADD_INT, FN_ADD_TEXT, FN_ARR]


def test_introspect_one_is_exact(conn: psycopg.Connection) -> None:
    found = FunctionIntrospector(conn).introspect_one("app", "fn_add")
    assert [routine(f) for f in found] == [FN_ADD_INT, FN_ADD_TEXT]
    assert FunctionIntrospector(conn).introspect_one("app", "fn_a%") == []


def test_an_extension_routine_is_introspected(conn: psycopg.Connection) -> None:
    """The introspector reports what the schema holds, the extension's own included."""
    names = {f.name for f in FunctionIntrospector(conn).introspect(schema="public").functions}
    assert {"citext", "texticlike"} <= names
