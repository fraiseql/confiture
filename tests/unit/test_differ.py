"""Unit tests for SchemaDiffer (Milestone 1.9-1.10)."""

from confiture.core.differ import SchemaDiffer
from confiture.models.schema import ColumnType, ParsedSchema


class TestSQLParser:
    """Test SQL parsing functionality (Milestone 1.9)."""

    def test_parse_simple_create_table(self):
        """Should parse simple CREATE TABLE statement."""
        sql = "CREATE TABLE users (id INT PRIMARY KEY, name TEXT)"

        differ = SchemaDiffer()
        tables = differ.parse_sql(sql)

        assert len(tables) == 1
        assert tables[0].name == "users"
        assert len(tables[0].columns) == 2

        # Check first column
        id_col = tables[0].columns[0]
        assert id_col.name == "id"
        assert id_col.type == ColumnType.INTEGER
        assert id_col.primary_key is True

        # Check second column
        name_col = tables[0].columns[1]
        assert name_col.name == "name"
        assert name_col.type == ColumnType.TEXT

    def test_parse_create_table_with_not_null(self):
        """Should parse NOT NULL constraints."""
        sql = """
        CREATE TABLE posts (
            id SERIAL PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            content TEXT
        )
        """

        differ = SchemaDiffer()
        tables = differ.parse_sql(sql)

        assert len(tables) == 1
        table = tables[0]
        assert table.name == "posts"

        # title should be NOT NULL
        title_col = table.get_column("title")
        assert title_col is not None
        assert title_col.nullable is False
        assert title_col.type == ColumnType.VARCHAR
        assert title_col.length == 255

        # content should be nullable (default)
        content_col = table.get_column("content")
        assert content_col is not None
        assert content_col.nullable is True

    def test_parse_multiple_tables(self):
        """Should parse multiple CREATE TABLE statements."""
        sql = """
        CREATE TABLE users (
            id INT PRIMARY KEY,
            username TEXT NOT NULL
        );

        CREATE TABLE posts (
            id INT PRIMARY KEY,
            user_id INT NOT NULL,
            title TEXT
        );
        """

        differ = SchemaDiffer()
        tables = differ.parse_sql(sql)

        assert len(tables) == 2
        assert tables[0].name == "users"
        assert tables[1].name == "posts"

    def test_parse_with_default_values(self):
        """Should parse DEFAULT constraints."""
        sql = """
        CREATE TABLE settings (
            id SERIAL PRIMARY KEY,
            enabled BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """

        differ = SchemaDiffer()
        tables = differ.parse_sql(sql)

        table = tables[0]
        enabled_col = table.get_column("enabled")
        assert enabled_col is not None
        assert enabled_col.default is not None
        assert "TRUE" in enabled_col.default.upper()

        created_at_col = table.get_column("created_at")
        assert created_at_col is not None
        assert created_at_col.default is not None
        assert "NOW" in created_at_col.default.upper()

    def test_parse_ignores_non_create_statements(self):
        """Should only parse CREATE TABLE statements."""
        sql = """
        INSERT INTO users VALUES (1, 'test');
        CREATE TABLE users (id INT);
        UPDATE users SET name = 'test';
        """

        differ = SchemaDiffer()
        tables = differ.parse_sql(sql)

        # Should only find the CREATE TABLE statement
        assert len(tables) == 1
        assert tables[0].name == "users"

    def test_parse_empty_sql(self):
        """Should handle empty SQL gracefully."""
        differ = SchemaDiffer()
        tables = differ.parse_sql("")

        assert tables == []

    def test_parse_comments_in_sql(self):
        """Should handle SQL comments."""
        sql = """
        -- This is a comment
        CREATE TABLE users (
            id INT PRIMARY KEY, -- Primary key column
            name TEXT
        );
        """

        differ = SchemaDiffer()
        tables = differ.parse_sql(sql)

        assert len(tables) == 1
        assert tables[0].name == "users"
        assert len(tables[0].columns) == 2


