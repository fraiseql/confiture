"""Tests for schema analysis and validation."""

from unittest.mock import MagicMock, Mock

import pytest

from confiture.core import live_catalog
from confiture.core.schema_analyzer import (
    LiveSchema,
    SchemaAnalyzer,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from confiture.core.schema_model import SchemaModel
from tests.unit._schema_models import index, model, model_of, table


def _live(tables: dict) -> LiveSchema:
    """The validator's view of a live ``public`` schema holding *tables*."""
    return LiveSchema(model_of(tables))


class TestValidationIssue:
    """Tests for ValidationIssue dataclass."""

    def test_issue_creation(self):
        """Test creating a validation issue."""
        issue = ValidationIssue(
            severity=ValidationSeverity.ERROR,
            message="Table does not exist",
            sql_fragment="DROP TABLE users",
            line_number=1,
            suggestion="Add IF EXISTS",
        )
        assert issue.severity == ValidationSeverity.ERROR
        assert issue.message == "Table does not exist"
        assert issue.sql_fragment == "DROP TABLE users"
        assert issue.line_number == 1
        assert issue.suggestion == "Add IF EXISTS"

    def test_issue_to_dict(self):
        """Test converting issue to dictionary."""
        issue = ValidationIssue(
            severity=ValidationSeverity.WARNING,
            message="Test message",
        )
        result = issue.to_dict()
        assert result["severity"] == "warning"
        assert result["message"] == "Test message"
        assert result["sql_fragment"] is None


class TestLiveSchema:
    """The validator's questions, answered from the live schema model."""

    def test_an_empty_model_has_no_table_and_no_index(self):
        live = LiveSchema(SchemaModel())
        assert not live.has_table("users")
        assert live.columns("users") == {}
        assert live.index_names() == set()

    def test_it_answers_from_the_model(self):
        """The dict of dicts shaped for the validator is gone; the model is read."""
        live = _live({"users": {"id": "integer"}})
        assert live.has_table("users")
        assert list(live.columns("users")) == ["id"]
        assert live.columns("users")["id"].type_text == "integer"

    def test_a_table_outside_public_is_not_one_the_validator_sees(self):
        """The validator asks about bare names, which resolve in ``public``."""
        live = LiveSchema(
            model_of({"public.users": {"id": "integer"}, "tenant.orders": {"id": "integer"}})
        )
        assert live.has_table("users")
        assert not live.has_table("orders")

    def test_index_names_include_constraint_backing_ones(self):
        """``DROP INDEX users_pkey`` names an index that exists, whoever created it."""
        live = LiveSchema(
            model(
                table(
                    "users",
                    indexes=[
                        index("users_pkey", "users", "id", unique=True, backs_constraint=True),
                        "idx_users_email",
                    ],
                ),
                table("tenant.orders", indexes=["idx_orders_elsewhere"]),
            )
        )
        assert live.index_names() == {"users_pkey", "idx_users_email"}


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_empty_result_is_valid(self):
        """Test empty result is valid."""
        result = ValidationResult(
            migration_name="test",
            migration_version="001",
        )
        assert result.is_valid
        assert not result.has_errors
        assert not result.has_warnings
        assert result.error_count == 0
        assert result.warning_count == 0

    def test_result_with_error(self):
        """Test result with error is invalid."""
        result = ValidationResult(
            migration_name="test",
            migration_version="001",
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    message="Test error",
                )
            ],
        )
        assert not result.is_valid
        assert result.has_errors
        assert result.error_count == 1

    def test_result_with_warning(self):
        """Test result with warning only is valid."""
        result = ValidationResult(
            migration_name="test",
            migration_version="001",
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    message="Test warning",
                )
            ],
        )
        assert result.is_valid  # Warnings don't make it invalid
        assert not result.has_errors
        assert result.has_warnings
        assert result.warning_count == 1

    def test_result_to_dict(self):
        """Test result to dictionary."""
        result = ValidationResult(
            migration_name="create_users",
            migration_version="001",
            statements_analyzed=5,
            validation_time_ms=100,
        )
        data = result.to_dict()
        assert data["migration_name"] == "create_users"
        assert data["migration_version"] == "001"
        assert data["is_valid"] is True
        assert data["statements_analyzed"] == 5
        assert data["validation_time_ms"] == 100


