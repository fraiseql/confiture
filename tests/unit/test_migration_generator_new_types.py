"""Phase 02 Cycle 2 — MigrationGenerator: delegate 13 new change types via DifferSQLGenerator."""

from __future__ import annotations

from confiture.core.migration_generator import MigrationGenerator
from confiture.models.schema import SchemaChange, SchemaDiff


def _gen(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    return MigrationGenerator(migrations_dir=d)


# ---------------------------------------------------------------------------
# Index changes
# ---------------------------------------------------------------------------


class TestIndexChanges:
    def test_up_add_index_generates_create_index(self, tmp_path):
        change = SchemaChange(
            type="ADD_INDEX",
            table="users",
            details={"name": "idx_users_email", "columns": ["email"]},
        )
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "CREATE" in sql and "INDEX" in sql
        assert "idx_users_email" in sql

    def test_up_drop_index_generates_drop_index(self, tmp_path):
        change = SchemaChange(
            type="DROP_INDEX",
            table="users",
            details={"name": "idx_users_email"},
        )
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "DROP INDEX" in sql

    def test_down_add_index_generates_drop(self, tmp_path):
        change = SchemaChange(
            type="ADD_INDEX",
            table="users",
            details={"name": "idx_users_email", "columns": ["email"]},
        )
        sql = _gen(tmp_path)._change_to_down_sql(change)
        assert sql is not None
        assert "DROP" in sql


# ---------------------------------------------------------------------------
# Foreign key changes
# ---------------------------------------------------------------------------


class TestForeignKeyChanges:
    def test_up_add_foreign_key(self, tmp_path):
        change = SchemaChange(
            type="ADD_FOREIGN_KEY",
            table="orders",
            details={
                "name": "fk_orders_user",
                "columns": ["user_id"],
                "ref_table": "users",
                "ref_columns": ["id"],
                "on_delete": None,
            },
        )
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "FOREIGN KEY" in sql

    def test_up_drop_foreign_key(self, tmp_path):
        change = SchemaChange(
            type="DROP_FOREIGN_KEY",
            table="orders",
            details={"name": "fk_orders_user"},
        )
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "DROP CONSTRAINT" in sql

    def test_down_add_foreign_key(self, tmp_path):
        change = SchemaChange(
            type="ADD_FOREIGN_KEY",
            table="orders",
            details={
                "name": "fk_orders_user",
                "columns": ["user_id"],
                "ref_table": "users",
                "ref_columns": ["id"],
                "on_delete": None,
            },
        )
        sql = _gen(tmp_path)._change_to_down_sql(change)
        assert sql is not None


# ---------------------------------------------------------------------------
# Check constraint changes
# ---------------------------------------------------------------------------


class TestCheckConstraintChanges:
    def test_up_add_check_constraint(self, tmp_path):
        change = SchemaChange(
            type="ADD_CHECK_CONSTRAINT",
            table="orders",
            details={"name": "chk_amount_positive", "expression": "amount > 0"},
        )
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "CHECK" in sql

    def test_up_drop_check_constraint(self, tmp_path):
        change = SchemaChange(
            type="DROP_CHECK_CONSTRAINT",
            table="orders",
            details={"name": "chk_amount_positive"},
        )
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "DROP CONSTRAINT" in sql


# ---------------------------------------------------------------------------
# Unique constraint changes
# ---------------------------------------------------------------------------


class TestUniqueConstraintChanges:
    def test_up_add_unique_constraint(self, tmp_path):
        change = SchemaChange(
            type="ADD_UNIQUE_CONSTRAINT",
            table="users",
            details={"name": "uq_users_email", "columns": ["email"]},
        )
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "UNIQUE" in sql

    def test_up_drop_unique_constraint(self, tmp_path):
        change = SchemaChange(
            type="DROP_UNIQUE_CONSTRAINT",
            table="users",
            details={"name": "uq_users_email"},
        )
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "DROP CONSTRAINT" in sql


# ---------------------------------------------------------------------------
# Enum type changes
# ---------------------------------------------------------------------------


class TestEnumTypeChanges:
    def test_up_add_enum_type(self, tmp_path):
        change = SchemaChange(
            type="ADD_ENUM_TYPE",
            table="mood",
            details={"values": ["happy", "sad"]},
        )
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "CREATE TYPE" in sql
        assert "mood" in sql

    def test_up_drop_enum_type_produces_warning_comment(self, tmp_path):
        """MigrationGenerator has no --force; DROP_ENUM_TYPE must emit a warning comment."""
        change = SchemaChange(type="DROP_ENUM_TYPE", table="mood")
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "WARNING" in sql.upper() or "--" in sql

    def test_up_change_enum_values(self, tmp_path):
        change = SchemaChange(
            type="CHANGE_ENUM_VALUES",
            table="mood",
            details={"added_values": ["ecstatic"], "removed_values": []},
        )
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "ADD VALUE" in sql

    def test_down_add_enum_type(self, tmp_path):
        change = SchemaChange(
            type="ADD_ENUM_TYPE",
            table="mood",
            details={"values": ["happy"]},
        )
        sql = _gen(tmp_path)._change_to_down_sql(change)
        assert sql is not None
        assert "DROP TYPE" in sql


# ---------------------------------------------------------------------------
# Sequence changes
# ---------------------------------------------------------------------------


class TestSequenceChanges:
    def test_up_add_sequence(self, tmp_path):
        change = SchemaChange(type="ADD_SEQUENCE", table="order_seq")
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "CREATE SEQUENCE" in sql
        assert "order_seq" in sql

    def test_up_drop_sequence_produces_warning_comment(self, tmp_path):
        """MigrationGenerator has no --force; DROP_SEQUENCE must emit a warning comment."""
        change = SchemaChange(type="DROP_SEQUENCE", table="order_seq")
        sql = _gen(tmp_path)._change_to_up_sql(change)
        assert sql is not None
        assert "WARNING" in sql.upper() or "--" in sql

    def test_down_add_sequence(self, tmp_path):
        change = SchemaChange(type="ADD_SEQUENCE", table="order_seq")
        sql = _gen(tmp_path)._change_to_down_sql(change)
        assert sql is not None
        assert "DROP SEQUENCE" in sql


# ---------------------------------------------------------------------------
# Full migration file integration: new types appear in generated file
# ---------------------------------------------------------------------------


class TestGeneratedFileContainsNewTypes:
    def test_migration_file_includes_add_index_sql(self, tmp_path):
        diff = SchemaDiff(
            changes=[
                SchemaChange(
                    type="ADD_INDEX",
                    table="users",
                    details={"name": "idx_email", "columns": ["email"]},
                )
            ]
        )
        gen = _gen(tmp_path)
        path = gen.generate(diff, name="add_idx_email")
        content = path.read_text()
        assert "idx_email" in content

    def test_migration_file_includes_add_enum_sql(self, tmp_path):
        diff = SchemaDiff(
            changes=[
                SchemaChange(
                    type="ADD_ENUM_TYPE",
                    table="mood",
                    details={"values": ["happy", "sad"]},
                )
            ]
        )
        gen = _gen(tmp_path)
        path = gen.generate(diff, name="add_mood_enum")
        content = path.read_text()
        assert "mood" in content
        assert "CREATE TYPE" in content