class TestSchemaDiffAlgorithm:
    """Test schema diff algorithm (Milestone 1.10)."""

    def test_compare_identical_schemas(self):
        """Should return no changes when schemas are identical."""
        sql = """
        CREATE TABLE users (
            id INT PRIMARY KEY,
            name TEXT NOT NULL
        );
        """

        differ = SchemaDiffer()
        diff = differ.compare(sql, sql)

        assert len(diff.changes) == 0

    def test_detect_new_table(self):
        """Should detect when a new table is added."""
        old_sql = "CREATE TABLE users (id INT PRIMARY KEY);"
        new_sql = """
        CREATE TABLE users (id INT PRIMARY KEY);
        CREATE TABLE posts (id INT PRIMARY KEY, title TEXT);
        """

        differ = SchemaDiffer()
        diff = differ.compare(old_sql, new_sql)

        assert len(diff.changes) == 1
        change = diff.changes[0]
        assert change.type == "ADD_TABLE"
        assert change.table == "posts"

    def test_detect_dropped_table(self):
        """Should detect when a table is removed."""
        old_sql = """
        CREATE TABLE users (id INT PRIMARY KEY);
        CREATE TABLE posts (id INT PRIMARY KEY);
        """
        new_sql = "CREATE TABLE users (id INT PRIMARY KEY);"

        differ = SchemaDiffer()
        diff = differ.compare(old_sql, new_sql)

        assert len(diff.changes) == 1
        change = diff.changes[0]
        assert change.type == "DROP_TABLE"
        assert change.table == "posts"

    def test_detect_new_column(self):
        """Should detect when a new column is added."""
        old_sql = "CREATE TABLE users (id INT PRIMARY KEY);"
        new_sql = "CREATE TABLE users (id INT PRIMARY KEY, name TEXT);"

        differ = SchemaDiffer()
        diff = differ.compare(old_sql, new_sql)

        assert len(diff.changes) == 1
        change = diff.changes[0]
        assert change.type == "ADD_COLUMN"
        assert change.table == "users"
        assert change.column == "name"

    def test_detect_dropped_column(self):
        """Should detect when a column is removed."""
        old_sql = "CREATE TABLE users (id INT PRIMARY KEY, name TEXT, age INT);"
        new_sql = "CREATE TABLE users (id INT PRIMARY KEY, name TEXT);"

        differ = SchemaDiffer()
        diff = differ.compare(old_sql, new_sql)

        assert len(diff.changes) == 1
        change = diff.changes[0]
        assert change.type == "DROP_COLUMN"
        assert change.table == "users"
        assert change.column == "age"

    def test_detect_column_type_change(self):
        """Should detect when a column type changes."""
        old_sql = "CREATE TABLE users (id INT PRIMARY KEY, age INT);"
        new_sql = "CREATE TABLE users (id INT PRIMARY KEY, age BIGINT);"

        differ = SchemaDiffer()
        diff = differ.compare(old_sql, new_sql)

        assert len(diff.changes) == 1
        change = diff.changes[0]
        assert change.type == "CHANGE_COLUMN_TYPE"
        assert change.table == "users"
        assert change.column == "age"
        assert change.old_value == "INTEGER"
        assert change.new_value == "BIGINT"

    def test_detect_column_rename(self):
        """Should detect column rename (fuzzy matching)."""
        old_sql = "CREATE TABLE users (id INT PRIMARY KEY, full_name TEXT);"
        new_sql = "CREATE TABLE users (id INT PRIMARY KEY, display_name TEXT);"

        differ = SchemaDiffer()
        diff = differ.compare(old_sql, new_sql)

        # Should detect as rename (not drop+add)
        assert len(diff.changes) == 1
        change = diff.changes[0]
        assert change.type == "RENAME_COLUMN"
        assert change.table == "users"
        assert change.old_value == "full_name"
        assert change.new_value == "display_name"

    def test_detect_nullable_change(self):
        """Should detect when nullable constraint changes."""
        old_sql = "CREATE TABLE users (id INT PRIMARY KEY, name TEXT);"
        new_sql = "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL);"

        differ = SchemaDiffer()
        diff = differ.compare(old_sql, new_sql)

        assert len(diff.changes) == 1
        change = diff.changes[0]
        assert change.type == "CHANGE_COLUMN_NULLABLE"
        assert change.table == "users"
        assert change.column == "name"
        assert change.old_value == "true"
        assert change.new_value == "false"

    def test_detect_default_change(self):
        """Should detect when default value changes."""
        old_sql = "CREATE TABLE settings (enabled BOOLEAN DEFAULT FALSE);"
        new_sql = "CREATE TABLE settings (enabled BOOLEAN DEFAULT TRUE);"

        differ = SchemaDiffer()
        diff = differ.compare(old_sql, new_sql)

        assert len(diff.changes) == 1
        change = diff.changes[0]
        assert change.type == "CHANGE_COLUMN_DEFAULT"
        assert change.table == "settings"
        assert change.column == "enabled"

    def test_detect_multiple_changes(self):
        """Should detect multiple changes across tables."""
        old_sql = """
        CREATE TABLE users (
            id INT PRIMARY KEY,
            name TEXT
        );
        CREATE TABLE posts (
            id INT PRIMARY KEY,
            title TEXT
        );
        """
        new_sql = """
        CREATE TABLE users (
            id INT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT
        );
        CREATE TABLE comments (
            id INT PRIMARY KEY,
            content TEXT
        );
        """

        differ = SchemaDiffer()
        diff = differ.compare(old_sql, new_sql)

        # Expected changes:
        # 1. users.name: nullable changed
        # 2. users.email: column added
        # 3. posts: table dropped
        # 4. comments: table added
        assert len(diff.changes) == 4

        change_types = [c.type for c in diff.changes]
        assert "CHANGE_COLUMN_NULLABLE" in change_types
        assert "ADD_COLUMN" in change_types
        assert "DROP_TABLE" in change_types
        assert "ADD_TABLE" in change_types

    def test_compare_empty_schemas(self):
        """Should handle empty schemas gracefully."""
        differ = SchemaDiffer()
        diff = differ.compare("", "")

        assert len(diff.changes) == 0

    def test_compare_with_table_rename(self):
        """Should detect table rename (fuzzy matching)."""
        old_sql = "CREATE TABLE user_accounts (id INT PRIMARY KEY);"
        new_sql = "CREATE TABLE user_profiles (id INT PRIMARY KEY);"

        differ = SchemaDiffer()
        diff = differ.compare(old_sql, new_sql)

        # Should detect as rename (not drop+add)
        assert len(diff.changes) == 1
        change = diff.changes[0]
        assert change.type == "RENAME_TABLE"
        assert change.old_value == "user_accounts"
        assert change.new_value == "user_profiles"


