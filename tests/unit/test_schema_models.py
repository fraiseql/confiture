"""Tests for schema data models."""

from confiture.models.schema import (
    Column,
    ColumnType,
    EnumType,
    ForeignKey,
    Index,
    ParsedSchema,
    Schema,
    SchemaChange,
    SchemaDiff,
    Sequence,
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
        assert table.foreign_keys == []
        assert table.check_constraints == []
        assert table.unique_constraints == []

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


class TestNewModelTypes:
    """Tests for new DDL object models (Phase 02)."""

    def test_column_type_enum_includes_money(self):
        assert ColumnType.MONEY.value == "MONEY"

    def test_column_type_enum_includes_network_types(self):
        assert ColumnType.CIDR.value == "CIDR"
        assert ColumnType.INET.value == "INET"
        assert ColumnType.MACADDR.value == "MACADDR"

    def test_column_type_enum_includes_range_types(self):
        assert ColumnType.INT4RANGE.value == "INT4RANGE"
        assert ColumnType.TSTZRANGE.value == "TSTZRANGE"

    def test_column_type_enum_includes_text_search(self):
        assert ColumnType.TSVECTOR.value == "TSVECTOR"
        assert ColumnType.TSQUERY.value == "TSQUERY"

    def test_index_model(self):
        idx = Index(name="idx_users_email", table="users", columns=["email"], unique=False)
        assert idx.name == "idx_users_email"
        assert not idx.unique

    def test_foreign_key_model(self):
        fk = ForeignKey(
            name="fk_orders_user",
            table="orders",
            columns=["user_id"],
            ref_table="users",
            ref_columns=["id"],
        )
        assert fk.ref_table == "users"

    def test_enum_type_model(self):
        et = EnumType(name="status", values=["active", "inactive"])
        assert "active" in et.values

    def test_sequence_model(self):
        seq = Sequence(name="order_seq", start=1000, increment=1)
        assert seq.start == 1000

    def test_parsed_schema_model(self):
        ps = ParsedSchema(tables=[Table(name="users")])
        assert len(ps.tables) == 1
        assert ps.enum_types == []
        assert ps.sequences == []


class TestSchemaChangeStrNewTypes:
    """Gap A — SchemaChange.__str__ for new DDL object types."""

    def test_str_add_index_with_details(self):
        change = SchemaChange(type="ADD_INDEX", table="users",
                              details={"index_name": "idx_email", "columns": ["email"]})
        s = str(change)
        assert "idx_email" in s
        assert "users" in s

    def test_str_add_index_no_details(self):
        change = SchemaChange(type="ADD_INDEX", table="users")
        s = str(change)
        assert "ADD INDEX" in s
        assert "users" in s

    def test_str_drop_index_no_details(self):
        change = SchemaChange(type="DROP_INDEX", table="users")
        s = str(change)
        assert "DROP INDEX" in s

    def test_str_add_foreign_key(self):
        change = SchemaChange(type="ADD_FOREIGN_KEY", table="orders",
                              details={"name": "fk_user"})
        s = str(change)
        assert "ADD FOREIGN KEY" in s
        assert "fk_user" in s

    def test_str_drop_foreign_key(self):
        change = SchemaChange(type="DROP_FOREIGN_KEY", table="orders",
                              details={"name": "fk_user"})
        s = str(change)
        assert "DROP FOREIGN KEY" in s

    def test_str_add_check_constraint(self):
        change = SchemaChange(type="ADD_CHECK_CONSTRAINT", table="orders",
                              details={"name": "chk_pos"})
        s = str(change)
        assert "ADD CHECK CONSTRAINT" in s
        assert "chk_pos" in s

    def test_str_drop_check_constraint(self):
        change = SchemaChange(type="DROP_CHECK_CONSTRAINT", table="orders",
                              details={"name": "chk_pos"})
        s = str(change)
        assert "DROP CHECK CONSTRAINT" in s

    def test_str_add_unique_constraint(self):
        change = SchemaChange(type="ADD_UNIQUE_CONSTRAINT", table="users",
                              details={"name": "uq_email"})
        s = str(change)
        assert "ADD UNIQUE CONSTRAINT" in s

    def test_str_drop_unique_constraint(self):
        change = SchemaChange(type="DROP_UNIQUE_CONSTRAINT", table="users",
                              details={"name": "uq_email"})
        s = str(change)
        assert "DROP UNIQUE CONSTRAINT" in s

    def test_str_add_enum_type(self):
        change = SchemaChange(type="ADD_ENUM_TYPE", table="status_enum")
        assert "ADD ENUM TYPE" in str(change)

    def test_str_drop_enum_type(self):
        change = SchemaChange(type="DROP_ENUM_TYPE", table="status_enum")
        assert "DROP ENUM TYPE" in str(change)

    def test_str_change_enum_values(self):
        change = SchemaChange(type="CHANGE_ENUM_VALUES", table="status_enum")
        assert "CHANGE ENUM VALUES" in str(change)

    def test_str_add_sequence(self):
        change = SchemaChange(type="ADD_SEQUENCE", table="order_seq")
        assert "ADD SEQUENCE" in str(change)

    def test_str_drop_sequence(self):
        change = SchemaChange(type="DROP_SEQUENCE", table="order_seq")
        assert "DROP SEQUENCE" in str(change)

    def test_str_no_details_defaults_gracefully(self):
        """details=None must not raise for any new type."""
        for change_type in (
            "ADD_INDEX", "DROP_INDEX", "ADD_FOREIGN_KEY", "DROP_FOREIGN_KEY",
            "ADD_CHECK_CONSTRAINT", "DROP_CHECK_CONSTRAINT",
            "ADD_UNIQUE_CONSTRAINT", "DROP_UNIQUE_CONSTRAINT",
        ):
            change = SchemaChange(type=change_type, table="t")
            assert isinstance(str(change), str)


class TestColumnRawSqlTypeEquality:
    """Gap B — raw_sql_type is excluded from Column equality and hash."""

    def test_column_raw_sql_type_excluded_from_equality(self):
        col1 = Column(name="x", type=ColumnType.UNKNOWN, raw_sql_type="my_domain")
        col2 = Column(name="x", type=ColumnType.UNKNOWN, raw_sql_type="other_domain")
        assert col1 == col2

    def test_column_raw_sql_type_excluded_from_hash(self):
        col1 = Column(name="x", type=ColumnType.UNKNOWN, raw_sql_type="my_domain")
        col2 = Column(name="x", type=ColumnType.UNKNOWN, raw_sql_type="other_domain")
        assert hash(col1) == hash(col2)

    def test_column_raw_sql_type_does_not_affect_set_membership(self):
        col1 = Column(name="x", type=ColumnType.UNKNOWN, raw_sql_type="a")
        col2 = Column(name="x", type=ColumnType.UNKNOWN, raw_sql_type="b")
        assert len({col1, col2}) == 1


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
