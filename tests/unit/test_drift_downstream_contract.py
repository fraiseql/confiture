"""A drift kind a downstream gate relies on keeps its name and its grade.

fraisier (from v0.82.0) validates ``post_migrate_check.escalate`` against a closed
list of confiture drift kinds, ``ESCALATABLE_KINDS``, and fails a deploy on
``critical`` drift. A project that writes ``escalate: [constraint_mismatch]`` is
saying "fail my deploy when a named constraint no longer says what the DDL
declares" — a foreign key re-pointed at another table under its own name.

Since #506 confiture grades a constraint the database lost (``missing_constraint``)
and one that says something else (``constraint_mismatch``) ``critical`` itself: a
lost or re-pointed foreign key is a loss of referential integrity, not a style
difference, and a gate should not need a consumer's own table to fail on it. An
``escalate`` naming either kind still validates, and now has nothing to promote.
The grade is pinned because a gate relies on it:

- rename a kind, and every fraisier config naming it fails validation;
- downgrade it, and deploys that failed on a lost foreign key pass — silently,
  for every project that trusted the default rather than listing it in
  ``escalate``.

``extra_constraint`` stays ``info`` and is not in ``ESCALATABLE_KINDS``: a
constraint the database has beyond the DDL loses no data. Changing a row is a
breaking change for fraisier: tell the fraisier maintainers, and flag it ⚠️ in the
CHANGELOG, in the same change.

Each row is checked on what the detector *emits* and on the JSON it writes, not
on the enum's declaration: severity is chosen where the item is built.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from confiture.core.drift import DriftItem, DriftReport, SchemaDriftDetector
from confiture.core.schema_model import Constraint, RelationName, SchemaModel
from tests.unit._schema_models import column, model, table

_DECLARED_FK = Constraint(
    kind="foreign_key",
    name="tb_item_org_fk",
    columns=("org_id",),
    ref_table=RelationName("core", "tb_org"),
    ref_columns=("id",),
)
_REPOINTED_FK = Constraint(
    kind="foreign_key",
    name="tb_item_org_fk",
    columns=("org_id",),
    ref_table=RelationName("app", "tb_org"),
    ref_columns=("id",),
)


def _item_table(fk: Constraint) -> SchemaModel:
    return model(table("tb_item", column("org_id"), constraints=[fk]))


def _item_table_without_fk() -> SchemaModel:
    return model(table("tb_item", column("org_id")))


def _compare(expected: SchemaModel, actual: SchemaModel) -> DriftReport:
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("db",)
    return SchemaDriftDetector(conn).compare_schemas(expected, actual)


#: kind (as fraisier spells it) → (severity a gate relies on, a pair of models
#: whose comparison emits that kind).
FRAISIER_ESCALATABLE: dict[str, tuple[str, tuple[SchemaModel, SchemaModel]]] = {
    "constraint_mismatch": ("critical", (_item_table(_DECLARED_FK), _item_table(_REPOINTED_FK))),
    "missing_constraint": ("critical", (_item_table(_DECLARED_FK), _item_table_without_fk())),
}


def _emitted(kind: str) -> DriftItem:
    _, (expected, actual) = FRAISIER_ESCALATABLE[kind]
    items = [i for i in _compare(expected, actual).drift_items if i.drift_type.value == kind]
    assert len(items) == 1, f"the {kind} scenario no longer emits exactly one {kind}"
    return items[0]


@pytest.mark.parametrize("kind", sorted(FRAISIER_ESCALATABLE))
def test_an_escalatable_kind_is_emitted_at_the_severity_fraisier_gates_on(kind: str) -> None:
    severity, _ = FRAISIER_ESCALATABLE[kind]
    assert _emitted(kind).severity.value == severity, (
        f"{kind} must stay {severity}: fraisier's deploy gate fails on it by default "
        f"(#506). Changing it is a breaking change for fraisier."
    )


@pytest.mark.parametrize("kind", sorted(FRAISIER_ESCALATABLE))
def test_an_escalatable_kind_reaches_the_json_under_its_name(kind: str) -> None:
    severity, _ = FRAISIER_ESCALATABLE[kind]
    wire = _emitted(kind).to_dict()
    assert (wire["type"], wire["severity"]) == (kind, severity)
