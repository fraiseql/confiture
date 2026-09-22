"""A schema change's tier is the change set's tier for the SQL confiture writes for it.

A variant declares its tier (``change_set.diff_tiers.tier_of``)
from the one taxonomy the change set uses. This holds the two readings to each
other — the tier a difference declares, and the worst tier ``classify_statements``
(the classifier ``migrate preflight`` runs, and the one that writes each generated
statement's ``-- confiture:tier`` directive) gives the statement the renderer writes
for it — over every kind, and over each kind compared by definition that a
migration is derived for.

Two disagreements are declared — a type change's source, and an addition written
``CREATE OR REPLACE`` — and each entry is asserted to **still disagree**: the day the renderer or the classifier closes one, its entry
fails and goes. A change the renderer writes no statement for has nothing to
agree with and is not compared.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.core.change_set import classify_statements
from confiture.core.change_set.diff_tiers import tier_of
from confiture.core.differ import SchemaDiffer
from confiture.core.differ_sql import DERIVED_KINDS, DifferSQLGenerator
from confiture.core.risk_tier import RiskTier, worst_tier
from confiture.core.schema_change import ObjectAdded, SchemaChange

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "every_change"

#: Where the difference knows what the statement cannot say, and why.
DISAGREEMENTS: dict[str, str] = {
    "ColumnTypeChanged": (
        "a statement states the target type and never the source, so the change set "
        "leaves it untiered without a live database (#199); the diff holds both types"
    ),
    "ObjectAdded[view]": (
        "an added view is written CREATE OR REPLACE so the migration re-applies; the "
        "statement reads as a replacement, the change is an addition"
    ),
    "ObjectAdded[function]": "as a view: CREATE OR REPLACE, and an addition",
    "ObjectAdded[procedure]": "as a view: CREATE OR REPLACE, and an addition",
}

_TABLE = "CREATE TABLE t (a int);"
#: One definition per kind a migration is derived for, and a second to replace it with.
_DEFINITIONS: dict[str, tuple[str, str]] = {
    "view": ("CREATE VIEW v AS SELECT 1 AS one;", "CREATE VIEW v AS SELECT 2 AS one;"),
    "matview": (
        "CREATE MATERIALIZED VIEW m AS SELECT 1 AS one;",
        "CREATE MATERIALIZED VIEW m AS SELECT 2 AS one;",
    ),
    "function": (
        "CREATE FUNCTION f() RETURNS int LANGUAGE sql AS 'select 1';",
        "CREATE FUNCTION f() RETURNS int LANGUAGE sql AS 'select 2';",
    ),
    "procedure": (
        "CREATE PROCEDURE p() LANGUAGE sql AS 'select 1';",
        "CREATE PROCEDURE p() LANGUAGE sql AS 'select 2';",
    ),
    "aggregate": (
        "CREATE AGGREGATE ag(int) (SFUNC = int4pl, STYPE = int);",
        "CREATE AGGREGATE ag(int) (SFUNC = int4pl, STYPE = int, INITCOND = '0');",
    ),
    "domain": ("CREATE DOMAIN d AS int;", "CREATE DOMAIN d AS int CHECK (VALUE > 0);"),
    "type": ("CREATE TYPE ct AS (a int);", "CREATE TYPE ct AS (a int, b int);"),
}


def _label(change: SchemaChange) -> str:
    if isinstance(change, ObjectAdded):
        return f"ObjectAdded[{change.ref.kind}]"
    return type(change).__name__


def _changes() -> list[SchemaChange]:
    old = (FIXTURES / "old.sql").read_text()
    new = (FIXTURES / "new.sql").read_text()
    found = list(SchemaDiffer().compare(old, new).changes)
    for first, second in _DEFINITIONS.values():
        before, after = _TABLE + first, _TABLE + second
        for old_sql, new_sql in (("", before), (before, ""), (before, after)):
            found.extend(
                change
                for change in SchemaDiffer().compare(old_sql, new_sql).changes
                if getattr(change, "ref", None) is not None
            )
    return found


CHANGES = _changes()


def _statement_tier(change: SchemaChange) -> tuple[bool, RiskTier | None]:
    """Whether the renderer writes a statement for *change*, and the change set's tier for it."""
    sql = DifferSQLGenerator(force_destructive=True).generate_up(change)
    entries = classify_statements(sql) if sql else []
    return bool(entries), worst_tier(entry.tier for entry in entries)


def test_every_derived_kind_is_measured() -> None:
    measured = {change.ref.kind for change in CHANGES if getattr(change, "ref", None)}
    assert measured >= DERIVED_KINDS


@pytest.mark.parametrize("change", CHANGES, ids=_label)
def test_a_change_declares_the_tier_of_what_confiture_writes_for_it(
    change: SchemaChange,
) -> None:
    written, statement_tier = _statement_tier(change)
    if not written:
        pytest.skip("the renderer writes no statement for this change")
    declared = tier_of(change)
    if _label(change) in DISAGREEMENTS:
        assert declared != statement_tier, (
            f"{_label(change)} now agrees with the change set: delete its DISAGREEMENTS entry"
        )
    else:
        assert declared == statement_tier


def test_every_declared_disagreement_is_seen() -> None:
    assert set(DISAGREEMENTS) <= {_label(change) for change in CHANGES}
