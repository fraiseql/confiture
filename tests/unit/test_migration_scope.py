"""One migration scope: what the statements before this one did, as every classifier reads it.

A statement is judged in the context of the file that holds it — the transaction
it runs in, a constraint an earlier statement added, a TVIEW an earlier statement
dropped. Each classifier used to keep its own fold of that context; this is the
one (``core/migration_scope``).
"""

import pglast.parser
import pytest

from confiture.core.migration_scope import AddedConstraint, walk

_FK = (
    "ALTER TABLE tb_user ADD CONSTRAINT fk_user_org FOREIGN KEY (org) "
    "REFERENCES tb_org (id) NOT VALID;\n"
)


def _steps(sql: str) -> list:
    return list(walk(sql))


def test_every_statement_is_a_step_in_order() -> None:
    steps = _steps("CREATE TABLE a (id int);\nCREATE TABLE b (id int);")

    assert [type(step.statement.stmt).__name__ for step in steps] == ["CreateStmt"] * 2
    assert [step.statement.line for step in steps] == [1, 2]


def test_a_file_runs_in_one_transaction_unless_it_cannot() -> None:
    [alone] = _steps("CREATE INDEX ix ON t (c);")
    concurrently = _steps("CREATE INDEX CONCURRENTLY ix ON t (c);")

    assert alone.before.transactional
    assert not concurrently[0].before.transactional


def test_a_constraint_added_is_in_the_scope_after_it() -> None:
    [add, validate] = _steps(_FK + "ALTER TABLE tb_user VALIDATE CONSTRAINT fk_user_org;")

    assert add.before.added_constraint(None, "tb_user", "fk_user_org") is None
    assert validate.before.added_constraint(None, "tb_user", "fk_user_org") == AddedConstraint(
        foreign_key=True, not_valid=True, referenced="tb_org"
    )


@pytest.mark.parametrize(("schema", "found"), [("public", True), ("other", False)])
def test_a_constraint_is_matched_by_identity(schema: str, found: bool) -> None:
    """A tightening fact: a match makes a verdict stricter, so the default schema folds."""
    [_, after] = _steps(_FK + "SELECT 1;")

    assert (after.before.added_constraint(schema, "tb_user", "fk_user_org") is not None) is found


def test_a_check_added_is_no_foreign_key() -> None:
    [_, after] = _steps(
        "ALTER TABLE tb_user ADD CONSTRAINT ck_org CHECK (org > 0) NOT VALID;\nSELECT 1;"
    )

    assert after.before.added_constraint(None, "tb_user", "ck_org") == AddedConstraint(
        foreign_key=False, not_valid=True, referenced=None
    )


@pytest.mark.parametrize(
    "drop", ["DROP TABLE tv_order;", "SELECT tviews.pg_tviews_drop('tv_order');"]
)
def test_a_tview_dropped_is_in_the_scope_after_it(drop: str) -> None:
    [step] = _steps(drop)

    assert "public.tv_order" not in step.before.dropped_tviews
    assert "public.tv_order" in step.after.dropped_tviews


def test_a_file_the_parser_rejects_raises() -> None:
    with pytest.raises(pglast.parser.ParseError):
        _steps("CREATE TABLE (")


# --- relations the file creates (a loosening fact, matched as written) --------------


def _created_after(sql: str) -> dict:
    """The relations the scope holds as created once every statement of *sql* ran."""
    *_, last = _steps(sql + "\nSELECT 1;")
    return last.before.created


@pytest.mark.parametrize(
    "create",
    [
        "CREATE TABLE t (id int);",
        "CREATE TABLE t AS SELECT 1 AS id;",
        "CREATE MATERIALIZED VIEW t AS SELECT 1 AS id;",
    ],
)
def test_a_relation_postgresql_proves_new_is_created(create: str) -> None:
    [step, _] = _steps(create + "\nSELECT 1;")

    assert step.before.fresh(None, "t") is None
    assert step.after.fresh(None, "t") is not None


@pytest.mark.parametrize(
    "create",
    [
        "CREATE TABLE IF NOT EXISTS t (id int);",
        "CREATE TABLE IF NOT EXISTS t AS SELECT 1 AS id;",
        "CREATE MATERIALIZED VIEW IF NOT EXISTS t AS SELECT 1 AS id;",
        "CREATE TABLE t PARTITION OF parent FOR VALUES IN (1);",
        "CREATE TABLE t (id int) INHERITS (parent);",
        "SELECT 1 AS id INTO t;",
    ],
)
def test_a_relation_that_may_already_exist_or_reaches_another_is_not_created(
    create: str,
) -> None:
    assert _created_after(create) == {}


