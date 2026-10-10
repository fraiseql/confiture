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