class TestUnknownTypeHandling:
    """Phase 01: ColumnType.UNKNOWN silent diff misses."""

    def test_parse_column_type_money(self):
        differ = SchemaDiffer()
        col_type, _ = differ._parse_column_type("MONEY")
        assert col_type == ColumnType.MONEY

    def test_parse_column_type_inet(self):
        differ = SchemaDiffer()
        col_type, _ = differ._parse_column_type("INET")
        assert col_type == ColumnType.INET

    def test_parse_column_type_tsvector(self):
        differ = SchemaDiffer()
        col_type, _ = differ._parse_column_type("TSVECTOR")
        assert col_type == ColumnType.TSVECTOR

    def test_parse_column_type_cidr(self):
        differ = SchemaDiffer()
        col_type, _ = differ._parse_column_type("CIDR")
        assert col_type == ColumnType.CIDR

    def test_change_between_two_unknown_types_is_detected(self):
        differ = SchemaDiffer()
        old_sql = "CREATE TABLE products (amount my_domain NOT NULL);"
        new_sql = "CREATE TABLE products (amount other_domain NOT NULL);"
        diff = differ.compare(old_sql, new_sql)
        assert diff.has_changes()
        assert any(c.type == "CHANGE_COLUMN_TYPE" for c in diff.changes)

    def test_same_unknown_type_is_not_a_change(self):
        differ = SchemaDiffer()
        old_sql = "CREATE TABLE products (amount my_domain NOT NULL);"
        new_sql = "CREATE TABLE products (amount my_domain NOT NULL);"
        diff = differ.compare(old_sql, new_sql)
        assert not diff.has_changes()

    def test_array_type_change_detected(self):
        differ = SchemaDiffer()
        old_sql = "CREATE TABLE t (tags INT[] NOT NULL);"
        new_sql = "CREATE TABLE t (tags TEXT[] NOT NULL);"
        diff = differ.compare(old_sql, new_sql)
        assert any(c.type == "CHANGE_COLUMN_TYPE" for c in diff.changes)

    def test_money_to_numeric_change_detected(self):
        differ = SchemaDiffer()
        old_sql = "CREATE TABLE t (price MONEY NOT NULL);"
        new_sql = "CREATE TABLE t (price NUMERIC NOT NULL);"
        diff = differ.compare(old_sql, new_sql)
        assert any(c.type == "CHANGE_COLUMN_TYPE" for c in diff.changes)


