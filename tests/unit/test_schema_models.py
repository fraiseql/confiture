"""Tests for the change-set models, and for the retired model's names."""

import pytest

from confiture.models.schema import SchemaChange


class TestSchemaChange:
    """Tests for SchemaChange model."""

    def test_schema_change_creation(self):
        """Test basic schema change creation."""
        change = SchemaChange(type="ADD_TABLE", table="users")
        assert change.type == "ADD_TABLE"
        assert change.table == "users"

    def test_str_add_table(self):
        """Test string representation for ADD_TABLE."""
        change = SchemaChange(type="ADD_TABLE", table="users")
        assert str(change) == "ADD TABLE users"

    def test_str_drop_table(self):
        """Test string representation for DROP_TABLE."""
        change = SchemaChange(type="DROP_TABLE", table="old_users")
        assert str(change) == "DROP TABLE old_users"

    def test_str_rename_table(self):
        """Test string representation for RENAME_TABLE."""
        change = SchemaChange(
            type="RENAME_TABLE", table="users", old_value="users", new_value="accounts"
        )
        assert str(change) == "RENAME TABLE users TO accounts"

    def test_str_add_column(self):
        """Test string representation for ADD_COLUMN."""
        change = SchemaChange(type="ADD_COLUMN", table="users", column="email")
        assert str(change) == "ADD COLUMN users.email"

    def test_str_drop_column(self):
        """Test string representation for DROP_COLUMN."""
        change = SchemaChange(type="DROP_COLUMN", table="users", column="old_field")
        assert str(change) == "DROP COLUMN users.old_field"

    def test_str_rename_column(self):
        """Test string representation for RENAME_COLUMN."""
        change = SchemaChange(
            type="RENAME_COLUMN",
            table="users",
            column="email",
            old_value="email",
            new_value="email_address",
        )
        assert str(change) == "RENAME COLUMN users.email TO email_address"

    def test_str_change_column_type(self):
        """Test string representation for CHANGE_COLUMN_TYPE."""
        change = SchemaChange(
            type="CHANGE_COLUMN_TYPE",
            table="users",
            column="age",
            old_value="INTEGER",
            new_value="BIGINT",
        )
        assert str(change) == "CHANGE COLUMN TYPE users.age FROM INTEGER TO BIGINT"

    def test_str_change_column_nullable(self):
        """Test string representation for CHANGE_COLUMN_NULLABLE."""
        change = SchemaChange(
            type="CHANGE_COLUMN_NULLABLE",
            table="users",
            column="email",
            old_value="TRUE",
            new_value="FALSE",
        )
        assert str(change) == "CHANGE COLUMN NULLABLE users.email FROM TRUE TO FALSE"

    def test_str_change_column_default(self):
        """Test string representation for CHANGE_COLUMN_DEFAULT."""
        change = SchemaChange(type="CHANGE_COLUMN_DEFAULT", table="users", column="created_at")
        assert str(change) == "CHANGE COLUMN DEFAULT users.created_at"

    def test_str_unknown_type(self):
        """Test string representation for unknown change type."""
        change = SchemaChange(type="UNKNOWN_CHANGE", table="users", column="some_field")
        result = str(change)
        assert "UNKNOWN_CHANGE" in result
        assert "users" in result
        assert "some_field" in result


class TestTheRetiredModelSaysWhereItWent:
    """``models.schema``'s table model is ``core.schema_model`` now."""

    @pytest.mark.parametrize(
        "name",
        ["Table", "Column", "ColumnType", "Index", "ForeignKey", "ParsedSchema"],
    )
    def test_importing_a_retired_name_names_its_new_home(self, name: str) -> None:
        from confiture.models import schema

        with pytest.raises(ImportError, match="is retired: use confiture\\.core\\."):
            getattr(schema, name)

    def test_an_unknown_name_is_still_an_attribute_error(self) -> None:
        from confiture.models import schema

        with pytest.raises(AttributeError):
            schema.NoSuchThing  # noqa: B018
