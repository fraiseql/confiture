"""Drift compares the schema model with itself: every fact the model holds, both sides.

The expected side is the lint inventory's ``SchemaModel``, the live side is
``live_catalog``'s, and ``compare_schemas`` reads the one against the other — so a
constraint and a default, which the model has always held, are compared at last.
``missing_constraint``, ``extra_constraint`` and ``default_mismatch`` were published
and never emitted (#303, #308, #309); each is pinned here by a pair of models that
differ in that one fact, beside the pairs that must *not* differ: an unnamed
foreign key and the name PostgreSQL gave it, ``'x'`` and ``'x'::text``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from confiture.core.drift import DriftReport, DriftSeverity, DriftType, SchemaDriftDetector
from confiture.core.schema_model import Constraint, SchemaModel
from tests.unit._schema_models import column, index, model, table


def _compare(expected: SchemaModel, actual: SchemaModel) -> DriftReport:
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("db",)
    return SchemaDriftDetector(conn).compare_schemas(expected, actual)


def _items(report: DriftReport) -> list[tuple[DriftType, DriftSeverity, str]]:
    return [(i.drift_type, i.severity, i.object_name) for i in report.drift_items]


PKEY = Constraint(kind="primary_key", name="users_pkey", columns=("id",))
EMAIL_UQ = Constraint(kind="unique", name="users_email_key", columns=("email",))
POSITIVE = Constraint(kind="check", name="users_id_positive", columns=("id",), expression="id > 0")


def _users(*extra: Constraint, default: str | None = "'active'") -> SchemaModel:
    return model(
        table(
            "users",
            column("id", nullable=False),
            column("status", "text", default=default),
            constraints=[PKEY, *extra],
        )
    )


# ---------------------------------------------------------------------------
# Two hand-built models, every kind of finding at once
# ---------------------------------------------------------------------------


def test_two_models_compare_fact_by_fact() -> None:
    expected = model(
        table(
            "users",
            column("id", nullable=False),
            column("email", "text", nullable=False),
            column("status", "text", default="'active'"),
            column("name", "text"),
            constraints=[PKEY, EMAIL_UQ],
            indexes=[index("idx_users_name", "users", "name", method="btree")],
        ),
        table("tenant.orders", column("id", "bigint")),
    )
    actual = model(
        table(
            "users",
            column("id", "bigint", nullable=False),
            column("email", "text"),
            column("status", "text", default="'inactive'::text"),
            column("legacy", "text"),
            constraints=[PKEY, POSITIVE],
            indexes=[
                index("users_pkey", "users", "id", unique=True, backs_constraint=True),
                index("idx_users_tmp", "users", "legacy", method="btree"),
            ],
        ),
        table("public.audit", column("id")),
    )

    report = _compare(expected, actual)

    critical, warning, info = DriftSeverity.CRITICAL, DriftSeverity.WARNING, DriftSeverity.INFO
    assert _items(report) == [
        (DriftType.MISSING_TABLE, critical, "tenant.orders"),
        (DriftType.EXTRA_TABLE, warning, "public.audit"),
        (DriftType.MISSING_COLUMN, critical, "public.users.name"),
        (DriftType.EXTRA_COLUMN, warning, "public.users.legacy"),
        (DriftType.NULLABLE_MISMATCH, warning, "public.users.email"),
        (DriftType.TYPE_MISMATCH, warning, "public.users.id"),
        (DriftType.DEFAULT_MISMATCH, warning, "public.users.status"),
        (DriftType.MISSING_INDEX, warning, "public.users.idx_users_name"),
        (DriftType.EXTRA_INDEX, info, "public.users.idx_users_tmp"),
        (DriftType.MISSING_CONSTRAINT, warning, "public.users.users_email_key"),
        (DriftType.EXTRA_CONSTRAINT, info, "public.users.users_id_positive"),
    ]
    assert (report.tables_checked, report.columns_checked, report.indexes_checked) == (1, 3, 2)


def test_identical_models_report_nothing() -> None:
    assert _compare(_users(EMAIL_UQ), _users(EMAIL_UQ)).drift_items == []


# ---------------------------------------------------------------------------
# One fact apart
# ---------------------------------------------------------------------------


def test_a_constraint_the_database_lost_is_missing() -> None:
    report = _compare(_users(POSITIVE), _users())

    (item,) = report.drift_items
    assert (item.drift_type, item.severity) == (DriftType.MISSING_CONSTRAINT, DriftSeverity.WARNING)
    assert item.object_name == "public.users.users_id_positive"
    assert (item.expected, item.actual) == ("users_id_positive", None)


def test_a_constraint_the_tree_never_declared_is_extra() -> None:
    report = _compare(_users(), _users(POSITIVE))

    (item,) = report.drift_items
    assert (item.drift_type, item.severity) == (DriftType.EXTRA_CONSTRAINT, DriftSeverity.INFO)
    assert item.object_name == "public.users.users_id_positive"


def test_a_default_the_database_changed_is_a_mismatch() -> None:
    report = _compare(_users(), _users(default="'inactive'::text"))

    (item,) = report.drift_items
    assert (item.drift_type, item.severity) == (DriftType.DEFAULT_MISMATCH, DriftSeverity.WARNING)
    assert item.object_name == "public.users.status"
    assert (item.expected, item.actual) == ("'active'", "'inactive'::text")


def test_a_default_the_database_dropped_is_a_mismatch() -> None:
    (item,) = _compare(_users(), _users(default=None)).drift_items
    assert item.drift_type == DriftType.DEFAULT_MISMATCH


# ---------------------------------------------------------------------------
# Two spellings of one fact
# ---------------------------------------------------------------------------


def test_a_literal_and_the_cast_postgres_stores_it_with_are_one_default() -> None:
    assert _compare(_users(default="'x'"), _users(default="'x'::text")).drift_items == []


def test_an_unnamed_foreign_key_matches_the_name_postgres_gave_it() -> None:
    """``REFERENCES parent`` names no constraint and no column; the catalog names both."""
    written = Constraint(kind="foreign_key", columns=("pid",), ref_table="parent")
    stored = Constraint(
        kind="foreign_key",
        name="child_pid_fkey",
        columns=("pid",),
        ref_table="public.parent",
        ref_columns=("id",),
    )
    expected = model(table("child", column("pid"), constraints=[written]))
    actual = model(table("child", column("pid"), constraints=[stored]))

    assert _compare(expected, actual).drift_items == []


def test_two_unnamed_foreign_keys_are_two() -> None:
    """1.14.0's rule: an unnamed constraint is identified by what it says, never by ``""``."""
    to_a = Constraint(kind="foreign_key", columns=("a_id",), ref_table="a")
    to_b = Constraint(kind="foreign_key", columns=("b_id",), ref_table="b")
    live_a = Constraint(kind="foreign_key", name="t_a_id_fkey", columns=("a_id",), ref_table="a")
    columns = (column("a_id"), column("b_id"))
    expected = model(table("t", *columns, constraints=[to_a, to_b]))
    actual = model(table("t", *columns, constraints=[live_a]))

    assert _items(_compare(expected, actual)) == [
        (DriftType.MISSING_CONSTRAINT, DriftSeverity.WARNING, "public.t.FOREIGN KEY (b_id)")
    ]


