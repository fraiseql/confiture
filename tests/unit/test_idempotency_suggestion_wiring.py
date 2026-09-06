"""The detector fills every suggestion from the statement it flagged."""

from __future__ import annotations

from confiture.core.idempotency.models import IdempotencyPattern
from confiture.core.idempotency.validator import IdempotencyValidator


def _validate(sql: str) -> str:
    """Return the first violation's suggestion, or fail loudly."""
    report = IdempotencyValidator().validate_sql(sql)
    assert report.violations, f"expected a violation for {sql!r}"
    return report.violations[0].suggestion


class TestFilledSuggestions:
    def test_create_table_qualified(self) -> None:
        sug = _validate("CREATE TABLE tenant.orders (id INT);")
        assert "tenant.orders" in sug
        assert "IF NOT EXISTS" in sug

    def test_create_index(self) -> None:
        sug = _validate("CREATE INDEX idx_orders_user_id ON tenant.orders (user_id);")
        assert "idx_orders_user_id" in sug
        assert "IF NOT EXISTS" in sug

    def test_alter_table_add_constraint_check(self) -> None:
        sug = _validate(
            "ALTER TABLE tenant.orders "
            "ADD CONSTRAINT chk_orders_amount_positive CHECK (amount > 0);"
        )
        assert "tenant.orders" in sug
        assert "chk_orders_amount_positive" in sug
        assert "DROP CONSTRAINT IF EXISTS" in sug

    def test_alter_table_add_column(self) -> None:
        sug = _validate("ALTER TABLE tenant.orders ADD COLUMN amount NUMERIC;")
        assert "tenant.orders" in sug
        assert "amount" in sug
        assert "IF NOT EXISTS" in sug

    def test_alter_rename_column(self) -> None:
        sug = _validate("ALTER TABLE tenant.orders RENAME COLUMN amt TO amount;")
        assert "tenant.orders" in sug
        assert "amt" in sug
        assert "amount" in sug
        assert "information_schema" in sug

    def test_create_type_enum(self) -> None:
        sug = _validate("CREATE TYPE tenant.order_status AS ENUM ('open', 'closed');")
        # Regex regex pattern doesn't catch ``schema.type``; AST does.
        # Both should at least mention the type name.
        assert "order_status" in sug
        assert "pg_type" in sug


class TestFunctionPatternUsesTemplateNotAvailableMarker:
    """``CREATE FUNCTION`` without ``OR REPLACE`` has no template — marker present."""

    def test_create_function_marker(self) -> None:
        sql = "CREATE FUNCTION tenant.f() RETURNS void LANGUAGE sql AS 'SELECT 1';"
        report = IdempotencyValidator().validate_sql(sql)
        # CREATE_FUNCTION should be one of the matches.
        function_violations = [
            v for v in report.violations if v.pattern is IdempotencyPattern.CREATE_FUNCTION
        ]
        assert function_violations, "expected a CREATE_FUNCTION violation"
        assert "no auto-template available" in function_violations[0].suggestion