class TestSchemaAnalyzer:
    """Tests for SchemaAnalyzer."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock connection with cursor."""
        conn = Mock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        return conn, cursor

    def test_live_schema_caches(self, mock_connection, monkeypatch):
        """Test schema info is cached."""
        conn, _cursor = mock_connection
        # The live side is `live_catalog.read`'s; what is tested here is the cache.
        monkeypatch.setattr(live_catalog, "read", lambda *_a, **_k: SchemaModel())

        analyzer = SchemaAnalyzer(conn)

        # First call
        info1 = analyzer.live_schema()
        # Second call should use cache
        info2 = analyzer.live_schema()

        assert info1 is info2

    def test_live_schema_refresh(self, mock_connection, monkeypatch):
        """Test schema info refresh."""
        conn, _cursor = mock_connection
        # The live side is `live_catalog.read`'s; what is tested here is the cache.
        monkeypatch.setattr(live_catalog, "read", lambda *_a, **_k: SchemaModel())

        analyzer = SchemaAnalyzer(conn)

        info1 = analyzer.live_schema()
        info2 = analyzer.live_schema(refresh=True)

        # Should be different objects after refresh
        assert info1 is not info2

    def test_validate_create_table_exists(self):
        """Test validation catches existing table without IF NOT EXISTS."""
        schema = _live({"users": {"id": {"type": "integer"}}})

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_create(
            "CREATE TABLE users (id INT)",
            schema,
            1,
        )

        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR
        assert "already exists" in issues[0].message

    def test_validate_create_table_if_not_exists(self):
        """Test IF NOT EXISTS doesn't trigger error."""
        schema = _live({"users": {"id": {"type": "integer"}}})

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_create(
            "CREATE TABLE IF NOT EXISTS users (id INT)",
            schema,
            1,
        )

        # Should not have an error for table already exists
        table_exists_errors = [i for i in issues if "already exists" in i.message]
        assert len(table_exists_errors) == 0

    def test_validate_create_index_nonexistent_table(self):
        """Test validation catches index on missing table."""
        schema = LiveSchema(SchemaModel())

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_create(
            "CREATE INDEX idx_users_email ON users (email)",
            schema,
            1,
        )

        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR
        assert "does not exist" in issues[0].message

    def test_validate_create_index_column_missing(self):
        """Test validation catches index on missing column."""
        schema = _live({"users": {"id": {"type": "integer"}}})

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_create(
            "CREATE INDEX idx_users_email ON users (email)",
            schema,
            1,
        )

        assert any(i.severity == ValidationSeverity.ERROR and "email" in i.message for i in issues)

    def test_validate_alter_nonexistent_table(self):
        """Test validation catches missing table."""
        schema = LiveSchema(SchemaModel())

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_alter(
            "ALTER TABLE users ADD COLUMN email TEXT",
            schema,
            1,
        )

        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR
        assert "does not exist" in issues[0].message

    def test_validate_alter_table_if_exists(self):
        """Test IF EXISTS doesn't trigger error."""
        schema = LiveSchema(SchemaModel())

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_alter(
            "ALTER TABLE IF EXISTS users ADD COLUMN email TEXT",
            schema,
            1,
        )

        # Should not have an error for table not existing
        assert len(issues) == 0

    def test_validate_add_existing_column(self):
        """Test validation catches existing column."""
        schema = _live({"users": {"id": {"type": "integer"}, "email": {"type": "text"}}})

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_column_operations(
            "ALTER TABLE users ADD COLUMN email TEXT",
            schema,
            "users",
            1,
        )

        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR
        assert "already exists" in issues[0].message

    def test_validate_drop_nonexistent_column(self):
        """Test validation catches missing column."""
        schema = _live({"users": {"id": {"type": "integer"}}})

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_column_operations(
            "ALTER TABLE users DROP COLUMN email",
            schema,
            "users",
            1,
        )

        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR
        assert "does not exist" in issues[0].message

    def test_validate_drop_column_if_exists(self):
        """Test DROP COLUMN IF EXISTS doesn't trigger error."""
        schema = _live({"users": {"id": {"type": "integer"}}})

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_column_operations(
            "ALTER TABLE users DROP COLUMN IF EXISTS email",
            schema,
            "users",
            1,
        )

        assert len(issues) == 0

    def test_validate_drop_table_nonexistent(self):
        """Test validation catches dropping missing table."""
        schema = LiveSchema(SchemaModel())

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_drop(
            "DROP TABLE users",
            schema,
            1,
        )

        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR
        assert "does not exist" in issues[0].message

    def test_validate_drop_table_if_exists(self):
        """Test DROP TABLE IF EXISTS doesn't trigger error."""
        schema = LiveSchema(SchemaModel())

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_drop(
            "DROP TABLE IF EXISTS users",
            schema,
            1,
        )

        assert len(issues) == 0

    def test_validate_fk_missing_target_table(self):
        """Test FK validation catches missing target table."""
        schema = _live({"orders": {"id": {"type": "integer"}}})

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issue = analyzer.validate_foreign_key(
            source_table="orders",
            source_column="user_id",
            target_table="users",
            target_column="id",
        )

        assert issue is not None
        assert issue.severity == ValidationSeverity.ERROR
        assert "does not exist" in issue.message

    def test_validate_fk_missing_target_column(self):
        """Test FK validation catches missing target column."""
        schema = _live(
            {
                "users": {"id": {"type": "integer"}},
                "orders": {"user_id": {"type": "integer"}},
            }
        )

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issue = analyzer.validate_foreign_key(
            source_table="orders",
            source_column="user_id",
            target_table="users",
            target_column="uuid",  # Doesn't exist
        )

        assert issue is not None
        assert issue.severity == ValidationSeverity.ERROR
        assert "does not exist" in issue.message

    def test_validate_fk_valid(self):
        """Test FK validation passes for valid reference."""
        schema = _live(
            {
                "users": {"id": {"type": "integer"}},
                "orders": {"user_id": {"type": "integer"}},
            }
        )

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issue = analyzer.validate_foreign_key(
            source_table="orders",
            source_column="user_id",
            target_table="users",
            target_column="id",
        )

        assert issue is None

    def test_validate_fk_type_mismatch(self):
        """Test FK validation warns on type mismatch."""
        schema = _live(
            {
                "users": {"id": {"type": "uuid"}},
                "orders": {"user_id": {"type": "integer"}},
            }
        )

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issue = analyzer.validate_foreign_key(
            source_table="orders",
            source_column="user_id",
            target_table="users",
            target_column="id",
        )

        assert issue is not None
        assert issue.severity == ValidationSeverity.WARNING
        assert "type mismatch" in issue.message

    def test_validate_insert_nonexistent_table(self):
        """Test INSERT validation catches missing table."""
        schema = LiveSchema(SchemaModel())

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_insert(
            "INSERT INTO users (id) VALUES (1)",
            schema,
            1,
        )

        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR
        assert "does not exist" in issues[0].message

    def test_validate_update_nonexistent_table(self):
        """Test UPDATE validation catches missing table."""
        schema = LiveSchema(SchemaModel())

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_update(
            "UPDATE users SET email = 'test@example.com'",
            schema,
            1,
        )

        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR

    def test_validate_delete_nonexistent_table(self):
        """Test DELETE validation catches missing table."""
        schema = LiveSchema(SchemaModel())

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_delete(
            "DELETE FROM users WHERE id = 1",
            schema,
            1,
        )

        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR

    def test_validate_sql_multiple_statements(self):
        """Test validating multiple SQL statements."""
        schema = _live({"users": {"id": {"type": "integer"}}})

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        sql = """
        CREATE TABLE orders (id INT);
        ALTER TABLE nonexistent ADD COLUMN foo TEXT;
        DROP TABLE missing;
        """

        issues = analyzer.validate_sql(sql)

        # Should find issues for nonexistent table and missing table
        assert len(issues) >= 2
        error_messages = [i.message for i in issues]
        assert any("nonexistent" in m.lower() for m in error_messages)
        assert any("missing" in m.lower() for m in error_messages)

    def test_validate_fk_in_create_table(self):
        """Test FK validation in CREATE TABLE statement."""
        schema = LiveSchema(SchemaModel())

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_fk_references_in_create(
            "CREATE TABLE orders (id INT, user_id INT REFERENCES users(id))",
            schema,
            1,
        )

        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR
        assert "users" in issues[0].message

    def test_validate_drop_index_nonexistent(self):
        """Test validation catches dropping missing index."""
        schema = LiveSchema(SchemaModel())

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_drop(
            "DROP INDEX idx_users_email",
            schema,
            1,
        )

        assert len(issues) == 1
        assert issues[0].severity == ValidationSeverity.ERROR
        assert "does not exist" in issues[0].message

    def test_validate_drop_index_if_exists(self):
        """Test DROP INDEX IF EXISTS doesn't trigger error."""
        schema = LiveSchema(SchemaModel())

        analyzer = SchemaAnalyzer(Mock())
        analyzer._live = schema

        issues = analyzer._validate_drop(
            "DROP INDEX IF EXISTS idx_users_email",
            schema,
            1,
        )

        assert len(issues) == 0
