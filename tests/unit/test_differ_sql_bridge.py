"""Gap F — DifferSQLGenerator bridge methods (ADD/DROP FK, CHECK, UNIQUE)."""

import pytest

from confiture.core.differ_sql import DifferSQLGenerator
from confiture.exceptions import UnsafeOperationError
from confiture.models.schema import SchemaChange


class TestDifferSQLBridgeMethods:
    def _gen(self) -> DifferSQLGenerator:
        return DifferSQLGenerator()

    def _gen_force(self) -> DifferSQLGenerator:
        return DifferSQLGenerator(force_destructive=True)

    # --- ADD_FOREIGN_KEY ---

    def test_up_add_foreign_key(self):
        change = SchemaChange(
            type="ADD_FOREIGN_KEY",
            table="orders",
            details={
                "name": "fk_u",
                "columns": ["user_id"],
                "ref_table": "users",
                "ref_columns": ["id"],
                "on_delete": None,
            },
        )
        sql = self._gen().generate_up(change)
        assert "FOREIGN KEY" in sql
        assert "fk_u" in sql
        assert "orders" in sql
        assert "users" in sql

    def test_up_add_foreign_key_with_on_delete(self):
        change = SchemaChange(
            type="ADD_FOREIGN_KEY",
            table="orders",
            details={
                "name": "fk_u",
                "columns": ["user_id"],
                "ref_table": "users",
                "ref_columns": ["id"],
                "on_delete": "CASCADE",
            },
        )
        sql = self._gen().generate_up(change)
        assert "FOREIGN KEY" in sql

    # --- DROP_FOREIGN_KEY ---

    def test_up_drop_foreign_key(self):
        change = SchemaChange(
            type="DROP_FOREIGN_KEY",
            table="orders",
            details={"name": "fk_u"},
        )
        sql = self._gen().generate_up(change)
        assert "DROP CONSTRAINT" in sql
        assert "fk_u" in sql

    # --- ADD_CHECK_CONSTRAINT ---

    def test_up_add_check_constraint(self):
        change = SchemaChange(
            type="ADD_CHECK_CONSTRAINT",
            table="orders",
            details={"name": "chk_pos", "expression": "amount > 0"},
        )
        sql = self._gen().generate_up(change)
        assert "ADD CONSTRAINT" in sql
        assert "chk_pos" in sql
        assert "amount > 0" in sql

    def test_up_add_check_constraint_no_details(self):
        """A change with no constraint name is a warning, not an invented name.

        This asserted a substring of what the fabricated fallback produced —
        ``ALTER TABLE orders ADD CONSTRAINT chk_orders CHECK () ()``, which
        PostgreSQL does not parse. A name confiture makes up is
        indistinguishable from one the author chose, and with a qualified table
        it is not even a legal identifier (``chk_tenant.t``).
        """
        change = SchemaChange(type="ADD_CHECK_CONSTRAINT", table="orders")
        sql = self._gen().generate_up(change)
        assert sql.startswith("-- WARNING:")
        assert "chk_orders" not in sql

    # --- DROP_CHECK_CONSTRAINT ---

    def test_up_drop_check_constraint(self):
        change = SchemaChange(
            type="DROP_CHECK_CONSTRAINT",
            table="orders",
            details={"name": "chk_pos"},
        )
        sql = self._gen().generate_up(change)
        assert "DROP CONSTRAINT" in sql
        assert "chk_pos" in sql

    # --- ADD_UNIQUE_CONSTRAINT ---

    def test_up_add_unique_constraint(self):
        change = SchemaChange(
            type="ADD_UNIQUE_CONSTRAINT",
            table="users",
            details={"name": "uq_email", "columns": ["email"]},
        )
        sql = self._gen().generate_up(change)
        assert "ADD CONSTRAINT" in sql
        assert "uq_email" in sql
        assert "UNIQUE" in sql

    # --- DROP_UNIQUE_CONSTRAINT ---

    def test_up_drop_unique_constraint(self):
        change = SchemaChange(
            type="DROP_UNIQUE_CONSTRAINT",
            table="users",
            details={"name": "uq_email"},
        )
        sql = self._gen().generate_up(change)
        assert "DROP CONSTRAINT" in sql
        assert "uq_email" in sql

    # --- Safety: unknown type raises ---

    def test_generate_up_unknown_type_raises(self):
        change = SchemaChange(type="UNSUPPORTED_CHANGE", table="t")
        with pytest.raises(NotImplementedError):
            self._gen().generate_up(change)

    # --- Safety: drop_table without force raises ---

    def test_up_drop_table_without_force_raises(self):
        change = SchemaChange(type="DROP_TABLE", table="t")
        with pytest.raises(UnsafeOperationError):
            self._gen().generate_up(change)

    def test_up_drop_table_with_force_generates_sql(self):
        change = SchemaChange(type="DROP_TABLE", table="t")
        sql = self._gen_force().generate_up(change)
        assert "DROP TABLE" in sql
