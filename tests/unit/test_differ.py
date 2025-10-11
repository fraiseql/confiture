"""Unit tests for SchemaDiffer (Milestone 1.9-1.10)."""

from confiture.core.differ import SchemaDiffer
from confiture.models.schema import ColumnType


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