def test_a_tview_pg_tviews_creates_is_created_and_one_it_may_replace_is_not() -> None:
    created = _created_after("SELECT tviews.pg_tviews_create('tv_a', 'SELECT 1 AS id');")
    replaced = _created_after(
        "SELECT tviews.pg_tviews_create('tv_a', 'SELECT 1 AS id');\n"
        "SELECT tviews.pg_tviews_create_or_replace('tv_a', 'SELECT 2 AS id');"
    )

    assert set(created) == {(None, "tv_a")}
    assert replaced == {}


@pytest.mark.parametrize(
    ("create", "written", "other"),
    [("CREATE TABLE t (id int);", (None, "t"), ("public", "t")),
     ("CREATE TABLE app.t (id int);", ("app", "t"), (None, "t"))],
)  # fmt: skip
def test_a_created_relation_matches_only_as_written(
    create: str, written: tuple, other: tuple
) -> None:
    [_, after] = _steps(create + "\nSELECT 1;")

    assert after.before.fresh(*written) is not None
    assert after.before.fresh(*other) is None


@pytest.mark.parametrize(
    "then",
    [
        "DROP TABLE public.t;",
        "DROP TABLE t;",
        "ALTER TABLE t SET SCHEMA app;",
        "DROP SCHEMA public CASCADE;",
        "SET search_path = app;",
        "RESET search_path;",
        "DO $$ BEGIN PERFORM 1; END $$;",
        "SELECT make_things();",
        "INSERT INTO log VALUES (now());",
        "CALL make_things();",
        "ALTER TABLE t ATTACH PARTITION existing FOR VALUES IN (1);",
        "ALTER TABLE t INHERIT existing;",
    ],
)
def test_a_statement_that_may_move_or_hide_the_relation_forgets_it(then: str) -> None:
    assert _created_after("CREATE TABLE t (id int);\n" + then) == {}


def test_a_qualified_relation_survives_a_search_path_change() -> None:
    assert set(_created_after("CREATE TABLE app.t (id int);\nSET search_path = other;")) == {
        ("app", "t")
    }


def test_a_rename_moves_the_relation() -> None:
    assert set(_created_after("CREATE TABLE t (id int);\nALTER TABLE t RENAME TO u;")) == {
        (None, "u")
    }


def test_a_pg_tviews_call_alone_keeps_the_scope() -> None:
    created = _created_after("CREATE TABLE t (id int);\nSELECT tviews.pg_tviews_drop('tv_other');")

    assert set(created) == {(None, "t")}


@pytest.mark.parametrize(
    ("sql", "references_existing"),
    [
        ("CREATE TABLE u (id int, tid int REFERENCES t (id));", True),
        ("CREATE TABLE t (id int PRIMARY KEY);\n"
         "CREATE TABLE u (id int, tid int REFERENCES t (id));", False),
        ("CREATE TABLE u (id int PRIMARY KEY, pid int REFERENCES u (id));", False),
        ("CREATE TABLE u (id int, tid int, FOREIGN KEY (tid) REFERENCES t (id));", True),
        ("CREATE TABLE u (id int, tid int);\n"
         "ALTER TABLE u ADD CONSTRAINT fk FOREIGN KEY (tid) REFERENCES t (id);", True),
    ],
)  # fmt: skip
def test_a_created_relation_knows_whether_it_references_one_that_existed(
    sql: str, references_existing: bool
) -> None:
    assert _created_after(sql)[(None, "u")].references_existing is references_existing


def _scope_after(sql: str):
    *_, last = _steps(sql + "\nSELECT 1;")
    return last.before


def test_an_exempt_operation_on_a_created_relation_is_exempt() -> None:
    scope = _scope_after("CREATE TABLE t (id int);")

    assert scope.exempts("create_index", None, "t")
    assert not scope.exempts("create_index", "public", "t")
    assert not scope.exempts("create_index", None, "other")
    assert not scope.exempts("revoke", None, "t")


def test_a_cascade_reaches_past_the_created_relation() -> None:
    scope = _scope_after("CREATE TABLE t (id int);")

    assert scope.exempts("truncate", None, "t")
    assert not scope.exempts("truncate", None, "t", cascade=True)


def test_dropping_a_created_relation_that_references_an_existing_one_is_not_exempt() -> None:
    scope = _scope_after("CREATE TABLE u (id int, tid int REFERENCES t (id));")

    assert scope.exempts("create_index", None, "u")
    assert not scope.exempts("drop_table", None, "u")


@pytest.mark.parametrize(("target", "exempt"), [((None, "t"), True), ((None, "x"), False)])
def test_a_foreign_key_is_exempt_only_onto_a_created_relation(target: tuple, exempt: bool) -> None:
    scope = _scope_after("CREATE TABLE t (id int PRIMARY KEY);\nCREATE TABLE u (tid int);")

    assert scope.exempts("add_constraint", None, "u", references=target) is exempt
