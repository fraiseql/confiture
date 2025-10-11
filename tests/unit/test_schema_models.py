"""Tests for schema data models."""

from confiture.models.schema import (
    Column,
    ColumnType,
    Schema,
    SchemaChange,
    SchemaDiff,
    Table,
)


class TestColumn:
    """Tests for Column model."""

    def test_column_creation(self):
        """Test basic column creation."""
        col = Column(name="id", type=ColumnType.INTEGER, primary_key=True)
        assert col.name == "id"
        assert col.type == ColumnType.INTEGER
        assert col.primary_key is True
        assert col.nullable is True  # Default

    def test_column_equality_same(self):
        """Test column equality with identical columns."""
        col1 = Column(
            name="email",
            type=ColumnType.VARCHAR,
            length=255,
            nullable=False,
            unique=True,
        )
        col2 = Column(
            name="email",
            type=ColumnType.VARCHAR,
            length=255,
            nullable=False,
            unique=True,
        )
        assert col1 == col2

    def test_column_equality_different_name(self):
        """Test column inequality with different names."""
        col1 = Column(name="email", type=ColumnType.VARCHAR)
        col2 = Column(name="username", type=ColumnType.VARCHAR)
        assert col1 != col2

    def test_column_equality_different_type(self):
        """Test column inequality with different types."""
        col1 = Column(name="age", type=ColumnType.INTEGER)
        col2 = Column(name="age", type=ColumnType.BIGINT)
        assert col1 != col2

    def test_column_equality_not_column(self):
        """Test column equality with non-Column object."""
        col = Column(name="id", type=ColumnType.INTEGER)
        assert col != "not a column"
        assert col != 123
        assert col is not None

    def test_column_hash(self):
        """Test column hashing for use in sets."""
        col1 = Column(name="id", type=ColumnType.INTEGER, primary_key=True)
        col2 = Column(name="id", type=ColumnType.INTEGER, primary_key=True)
        col3 = Column(name="email", type=ColumnType.VARCHAR)

        # Same columns should have same hash
        assert hash(col1) == hash(col2)

        # Can be used in sets
        col_set = {col1, col2, col3}
        assert len(col_set) == 2  # col1 and col2 are duplicates

    def test_column_with_default(self):
        """Test column with default value."""
        col = Column(
            name="created_at",
            type=ColumnType.TIMESTAMP,
            default="NOW()",
            nullable=False,
        )
        assert col.default == "NOW()"
        assert col.nullable is False


class TestTable:
    """Tests for Table model."""

    def test_table_creation(self):
        """Test basic table creation."""
        table = Table(name="users")
        assert table.name == "users"
        assert table.columns == []
        assert table.indexes == []
        assert table.constraints == []

    def test_table_with_columns(self):
        """Test table with columns."""
        columns = [
            Column(name="id", type=ColumnType.INTEGER, primary_key=True),
            Column(name="email", type=ColumnType.VARCHAR, length=255),
        ]
        table = Table(name="users", columns=columns)
        assert len(table.columns) == 2
        assert table.columns[0].name == "id"

    def test_get_column_exists(self):
        """Test getting existing column."""
        columns = [
            Column(name="id", type=ColumnType.INTEGER),
            Column(name="email", type=ColumnType.VARCHAR),
        ]
        table = Table(name="users", columns=columns)

        email_col = table.get_column("email")
        assert email_col is not None
        assert email_col.name == "email"
        assert email_col.type == ColumnType.VARCHAR

    def test_get_column_not_exists(self):
        """Test getting non-existent column."""
        table = Table(name="users", columns=[])
        col = table.get_column("nonexistent")
        assert col is None

    def test_has_column_exists(self):
        """Test checking if column exists."""
        columns = [Column(name="id", type=ColumnType.INTEGER)]
        table = Table(name="users", columns=columns)
        assert table.has_column("id") is True

    def test_has_column_not_exists(self):
        """Test checking if column doesn't exist."""
        table = Table(name="users", columns=[])
        assert table.has_column("nonexistent") is False

    def test_table_equality_same(self):
        """Test table equality with identical tables."""
        columns = [Column(name="id", type=ColumnType.INTEGER)]
        table1 = Table(name="users", columns=columns)
        table2 = Table(name="users", columns=columns)
        assert table1 == table2

    def test_table_equality_different_name(self):
        """Test table inequality with different names."""
        table1 = Table(name="users")
        table2 = Table(name="posts")
        assert table1 != table2

    def test_table_equality_different_columns(self):
        """Test table inequality with different columns."""
        table1 = Table(name="users", columns=[Column(name="id", type=ColumnType.INTEGER)])
        table2 = Table(name="users", columns=[Column(name="email", type=ColumnType.VARCHAR)])
        assert table1 != table2

    def test_table_equality_not_table(self):
        """Test table equality with non-Table object."""
        table = Table(name="users")
        assert table != "not a table"
        assert table != 123
        assert table is not None


