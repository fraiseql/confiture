"""Unit tests for SchemaDiffer (Milestone 1.9-1.10)."""

from confiture.core.differ import SchemaDiffer
from confiture.models.schema import Column, ColumnType, Table


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
