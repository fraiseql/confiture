"""MigrationGenerator: delegate 13 new change types via DifferSQLGenerator."""

from __future__ import annotations

from confiture.core.migration_generator import MigrationGenerator
from confiture.core.schema_change import (
    CheckConstraintAdded,
    CheckConstraintDropped,
    EnumTypeAdded,
    EnumTypeDropped,
    EnumValuesChanged,
    ForeignKeyAdded,
    ForeignKeyDropped,
    IndexAdded,
    IndexDropped,
    SchemaDiff,
    SequenceAdded,
    SequenceDropped,
    UniqueConstraintAdded,
    UniqueConstraintDropped,
)
from confiture.core.schema_model import Constraint, EnumType, Sequence
from tests.unit._schema_models import index


def _gen(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    return MigrationGenerator(migrations_dir=d)


FK_ORDERS_USER = Constraint(
    kind="foreign_key",
    name="fk_orders_user",
    columns=("user_id",),
    ref_table="users",
    ref_columns=("id",),
)
CHK_AMOUNT_POSITIVE = Constraint(kind="check", name="chk_amount_positive", expression="amount > 0")
UQ_USERS_EMAIL = Constraint(kind="unique", name="uq_users_email", columns=("email",))
IDX_USERS_EMAIL = index("idx_users_email", "users", "email")


# ---------------------------------------------------------------------------
# Index changes
# ---------------------------------------------------------------------------


class TestIndexChanges:
    def test_up_add_index_generates_create_index(self, tmp_path):
        change = IndexAdded("users", IDX_USERS_EMAIL)
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "CREATE" in sql and "INDEX" in sql
        assert "idx_users_email" in sql

    def test_up_drop_index_generates_drop_index(self, tmp_path):
        change = IndexDropped("users", IDX_USERS_EMAIL)
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "DROP INDEX" in sql

    def test_down_add_index_generates_drop(self, tmp_path):
        change = IndexAdded("users", IDX_USERS_EMAIL)
        sql = _gen(tmp_path)._change_to_down_sql(change)
        assert sql is not None
        assert "DROP" in sql


# ---------------------------------------------------------------------------
# Foreign key changes
# ---------------------------------------------------------------------------


class TestForeignKeyChanges:
    def test_up_add_foreign_key(self, tmp_path):
        change = ForeignKeyAdded("orders", FK_ORDERS_USER)
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "FOREIGN KEY" in sql

    def test_up_drop_foreign_key(self, tmp_path):
        change = ForeignKeyDropped("orders", FK_ORDERS_USER)
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "DROP CONSTRAINT" in sql

    def test_down_add_foreign_key(self, tmp_path):
        change = ForeignKeyAdded("orders", FK_ORDERS_USER)
        sql = _gen(tmp_path)._change_to_down_sql(change)
        assert sql is not None


# ---------------------------------------------------------------------------
# Check constraint changes
# ---------------------------------------------------------------------------


class TestCheckConstraintChanges:
    def test_up_add_check_constraint(self, tmp_path):
        change = CheckConstraintAdded("orders", CHK_AMOUNT_POSITIVE)
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "CHECK" in sql

    def test_up_drop_check_constraint(self, tmp_path):
        change = CheckConstraintDropped("orders", CHK_AMOUNT_POSITIVE)
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "DROP CONSTRAINT" in sql


# ---------------------------------------------------------------------------
# Unique constraint changes
# ---------------------------------------------------------------------------


class TestUniqueConstraintChanges:
    def test_up_add_unique_constraint(self, tmp_path):
        change = UniqueConstraintAdded("users", UQ_USERS_EMAIL)
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "UNIQUE" in sql

    def test_up_drop_unique_constraint(self, tmp_path):
        change = UniqueConstraintDropped("users", UQ_USERS_EMAIL)
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "DROP CONSTRAINT" in sql


# ---------------------------------------------------------------------------
# Enum type changes
# ---------------------------------------------------------------------------


class TestEnumTypeChanges:
    def test_up_add_enum_type(self, tmp_path):
        change = EnumTypeAdded(EnumType("mood", values=("happy", "sad")))
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "CREATE TYPE" in sql
        assert "mood" in sql

    def test_up_drop_enum_type_is_the_drop(self, tmp_path):
        """The destructive gate decides whether it ships, as for a table (#335)."""
        change = EnumTypeDropped(EnumType("mood", values=("happy", "sad")))
        assert _gen(tmp_path)._change_to_up_sql(change) == "DROP TYPE IF EXISTS mood;"

    def test_up_change_enum_values(self, tmp_path):
        change = EnumValuesChanged("mood", added=("ecstatic",), removed=())
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "ADD VALUE" in sql

    def test_down_add_enum_type(self, tmp_path):
        change = EnumTypeAdded(EnumType("mood", values=("happy",)))
        sql = _gen(tmp_path)._change_to_down_sql(change)
        assert sql is not None
        assert "DROP TYPE" in sql


# ---------------------------------------------------------------------------
# Sequence changes
# ---------------------------------------------------------------------------


class TestSequenceChanges:
    def test_up_add_sequence(self, tmp_path):
        change = SequenceAdded(Sequence("order_seq"))
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "CREATE SEQUENCE" in sql
        assert "order_seq" in sql

    def test_up_drop_sequence_is_the_drop(self, tmp_path):
        """The destructive gate decides whether it ships, as for a table (#335)."""
        change = SequenceDropped(Sequence("order_seq"))
        assert _gen(tmp_path)._change_to_up_sql(change) == "DROP SEQUENCE IF EXISTS order_seq;"

    def test_down_add_sequence(self, tmp_path):
        change = SequenceAdded(Sequence("order_seq"))
        sql = _gen(tmp_path)._change_to_down_sql(change)
        assert sql is not None
        assert "DROP SEQUENCE" in sql


# ---------------------------------------------------------------------------
# Full migration file integration: new types appear in generated file
# ---------------------------------------------------------------------------


class TestGeneratedFileContainsNewTypes:
    def test_migration_file_includes_add_index_sql(self, tmp_path):
        diff = SchemaDiff(changes=[IndexAdded("users", index("idx_email", "users", "email"))])
        gen = _gen(tmp_path)
        path = gen.generate(diff, name="add_idx_email")
        content = path.read_text()
        assert "idx_email" in content

    def test_migration_file_includes_add_enum_sql(self, tmp_path):
        diff = SchemaDiff(changes=[EnumTypeAdded(EnumType("mood", values=("happy", "sad")))])
        gen = _gen(tmp_path)
        path = gen.generate(diff, name="add_mood_enum")
        content = path.read_text()
        assert "mood" in content
        assert "CREATE TYPE" in content