class TestParseSchema:
    """Phase 02: parse_schema returns ParsedSchema with enums/sequences."""

    def test_parse_sql_returns_list_of_tables(self):
        differ = SchemaDiffer()
        tables = differ.parse_sql("CREATE TABLE users (id INT);")
        assert len(tables) == 1

    def test_parse_schema_returns_parsed_schema(self):
        differ = SchemaDiffer()
        result = differ.parse_schema("CREATE TABLE users (id INT);")
        assert isinstance(result, ParsedSchema)
        assert len(result.tables) == 1

    def test_parse_schema_extracts_enum(self):
        differ = SchemaDiffer()
        sql = "CREATE TYPE status AS ENUM ('active', 'inactive', 'banned');"
        result = differ.parse_schema(sql)
        assert len(result.enum_types) == 1
        assert result.enum_types[0].name == "status"
        assert "active" in result.enum_types[0].values

    def test_parse_schema_extracts_sequence(self):
        differ = SchemaDiffer()
        sql = "CREATE SEQUENCE order_seq START 1000 INCREMENT 1;"
        result = differ.parse_schema(sql)
        assert len(result.sequences) == 1
        assert result.sequences[0].name == "order_seq"
        assert result.sequences[0].start == 1000

    def test_parse_schema_extracts_index(self):
        differ = SchemaDiffer()
        sql = (
            "CREATE TABLE users (id INT, email TEXT);\n"
            "CREATE INDEX idx_users_email ON users(email);"
        )
        result = differ.parse_schema(sql)
        assert len(result.tables) == 1
        assert len(result.tables[0].indexes) == 1
        assert result.tables[0].indexes[0].name == "idx_users_email"

    def test_parse_schema_extracts_unique_index(self):
        differ = SchemaDiffer()
        sql = (
            "CREATE TABLE users (id INT, email TEXT);\n"
            "CREATE UNIQUE INDEX idx_unique_email ON users(email);"
        )
        result = differ.parse_schema(sql)
        idx = result.tables[0].indexes[0]
        assert idx.unique is True

    def test_parse_schema_extracts_fk_from_alter(self):
        differ = SchemaDiffer()
        sql = (
            "CREATE TABLE users (id INT);\n"
            "CREATE TABLE orders (id INT, user_id INT);\n"
            "ALTER TABLE orders ADD CONSTRAINT fk_orders_user "
            "FOREIGN KEY (user_id) REFERENCES users(id);"
        )
        result = differ.parse_schema(sql)
        orders = next(t for t in result.tables if t.name == "orders")
        assert len(orders.foreign_keys) == 1
        assert orders.foreign_keys[0].name == "fk_orders_user"
        assert orders.foreign_keys[0].ref_table == "users"