def test_an_unnamed_index_matches_by_what_it_indexes() -> None:
    written = index(None, "t", "code", method="btree")
    stored = index("t_code_idx", "t", "code", method="btree")
    expected = model(table("t", column("code", "text"), indexes=[written]))
    actual = model(table("t", column("code", "text"), indexes=[stored]))

    assert _compare(expected, actual).drift_items == []


class TestExclusionConstraints:
    """#322: drift sees an EXCLUDE constraint, named or not."""

    NAMED = Constraint(
        kind="exclusion", name="no_overlap", columns=("id",), operators=("&&",), method="gist"
    )
    UNNAMED = Constraint(kind="exclusion", columns=("id",), operators=("&&",), method="gist")

    def test_one_the_database_lost_is_missing(self) -> None:
        assert _items(_compare(_users(self.NAMED), _users())) == [
            (DriftType.MISSING_CONSTRAINT, DriftSeverity.WARNING, "public.users.no_overlap")
        ]

    def test_an_unnamed_one_matches_the_name_postgresql_gave_it(self) -> None:
        stored = Constraint(
            kind="exclusion",
            name="users_id_excl",
            columns=("id",),
            operators=("&&",),
            method="gist",
        )
        assert _compare(_users(self.UNNAMED), _users(stored)).drift_items == []

    def test_an_unnamed_one_with_another_operator_is_another_constraint(self) -> None:
        other = Constraint(kind="exclusion", name="x", columns=("id",), operators=("=",))
        assert [
            i.drift_type for i in _compare(_users(self.UNNAMED), _users(other)).drift_items
        ] == [
            DriftType.MISSING_CONSTRAINT,
            DriftType.EXTRA_CONSTRAINT,
        ]

    def test_an_unnamed_missing_one_is_labelled_by_what_it_says(self) -> None:
        (item,) = _compare(_users(self.UNNAMED), _users()).drift_items
        assert "EXCLUDE (id)" in item.message
