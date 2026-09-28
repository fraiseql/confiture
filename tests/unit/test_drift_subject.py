"""A drift item names what it is about in parts, never joined (#505).

``object`` joins schema, relation and name with dots, so a constraint named
``tb_dotted.org.fk`` on ``app.tb_dotted`` read ``app.tb_dotted.tb_dotted.org.fk``:
several splits, and nothing to tell them apart. ``subject`` carries the parts
apart (``schema``, ``relation``, ``name``, a routine's ``arguments``, a grant's
``role``), as #478 did for the model. ``object`` stays, for the reader of today.

The DDL side refuses a name that needs quotes (``DIFFER_403``, as ``migrate
diff`` does), so on that side a dot never reaches a finding. The live side is
read whatever it holds, which is why the parts matter: an extra constraint in
the database is reported under the name the database gives it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import confiture.core.drift as drift_module
from confiture.core.drift import (
    DriftReport,
    DriftSubject,
    DriftType,
    SchemaDriftDetector,
    parse_expected_schema,
)
from confiture.core.schema_model import Constraint, RelationName, SchemaModel
from confiture.exceptions import DifferError
from tests.unit._schema_models import column, index, model, table


def _compare(expected: SchemaModel, actual: SchemaModel, *, objects: bool = False) -> DriftReport:
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("db",)
    return SchemaDriftDetector(conn).compare_schemas(expected, actual, objects=objects)


def _subjects(report: DriftReport) -> dict[DriftType, DriftSubject | None]:
    return {item.drift_type: item.subject for item in report.drift_items}


FK = Constraint(
    kind="foreign_key",
    name="tb_item_org_fk",
    columns=("org_id",),
    ref_table=RelationName("core", "tb_org"),
    ref_columns=("id",),
)


# ---------------------------------------------------------------------------
# Every finding on a table carries the table's parts
# ---------------------------------------------------------------------------


def test_a_missing_table_is_its_schema_and_relation() -> None:
    report = _compare(model(table("app.tb_item", column("id"))), model())
    assert _subjects(report)[DriftType.MISSING_TABLE] == DriftSubject("app", "tb_item")


def test_an_unqualified_table_is_in_the_default_schema() -> None:
    report = _compare(model(), model(table("tb_item", column("id"))))
    assert _subjects(report)[DriftType.EXTRA_TABLE] == DriftSubject("public", "tb_item")


def test_a_column_finding_names_the_column() -> None:
    expected = model(table("app.tb_item", column("id"), column("gone")))
    actual = model(table("app.tb_item", column("id", "text"), column("extra")))
    assert _subjects(_compare(expected, actual)) == {
        DriftType.MISSING_COLUMN: DriftSubject("app", "tb_item", "gone"),
        DriftType.EXTRA_COLUMN: DriftSubject("app", "tb_item", "extra"),
        DriftType.TYPE_MISMATCH: DriftSubject("app", "tb_item", "id"),
    }


def test_a_column_order_finding_is_the_table() -> None:
    expected = model(table("tb_item", column("a"), column("b")))
    actual = model(table("tb_item", column("b"), column("a")))
    assert _subjects(_compare(expected, actual)) == {
        DriftType.COLUMN_ORDER_MISMATCH: DriftSubject("public", "tb_item"),
    }


def test_an_index_finding_names_the_index() -> None:
    expected = model(table("tb_item", column("a"), indexes=[index("ix_a", "tb_item", "a")]))
    actual = model(table("tb_item", column("a"), indexes=[index("ix_tmp", "tb_item", "a")]))
    assert _subjects(_compare(expected, actual)) == {
        DriftType.MISSING_INDEX: DriftSubject("public", "tb_item", "ix_a"),
        DriftType.EXTRA_INDEX: DriftSubject("public", "tb_item", "ix_tmp"),
    }


def test_a_constraint_mismatch_names_the_constraint() -> None:
    live = Constraint(**{**FK.__dict__, "ref_table": RelationName("app", "tb_org")})
    expected = model(table("app.tb_item", column("org_id"), constraints=[FK]))
    actual = model(table("app.tb_item", column("org_id"), constraints=[live]))
    assert _subjects(_compare(expected, actual)) == {
        DriftType.CONSTRAINT_MISMATCH: DriftSubject("app", "tb_item", "tb_item_org_fk"),
    }


def test_an_unnamed_constraint_has_no_name() -> None:
    """Its definition is in ``expected``; the label in ``object`` is not a name."""
    unnamed = Constraint(kind="unique", name=None, columns=("org_id",))
    report = _compare(
        model(table("tb_item", column("org_id"), constraints=[unnamed])),
        model(table("tb_item", column("org_id"))),
    )
    assert _subjects(report) == {DriftType.MISSING_CONSTRAINT: DriftSubject("public", "tb_item")}


def test_a_dotted_live_name_stays_one_name() -> None:
    """The #505 shape: the parts survive where the joined string cannot."""
    dotted = Constraint(**{**FK.__dict__, "name": "tb_dotted.org.fk"})
    report = _compare(
        model(table("app.tb_dotted", column("org_id"))),
        model(table("app.tb_dotted", column("org_id"), constraints=[dotted])),
    )
    (item,) = report.drift_items
    assert item.object_name == "app.tb_dotted.tb_dotted.org.fk"
    assert item.to_dict()["subject"] == {
        "schema": "app",
        "relation": "tb_dotted",
        "name": "tb_dotted.org.fk",
        "arguments": None,
        "role": None,
    }


