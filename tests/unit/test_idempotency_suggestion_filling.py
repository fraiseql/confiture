"""Tests for template-filled idempotency suggestions (Phase 04 Cycle 3).

For each :data:`TEMPLATE_FILLABLE` pattern, the suggestion machinery
takes a :class:`Captures` instance and produces a copy-pasteable SQL
template with the captured identifiers inlined.

Patterns in :data:`TEMPLATE_NOT_AVAILABLE` keep the generic suggestion
and explicitly say "no auto-template available — manual fix required".
"""

from __future__ import annotations

import pytest

from confiture.core.idempotency._captures import Captures
from confiture.core.idempotency.models import IdempotencyPattern
from confiture.core.idempotency.suggestion_templates import (
    NO_TEMPLATE_AVAILABLE_MARKER,
    suggestion_for,
)


class TestTemplateFillableHappyPath:
    """Filled templates contain the captured identifiers verbatim."""

    def test_create_table_qualified(self) -> None:
        cap = Captures(schema="tenant", table="orders")
        sug = suggestion_for(IdempotencyPattern.CREATE_TABLE, cap)
        assert "tenant.orders" in sug
        assert "IF NOT EXISTS" in sug

    def test_create_table_unqualified(self) -> None:
        cap = Captures(table="orders")
        sug = suggestion_for(IdempotencyPattern.CREATE_TABLE, cap)
        assert "orders" in sug
        assert "IF NOT EXISTS" in sug
        assert "tenant" not in sug

    def test_create_index(self) -> None:
        cap = Captures(index_name="idx_orders_user_id", schema="tenant", table="orders")
        sug = suggestion_for(IdempotencyPattern.CREATE_INDEX, cap)
        assert "idx_orders_user_id" in sug
        assert "tenant.orders" in sug
        assert "IF NOT EXISTS" in sug

    def test_create_unique_index(self) -> None:
        cap = Captures(index_name="uq_orders_email", schema="tenant", table="orders")
        sug = suggestion_for(IdempotencyPattern.CREATE_UNIQUE_INDEX, cap)
        assert "uq_orders_email" in sug
        assert "tenant.orders" in sug
        assert "UNIQUE" in sug

    def test_alter_table_add_column(self) -> None:
        cap = Captures(schema="tenant", table="orders", column="amount")
        sug = suggestion_for(IdempotencyPattern.ALTER_TABLE_ADD_COLUMN, cap)
        assert "tenant.orders" in sug
        assert "amount" in sug
        assert "IF NOT EXISTS" in sug

    def test_alter_table_add_constraint_check(self) -> None:
        cap = Captures(
            schema="tenant", table="orders", constraint="chk_orders_amount_positive"
        )
        sug = suggestion_for(IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK, cap)
        assert "tenant.orders" in sug
        assert "chk_orders_amount_positive" in sug
        assert "DROP CONSTRAINT IF EXISTS" in sug

    def test_alter_table_add_constraint_primary_key(self) -> None:
        cap = Captures(schema="tenant", table="orders", constraint="pk_orders")
        sug = suggestion_for(
            IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_PRIMARY_KEY, cap
        )
        assert "tenant.orders" in sug
        assert "pk_orders" in sug
        assert "DROP CONSTRAINT IF EXISTS" in sug

    def test_alter_table_add_constraint_unique(self) -> None:
        cap = Captures(schema="tenant", table="orders", constraint="uq_orders_email")
        sug = suggestion_for(IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_UNIQUE, cap)
        assert "tenant.orders" in sug
        assert "uq_orders_email" in sug
        assert "DROP CONSTRAINT IF EXISTS" in sug

    def test_alter_table_rename_column(self) -> None:
        cap = Captures(schema="tenant", table="orders", column="amt", new_column="amount")
        sug = suggestion_for(IdempotencyPattern.ALTER_TABLE_RENAME_COLUMN, cap)
        assert "tenant.orders" in sug
        assert "amt" in sug
        assert "amount" in sug
        assert "information_schema" in sug

    def test_create_type_enum(self) -> None:
        cap = Captures(schema="tenant", type_name="order_status")
        sug = suggestion_for(IdempotencyPattern.CREATE_TYPE, cap)
        assert "tenant.order_status" in sug
        assert "pg_type" in sug

    def test_create_schema(self) -> None:
        cap = Captures(schema="tenant")
        sug = suggestion_for(IdempotencyPattern.CREATE_SCHEMA, cap)
        assert "tenant" in sug
        assert "IF NOT EXISTS" in sug

    def test_create_sequence(self) -> None:
        cap = Captures(schema="tenant", sequence="orders_seq")
        sug = suggestion_for(IdempotencyPattern.CREATE_SEQUENCE, cap)
        assert "tenant.orders_seq" in sug
        assert "IF NOT EXISTS" in sug

    def test_create_extension(self) -> None:
        cap = Captures(extension="pgcrypto")
        sug = suggestion_for(IdempotencyPattern.CREATE_EXTENSION, cap)
        assert "pgcrypto" in sug
        assert "IF NOT EXISTS" in sug

    def test_create_view(self) -> None:
        cap = Captures(schema="tenant", view="v_orders_summary")
        sug = suggestion_for(IdempotencyPattern.CREATE_VIEW, cap)
        assert "tenant.v_orders_summary" in sug
        assert "DROP VIEW IF EXISTS" in sug

    def test_create_or_replace_view_shape_risk(self) -> None:
        cap = Captures(schema="tenant", view="v_orders_summary")
        sug = suggestion_for(IdempotencyPattern.CREATE_OR_REPLACE_VIEW_SHAPE_RISK, cap)
        assert "tenant.v_orders_summary" in sug
        assert "DROP VIEW IF EXISTS" in sug

    def test_alter_table_owner(self) -> None:
        cap = Captures(schema="tenant", table="orders")
        sug = suggestion_for(IdempotencyPattern.ALTER_TABLE_OWNER, cap)
        assert "tenant.orders" in sug
        assert "pg_class" in sug

    def test_alter_view_owner(self) -> None:
        cap = Captures(schema="tenant", view="v_orders")
        sug = suggestion_for(IdempotencyPattern.ALTER_VIEW_OWNER, cap)
        assert "tenant.v_orders" in sug
        assert "pg_class" in sug

    def test_alter_matview_owner(self) -> None:
        cap = Captures(schema="tenant", view="mv_orders")
        sug = suggestion_for(IdempotencyPattern.ALTER_MATVIEW_OWNER, cap)
        assert "tenant.mv_orders" in sug
        assert "pg_matviews" in sug

    @pytest.mark.parametrize(
        ("pattern", "captures_kwargs"),
        [
            (IdempotencyPattern.DROP_TABLE, {"schema": "tenant", "table": "orders"}),
            (IdempotencyPattern.DROP_INDEX, {"schema": "tenant", "table": "idx_orders"}),
            (IdempotencyPattern.DROP_VIEW, {"schema": "tenant", "table": "v_orders"}),
            (IdempotencyPattern.DROP_TYPE, {"schema": "tenant", "table": "order_status"}),
            (IdempotencyPattern.DROP_SCHEMA, {"table": "tenant"}),
            (IdempotencyPattern.DROP_SEQUENCE, {"schema": "tenant", "table": "orders_seq"}),
        ],
    )
    def test_drop_with_if_exists(
        self, pattern: IdempotencyPattern, captures_kwargs: dict[str, str]
    ) -> None:
        cap = Captures(**captures_kwargs)
        sug = suggestion_for(pattern, cap)
        assert "IF EXISTS" in sug
        name_token = captures_kwargs.get("table")
        assert name_token is not None
        assert name_token in sug


