"""A ``NOT NULL … NOT VALID`` column may hold NULLs, and the model says so (#605).

PostgreSQL 18 stores a NOT NULL as a constraint that can be added ``NOT VALID``:
``attnotnull`` is then true while the table still holds the NULLs it held before.
``Column.not_null_validated`` is that fact, read from the tree here (the live side is
``tests/integration/test_not_null_validity_live.py``): the tree's ``ALTER TABLE …
ADD … NOT NULL … NOT VALID`` leaves it false; ``VALIDATE CONSTRAINT`` and ``SET NOT
NULL`` validate it. Two sides that differ in it alone are one
``ColumnNotNullValidityChanged``, rendered as DDL both ways and reported by drift as
the ``nullable_mismatch`` the column's nullability already uses.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

import pglast
import pytest

from confiture.core import destructive, git_accompaniment
from confiture.core.change_set import classify_statements
from confiture.core.change_set.diff_tiers import tier_of
from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.drift import DriftSeverity, DriftType, SchemaDriftDetector
from confiture.core.risk_tier import RiskTier, worst_tier
from confiture.core.schema_change import ColumnNotNullValidityChanged
from confiture.core.schema_model import Column, SchemaModel
from confiture.core.schema_read import read_text
from tests.unit._schema_models import column, model, table

TABLE = "CREATE TABLE t (a INT, b INT);\n"
NOT_VALID = TABLE + "ALTER TABLE t ADD CONSTRAINT nn_a NOT NULL a NOT VALID;\n"


def _column(sql: str, name: str = "a") -> Column:
    tables = read_text(sql).model.tables
    (held,) = tables.values()
    return next(c for c in held.columns if c.folded == name)


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------


def test_a_not_null_added_not_valid_is_not_null_and_not_validated() -> None:
    a = _column(NOT_VALID)
    assert (a.not_null, a.not_null_validated) == (True, False)


def test_an_unnamed_not_null_added_not_valid_reads_the_same() -> None:
    a = _column(TABLE + "ALTER TABLE t ADD NOT NULL a NOT VALID;\n")
    assert (a.not_null, a.not_null_validated) == (True, False)


def test_a_not_null_added_at_table_level_is_not_null() -> None:
    a = _column(TABLE + "ALTER TABLE t ADD CONSTRAINT nn_a NOT NULL a;\n")
    assert (a.not_null, a.not_null_validated) == (True, True)


def test_create_table_validates_a_not_valid_not_null() -> None:
    """Measured on 18.4: a new table is empty, so PostgreSQL stores it validated."""
    a = _column("CREATE TABLE t (a INT, CONSTRAINT nn_a NOT NULL a NOT VALID);\n")
    assert (a.not_null, a.not_null_validated) == (True, True)


def test_validate_constraint_validates_it() -> None:
    a = _column(NOT_VALID + "ALTER TABLE t VALIDATE CONSTRAINT nn_a;\n")
    assert (a.not_null, a.not_null_validated) == (True, True)


def test_validating_another_constraint_leaves_it_unvalidated() -> None:
    a = _column(NOT_VALID + "ALTER TABLE t VALIDATE CONSTRAINT some_check;\n")
    assert a.not_null_validated is False


def test_set_not_null_validates_it() -> None:
    """Measured on 18.4: ``SET NOT NULL`` scans the table and validates the constraint."""
    a = _column(NOT_VALID + "ALTER TABLE t ALTER COLUMN a SET NOT NULL;\n")
    assert (a.not_null, a.not_null_validated) == (True, True)


def test_drop_not_null_leaves_a_nullable_column() -> None:
    a = _column(NOT_VALID + "ALTER TABLE t ALTER COLUMN a DROP NOT NULL;\n")
    assert (a.not_null, a.not_null_validated) == (False, True)


def test_not_valid_on_a_column_already_not_null_keeps_it_validated() -> None:
    a = _column("CREATE TABLE t (a INT NOT NULL);\nALTER TABLE t ADD NOT NULL a NOT VALID;\n")
    assert (a.not_null, a.not_null_validated) == (True, True)


def test_an_ordinary_column_is_validated() -> None:
    b = _column(NOT_VALID, "b")
    assert (b.not_null, b.not_null_validated) == (False, True)


# ---------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------

VALIDATED = TABLE + "ALTER TABLE t ALTER COLUMN a SET NOT NULL;\n"


def _changes(old: str, new: str) -> list[object]:
    return list(SchemaDiffer().compare(old, new).changes)


def test_validity_alone_is_one_change() -> None:
    (change,) = _changes(NOT_VALID, VALIDATED)
    assert isinstance(change, ColumnNotNullValidityChanged)
    assert (change.column, change.validated) == ("a", True)


def test_the_same_validity_is_no_change() -> None:
    assert _changes(NOT_VALID, NOT_VALID) == []


def test_a_nullable_column_has_no_validity_to_compare() -> None:
    (change,) = _changes(TABLE, NOT_VALID)
    assert type(change).__name__ == "ColumnNullabilityChanged"


def _statements(sql: str | None) -> list[str]:
    assert sql is not None and sql.endswith("\n")
    return [type(raw.stmt).__name__ for raw in pglast.parse_sql(sql)]


@pytest.mark.parametrize(("old", "new"), [(NOT_VALID, VALIDATED), (VALIDATED, NOT_VALID)])
def test_both_directions_render_and_undo(old: str, new: str) -> None:
    (change,) = _changes(old, new)
    renderer = DifferSQLGenerator()
    up, down = renderer.generate_up(change), renderer.generate_down(change)
    assert _statements(up) and _statements(down)
    (back,) = _changes(new, old)
    assert renderer.generate_up(back) == down


def test_validating_sets_not_null_which_validates() -> None:
    (change,) = _changes(NOT_VALID, VALIDATED)
    assert (
        DifferSQLGenerator().generate_up(change) == "ALTER TABLE t ALTER COLUMN a SET NOT NULL;\n"
    )


def test_unvalidating_drops_and_adds_the_not_null_not_valid() -> None:
    (change,) = _changes(VALIDATED, NOT_VALID)
    assert DifferSQLGenerator().generate_up(change) == (
        "ALTER TABLE t ALTER COLUMN a DROP NOT NULL;\nALTER TABLE t ADD NOT NULL a NOT VALID;\n"
    )


@pytest.mark.parametrize(("old", "new"), [(NOT_VALID, VALIDATED), (VALIDATED, NOT_VALID)])
def test_the_declared_tier_is_the_tier_of_what_is_written(old: str, new: str) -> None:
    (change,) = _changes(old, new)
    written = classify_statements(DifferSQLGenerator().generate_up(change) or "")
    assert tier_of(change) == worst_tier(entry.tier for entry in written)
    assert isinstance(tier_of(change), RiskTier)


def test_it_loses_no_data_and_is_no_body_change() -> None:
    (change,) = _changes(NOT_VALID, VALIDATED)
    assert destructive.data_loss_reason(change) is None
    assert git_accompaniment.is_body_change(change) is False


def test_the_wire_says_valid_or_not() -> None:
    (change,) = _changes(NOT_VALID, VALIDATED)
    wire = change.to_wire()
    assert (wire.column, wire.old_value, wire.new_value) == ("a", "NOT VALID", "VALID")


# ---------------------------------------------------------------------------
# Drift
# ---------------------------------------------------------------------------


def _drift(
    expected: SchemaModel, actual: SchemaModel
) -> list[tuple[DriftType, DriftSeverity, str]]:
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("db",)
    report = SchemaDriftDetector(conn).compare_schemas(expected, actual)
    return [(i.drift_type, i.severity, i.object_name) for i in report.drift_items]


def test_drift_reports_a_not_null_the_database_never_validated() -> None:
    declared = column("a", nullable=False)
    expected = model(table("t", declared))
    actual = model(table("t", replace(declared, not_null_validated=False)))
    assert _drift(expected, actual) == [
        (DriftType.NULLABLE_MISMATCH, DriftSeverity.WARNING, "public.t.a")
    ]


def test_drift_is_quiet_when_both_are_validated() -> None:
    expected = model(table("t", column("a", nullable=False)))
    assert _drift(expected, expected) == []


def test_dropping_a_not_null_constraint_makes_its_column_nullable() -> None:
    """Measured on PostgreSQL 18.4, by the tree's name or PostgreSQL's ``<table>_<column>_not_null``."""
    from confiture.platform import parse_schema

    model = parse_schema(
        "CREATE TABLE t (a int NOT NULL, b int, c int NOT NULL, CONSTRAINT b_nn NOT NULL b);\n"
        "ALTER TABLE t DROP CONSTRAINT t_a_not_null;\n"
        "ALTER TABLE t DROP CONSTRAINT b_nn;\n"
    )
    (table,) = model.tables.values()
    assert {c.name: c.not_null for c in table.columns} == {"a": False, "b": False, "c": True}