# ---------------------------------------------------------------------------
# Views, triggers and routines
# ---------------------------------------------------------------------------

DECLARED = """
CREATE SCHEMA core;
CREATE TABLE core.tb_widget (id BIGINT);
CREATE VIEW core.v_widget AS SELECT 1 AS id;
CREATE FUNCTION core.fn_touch() RETURNS TRIGGER LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;
CREATE TRIGGER trg_touch BEFORE UPDATE ON core.tb_widget
    FOR EACH ROW EXECUTE FUNCTION core.fn_touch();
CREATE FUNCTION core.fn_gone(widget_id BIGINT, label TEXT) RETURNS BIGINT
    LANGUAGE sql AS $$ SELECT 1 $$;
"""


def _missing_objects() -> dict[str, DriftSubject | None]:
    expected = parse_expected_schema(DECLARED).model
    actual = SchemaModel(tables=expected.tables)
    report = _compare(expected, actual, objects=True)
    return {item.object_name: item.subject for item in report.drift_items}


def test_a_view_is_its_schema_and_relation() -> None:
    assert _missing_objects()["core.v_widget"] == DriftSubject("core", "v_widget")


def test_a_trigger_is_named_on_its_table() -> None:
    subjects = _missing_objects()
    (trigger,) = [s for s in subjects.values() if s and s.name == "trg_touch"]
    assert trigger == DriftSubject("core", "tb_widget", "trg_touch")


def test_a_routine_carries_its_arguments() -> None:
    subjects = _missing_objects()
    (routine,) = [s for s in subjects.values() if s and s.name == "fn_gone"]
    assert routine == DriftSubject("core", None, "fn_gone", arguments=("bigint", "text"))


# ---------------------------------------------------------------------------
# Every item the module builds carries one; the DDL side refuses a quoted name
# ---------------------------------------------------------------------------


def test_every_drift_item_the_module_builds_carries_a_subject() -> None:
    tree = ast.parse(Path(drift_module.__file__).read_text(encoding="utf-8"))
    built = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "DriftItem"
    ]
    assert built, "the walker found no DriftItem(...) call"
    without = [node.lineno for node in built if "subject" not in {k.arg for k in node.keywords}]
    assert without == []


@pytest.mark.parametrize(
    "ddl",
    [
        pytest.param('CREATE TABLE app."tb.dotted" (id INT);', id="dotted-table"),
        pytest.param(
            'CREATE TABLE t (org_id INT, CONSTRAINT "t.org.fk" UNIQUE (org_id));',
            id="dotted-constraint",
        ),
        pytest.param('CREATE TABLE "User" (id INT);', id="capitalised"),
    ],
)
def test_the_expected_schema_refuses_a_name_that_needs_quotes(ddl: str) -> None:
    with pytest.raises(DifferError) as caught:
        parse_expected_schema(ddl)
    assert caught.value.error_code == "DIFFER_403"
