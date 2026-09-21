"""Tests for the change-set models, and for the retired model's names."""

import pytest

from confiture.core.schema_change import (
    ColumnAdded,
    ColumnDefaultChanged,
    ColumnDropped,
    ColumnNullabilityChanged,
    ColumnRenamed,
    ColumnTypeChanged,
    TableAdded,
    TableDropped,
    TableRenamed,
)
from tests.unit._schema_changes import spelled
from tests.unit._schema_models import table


class TestSchemaChange:
    """Tests for the SchemaChange variants and their wire form."""

    def test_schema_change_creation(self):
        """Test basic schema change creation."""
        change = TableAdded(table("users")).to_wire()
        assert change.type == "ADD_TABLE"
        assert change.table == "users"

    def test_str_add_table(self):
        """Test string representation for ADD_TABLE."""
        change = TableAdded(table("users"))
        assert str(change) == "ADD TABLE users"

    def test_str_drop_table(self):
        """Test string representation for DROP_TABLE."""
        change = TableDropped(table("old_users"))
        assert str(change) == "DROP TABLE old_users"

    def test_str_rename_table(self):
        """Test string representation for RENAME_TABLE."""
        change = TableRenamed(table("users"), table("accounts"))
        assert str(change) == "RENAME TABLE users TO accounts"

    def test_str_add_column(self):
        """Test string representation for ADD_COLUMN."""
        change = ColumnAdded("users", spelled("email", "TEXT"))
        assert str(change) == "ADD COLUMN users.email"

    def test_str_drop_column(self):
        """Test string representation for DROP_COLUMN."""
        change = ColumnDropped("users", spelled("old_field", "TEXT"))
        assert str(change) == "DROP COLUMN users.old_field"

    def test_str_rename_column(self):
        """Test string representation for RENAME_COLUMN."""
        change = ColumnRenamed("users", "email", "email_address")
        assert str(change) == "RENAME COLUMN users.email TO email_address"

    def test_str_change_column_type(self):
        """Test string representation for CHANGE_COLUMN_TYPE."""
        change = ColumnTypeChanged("users", spelled("age", "INTEGER"), spelled("age", "BIGINT"))
        assert str(change) == "CHANGE COLUMN TYPE users.age FROM INTEGER TO BIGINT"

    def test_str_change_column_nullable(self):
        """Test string representation for CHANGE_COLUMN_NULLABLE."""
        change = ColumnNullabilityChanged("users", "email", nullable=False)
        assert str(change) == "CHANGE COLUMN NULLABLE users.email FROM true TO false"

    def test_str_change_column_default(self):
        """Test string representation for CHANGE_COLUMN_DEFAULT."""
        change = ColumnDefaultChanged("users", "created_at", None, "now()")
        assert str(change) == "CHANGE COLUMN DEFAULT users.created_at"


class TestTheRetiredModelSaysWhereItWent:
    """``models.schema``'s table model is ``core.schema_model`` now, and its
    change set ``core.schema_change``."""

    @pytest.mark.parametrize(
        "name",
        [
            "Table",
            "Column",
            "ColumnType",
            "Index",
            "ForeignKey",
            "ParsedSchema",
            "SchemaChange",
            "SchemaDiff",
        ],
    )
    def test_importing_a_retired_name_names_its_new_home(self, name: str) -> None:
        from confiture.models import schema

        with pytest.raises(ImportError, match="is retired: use confiture\\.core\\."):
            getattr(schema, name)

    def test_an_unknown_name_is_still_an_attribute_error(self) -> None:
        from confiture.models import schema

        with pytest.raises(AttributeError):
            schema.NoSuchThing  # noqa: B018