class TestIndexDiff:
    """Phase 02 Cycle 3: Index diffing."""

    def test_diff_detects_new_index(self):
        differ = SchemaDiffer()
        old = "CREATE TABLE users (id INT, email TEXT);"
        new = (
            "CREATE TABLE users (id INT, email TEXT);\n"
            "CREATE INDEX idx_users_email ON users(email);"
        )
        diff = differ.compare(old, new)
        assert any(c.type == "ADD_INDEX" for c in diff.changes)

    def test_diff_detects_dropped_index(self):
        differ = SchemaDiffer()
        old = (
            "CREATE TABLE users (id INT, email TEXT);\n"
            "CREATE INDEX idx_users_email ON users(email);"
        )
        new = "CREATE TABLE users (id INT, email TEXT);"
        diff = differ.compare(old, new)
        assert any(c.type == "DROP_INDEX" for c in diff.changes)

    def test_diff_no_change_when_indexes_identical(self):
        differ = SchemaDiffer()
        sql = (
            "CREATE TABLE users (id INT, email TEXT);\n"
            "CREATE INDEX idx ON users(email);"
        )
        diff = differ.compare(sql, sql)
        assert not diff.has_changes()


class TestForeignKeyDiff:
    """Phase 02 Cycle 4: Foreign key diffing."""

    _BASE = (
        "CREATE TABLE users (id INT);\n"
        "CREATE TABLE orders (id INT, user_id INT);\n"
    )

    def test_diff_detects_new_fk(self):
        differ = SchemaDiffer()
        old = self._BASE
        new = (
            self._BASE
            + "ALTER TABLE orders ADD CONSTRAINT fk_orders_user "
            "FOREIGN KEY (user_id) REFERENCES users(id);"
        )
        diff = differ.compare(old, new)
        assert any(c.type == "ADD_FOREIGN_KEY" for c in diff.changes)

    def test_diff_detects_dropped_fk(self):
        differ = SchemaDiffer()
        old = (
            self._BASE
            + "ALTER TABLE orders ADD CONSTRAINT fk_orders_user "
            "FOREIGN KEY (user_id) REFERENCES users(id);"
        )
        new = self._BASE
        diff = differ.compare(old, new)
        assert any(c.type == "DROP_FOREIGN_KEY" for c in diff.changes)


class TestEnumDiff:
    """Phase 02 Cycle 6: Enum type diffing."""

    def test_diff_detects_new_enum(self):
        differ = SchemaDiffer()
        old = "CREATE TABLE t (id INT);"
        new = "CREATE TABLE t (id INT);\nCREATE TYPE status AS ENUM ('a', 'b');"
        diff = differ.compare(old, new)
        assert any(c.type == "ADD_ENUM_TYPE" for c in diff.changes)

    def test_diff_detects_dropped_enum(self):
        differ = SchemaDiffer()
        old = "CREATE TABLE t (id INT);\nCREATE TYPE status AS ENUM ('a', 'b');"
        new = "CREATE TABLE t (id INT);"
        diff = differ.compare(old, new)
        assert any(c.type == "DROP_ENUM_TYPE" for c in diff.changes)

    def test_diff_detects_changed_enum_values(self):
        differ = SchemaDiffer()
        old = "CREATE TYPE status AS ENUM ('active', 'inactive');"
        new = "CREATE TYPE status AS ENUM ('active', 'inactive', 'banned');"
        diff = differ.compare(old, new)
        assert any(c.type == "CHANGE_ENUM_VALUES" for c in diff.changes)
        change = next(c for c in diff.changes if c.type == "CHANGE_ENUM_VALUES")
        assert "banned" in change.details["added_values"]

    def test_diff_no_change_when_enum_identical(self):
        differ = SchemaDiffer()
        sql = "CREATE TYPE status AS ENUM ('active', 'inactive');"
        diff = differ.compare(sql, sql)
        assert not diff.has_changes()


class TestSequenceDiff:
    """Phase 02 Cycle 7: Sequence diffing."""

    def test_diff_detects_new_sequence(self):
        differ = SchemaDiffer()
        old = "CREATE TABLE t (id INT);"
        new = "CREATE TABLE t (id INT);\nCREATE SEQUENCE order_seq START 1;"
        diff = differ.compare(old, new)
        assert any(c.type == "ADD_SEQUENCE" for c in diff.changes)

    def test_diff_detects_dropped_sequence(self):
        differ = SchemaDiffer()
        old = "CREATE TABLE t (id INT);\nCREATE SEQUENCE order_seq START 1;"
        new = "CREATE TABLE t (id INT);"
        diff = differ.compare(old, new)
        assert any(c.type == "DROP_SEQUENCE" for c in diff.changes)