class TestTemplateFillableFallback:
    """When required captures are missing, the template falls back gracefully."""

    def test_create_table_missing_name_falls_back(self) -> None:
        cap = Captures()  # no table name
        sug = suggestion_for(IdempotencyPattern.CREATE_TABLE, cap)
        # Falls back to the generic IdempotencyPattern.suggestion text.
        assert "IF NOT EXISTS" in sug
        # No bare placeholder tokens left behind.
        assert "<table>" not in sug

    def test_alter_add_constraint_missing_constraint_falls_back(self) -> None:
        cap = Captures(schema="tenant", table="orders")  # no constraint name
        sug = suggestion_for(IdempotencyPattern.ALTER_TABLE_ADD_CONSTRAINT_CHECK, cap)
        # Falls back to the generic suggestion (still mentions the strategy).
        assert "DROP CONSTRAINT" in sug


class TestTemplateNotAvailable:
    """``TEMPLATE_NOT_AVAILABLE`` patterns emit the explicit marker."""

    @pytest.mark.parametrize(
        "pattern",
        [
            IdempotencyPattern.CREATE_FUNCTION,
            IdempotencyPattern.CREATE_PROCEDURE,
            IdempotencyPattern.DROP_FUNCTION,
            IdempotencyPattern.CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK,
            IdempotencyPattern.CREATE_OR_REPLACE_PROCEDURE_SHAPE_RISK,
        ],
    )
    def test_emits_no_template_marker(self, pattern: IdempotencyPattern) -> None:
        cap = Captures()
        sug = suggestion_for(pattern, cap)
        assert NO_TEMPLATE_AVAILABLE_MARKER in sug
