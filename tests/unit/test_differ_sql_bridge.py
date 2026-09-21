"""Gap F — DifferSQLGenerator bridge methods (ADD/DROP FK, CHECK, UNIQUE)."""

from dataclasses import replace

import pytest

from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.schema_change import (
    CheckConstraintAdded,
    CheckConstraintDropped,
    ForeignKeyAdded,
    ForeignKeyDropped,
    TableDropped,
    UniqueConstraintAdded,
    UniqueConstraintDropped,
)
from confiture.core.schema_model import Constraint
from confiture.exceptions import UnsafeOperationError
from tests.unit._schema_models import table

FK_U = Constraint(
    kind="foreign_key", name="fk_u", columns=("user_id",), ref_table="users", ref_columns=("id",)
)
CHK_POS = Constraint(kind="check", name="chk_pos", expression="amount > 0")
UQ_EMAIL = Constraint(kind="unique", name="uq_email", columns=("email",))


class TestDifferSQLBridgeMethods:
    def _gen(self) -> DifferSQLGenerator:
        return DifferSQLGenerator()

    def _gen_force(self) -> DifferSQLGenerator:
        return DifferSQLGenerator(force_destructive=True)

    # --- ADD_FOREIGN_KEY ---

    def test_up_add_foreign_key(self):
        change = ForeignKeyAdded("orders", FK_U)
        sql = self._gen().generate_up(change)
        assert "FOREIGN KEY" in sql
        assert "fk_u" in sql
        assert "orders" in sql
        assert "users" in sql

    def test_up_add_foreign_key_with_on_delete(self):
        change = ForeignKeyAdded("orders", replace(FK_U, on_delete="CASCADE"))
        sql = self._gen().generate_up(change)
        assert "FOREIGN KEY" in sql

    # --- DROP_FOREIGN_KEY ---

    def test_up_drop_foreign_key(self):
        change = ForeignKeyDropped("orders", FK_U)
        sql = self._gen().generate_up(change)
        assert "DROP CONSTRAINT" in sql
        assert "fk_u" in sql

    # --- ADD_CHECK_CONSTRAINT ---

    def test_up_add_check_constraint(self):
        change = CheckConstraintAdded("orders", CHK_POS)
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
        change = CheckConstraintAdded("orders", Constraint(kind="check"))
        sql = self._gen().generate_up(change)
        assert sql.startswith("-- WARNING:")
        assert "chk_orders" not in sql

    # --- DROP_CHECK_CONSTRAINT ---

    def test_up_drop_check_constraint(self):
        change = CheckConstraintDropped("orders", CHK_POS)
        sql = self._gen().generate_up(change)
        assert "DROP CONSTRAINT" in sql
        assert "chk_pos" in sql

    # --- ADD_UNIQUE_CONSTRAINT ---

    def test_up_add_unique_constraint(self):
        change = UniqueConstraintAdded("users", UQ_EMAIL)
        sql = self._gen().generate_up(change)
        assert "ADD CONSTRAINT" in sql
        assert "uq_email" in sql
        assert "UNIQUE" in sql

    # --- DROP_UNIQUE_CONSTRAINT ---

    def test_up_drop_unique_constraint(self):
        change = UniqueConstraintDropped("users", UQ_EMAIL)
        sql = self._gen().generate_up(change)
        assert "DROP CONSTRAINT" in sql
        assert "uq_email" in sql

    # --- Safety: drop_table without force raises ---

    def test_up_drop_table_without_force_raises(self):
        change = TableDropped(table("t"))
        with pytest.raises(UnsafeOperationError):
            self._gen().generate_up(change)

    def test_up_drop_table_with_force_generates_sql(self):
        change = TableDropped(table("t"))
        sql = self._gen_force().generate_up(change)
        assert "DROP TABLE" in sql