class TestSchema:
    """Tests for Schema model."""

    def test_schema_creation(self):
        """Test basic schema creation."""
        schema = Schema()
        assert schema.tables == []

    def test_schema_with_tables(self):
        """Test schema with tables."""
        tables = [Table(name="users"), Table(name="posts")]
        schema = Schema(tables=tables)
        assert len(schema.tables) == 2
        assert schema.tables[0].name == "users"

    def test_get_table_exists(self):
        """Test getting existing table."""
        tables = [Table(name="users"), Table(name="posts")]
        schema = Schema(tables=tables)

        users_table = schema.get_table("users")
        assert users_table is not None
        assert users_table.name == "users"

    def test_get_table_not_exists(self):
        """Test getting non-existent table."""
        schema = Schema(tables=[])
        table = schema.get_table("nonexistent")
        assert table is None

    def test_has_table_exists(self):
        """Test checking if table exists."""
        tables = [Table(name="users")]
        schema = Schema(tables=tables)
        assert schema.has_table("users") is True

    def test_has_table_not_exists(self):
        """Test checking if table doesn't exist."""
        schema = Schema(tables=[])
        assert schema.has_table("nonexistent") is False

    def test_table_names(self):
        """Test getting all table names."""
        tables = [Table(name="users"), Table(name="posts"), Table(name="comments")]
        schema = Schema(tables=tables)

        names = schema.table_names()
        assert names == ["users", "posts", "comments"]

    def test_table_names_empty(self):
        """Test getting table names from empty schema."""
        schema = Schema()
        names = schema.table_names()
        assert names == []


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


class TestSchemaDiff:
    """Tests for SchemaDiff model."""

    def test_schema_diff_creation(self):
        """Test basic schema diff creation."""
        diff = SchemaDiff()
        assert diff.changes == []

    def test_schema_diff_with_changes(self):
        """Test schema diff with changes."""
        changes = [
            SchemaChange(type="ADD_TABLE", table="users"),
            SchemaChange(type="ADD_COLUMN", table="posts", column="title"),
        ]
        diff = SchemaDiff(changes=changes)
        assert len(diff.changes) == 2

    def test_has_changes_true(self):
        """Test has_changes when there are changes."""
        changes = [SchemaChange(type="ADD_TABLE", table="users")]
        diff = SchemaDiff(changes=changes)
        assert diff.has_changes() is True

    def test_has_changes_false(self):
        """Test has_changes when there are no changes."""
        diff = SchemaDiff()
        assert diff.has_changes() is False

    def test_count_by_type(self):
        """Test counting changes by type."""
        changes = [
            SchemaChange(type="ADD_TABLE", table="users"),
            SchemaChange(type="ADD_TABLE", table="posts"),
            SchemaChange(type="ADD_COLUMN", table="users", column="email"),
            SchemaChange(type="DROP_TABLE", table="old_table"),
        ]
        diff = SchemaDiff(changes=changes)

        assert diff.count_by_type("ADD_TABLE") == 2
        assert diff.count_by_type("ADD_COLUMN") == 1
        assert diff.count_by_type("DROP_TABLE") == 1
        assert diff.count_by_type("NONEXISTENT") == 0

    def test_str_no_changes(self):
        """Test string representation with no changes."""
        diff = SchemaDiff()
        assert str(diff) == "No changes detected"

    def test_str_with_changes(self):
        """Test string representation with changes."""
        changes = [
            SchemaChange(type="ADD_TABLE", table="users"),
            SchemaChange(type="ADD_COLUMN", table="users", column="email"),
        ]
        diff = SchemaDiff(changes=changes)

        result = str(diff)
        assert "ADD TABLE users" in result
        assert "ADD COLUMN users.email" in result
        assert "\n" in result  # Changes separated by newlines
