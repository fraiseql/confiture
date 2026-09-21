"""Tests for schema drift detection."""

from unittest.mock import MagicMock, Mock

import pytest

from confiture.core.drift import (
    DriftItem,
    DriftReport,
    DriftSeverity,
    DriftType,
    SchemaDriftDetector,
    parse_expected_schema,
)
from confiture.core.schema_model import SchemaModel, Table
from confiture.core.type_lattice import same_type
from confiture.exceptions import SchemaError
from tests.unit._schema_models import index, model_of

# Exact block-comment file separator emitted by SchemaBuilder (block_comment is
# the default separator style) — reproduced here so the drift parser is proven
# to round-trip confiture's own build output (issue #175).
_BUILD_BLOCK_SEP = "\n/* " + "=" * 42 + "\n * File: {rel}\n * " + "=" * 42 + " */\n\n"


class TestDriftItem:
    """Tests for DriftItem dataclass."""

    def test_drift_item_creation(self):
        """Test creating a drift item."""
        item = DriftItem(
            drift_type=DriftType.MISSING_TABLE,
            severity=DriftSeverity.CRITICAL,
            object_name="users",
            expected="users",
            actual=None,
            message="Table 'users' is missing",
        )
        assert item.drift_type == DriftType.MISSING_TABLE
        assert item.severity == DriftSeverity.CRITICAL
        assert item.object_name == "users"
        assert "users" in str(item)

    def test_drift_item_to_dict(self):
        """Test converting drift item to dictionary."""
        item = DriftItem(
            drift_type=DriftType.EXTRA_COLUMN,
            severity=DriftSeverity.WARNING,
            object_name="users.email",
            message="Extra column",
        )
        result = item.to_dict()
        assert result["type"] == "extra_column"
        assert result["severity"] == "warning"
        assert result["object"] == "users.email"


class TestDriftReport:
    """Tests for DriftReport dataclass."""

    def test_empty_report_no_drift(self):
        """Test empty report has no drift."""
        report = DriftReport(
            database_name="test_db",
            expected_schema_source="migrations",
        )
        assert not report.has_drift
        assert not report.has_critical_drift
        assert report.critical_count == 0
        assert report.warning_count == 0

    def test_report_with_critical_drift(self):
        """Test report with critical drift."""
        report = DriftReport(
            database_name="test_db",
            expected_schema_source="migrations",
            drift_items=[
                DriftItem(
                    drift_type=DriftType.MISSING_TABLE,
                    severity=DriftSeverity.CRITICAL,
                    object_name="users",
                    message="Missing table",
                )
            ],
        )
        assert report.has_drift
        assert report.has_critical_drift
        assert report.critical_count == 1
        assert report.warning_count == 0

    def test_report_with_warning_only(self):
        """Test report with warning but no critical."""
        report = DriftReport(
            database_name="test_db",
            expected_schema_source="migrations",
            drift_items=[
                DriftItem(
                    drift_type=DriftType.EXTRA_TABLE,
                    severity=DriftSeverity.WARNING,
                    object_name="temp",
                    message="Extra table",
                )
            ],
        )
        assert report.has_drift
        assert not report.has_critical_drift
        assert report.warning_count == 1

    def test_report_to_dict(self):
        """Test report to dictionary conversion."""
        report = DriftReport(
            database_name="test_db",
            expected_schema_source="file:schema.sql",
            tables_checked=5,
            columns_checked=20,
            detection_time_ms=100,
        )
        result = report.to_dict()
        assert result["database_name"] == "test_db"
        assert result["expected_schema_source"] == "file:schema.sql"
        assert result["has_drift"] is False
        assert result["tables_checked"] == 5


def _tables(expected: SchemaModel) -> dict[str, Table]:
    """The model's tables keyed ``schema.table``, as a finding names them."""
    return {f"{t.schema}.{t.name}": t for t in expected.tables.values()}


def _parsed(sql: str) -> dict[str, Table]:
    return _tables(parse_expected_schema(sql).model)


class TestSchemaDriftDetector:
    """Tests for SchemaDriftDetector."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock connection."""
        conn = Mock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        # Mock database name query
        cursor.fetchone.return_value = ("test_db",)
        cursor.fetchall.return_value = []
        return conn, cursor

    def test_no_drift_identical_schemas(self, mock_connection):
        """Test no drift for identical schemas."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = model_of({"users": {"id": {"type": "integer", "nullable": False}}})
        actual = model_of({"users": {"id": {"type": "integer", "nullable": False}}})

        report = detector.compare_schemas(expected, actual)

        assert not report.has_drift
        assert report.tables_checked == 1

    def test_missing_table_detected(self, mock_connection):
        """Test missing table is detected as critical."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = model_of({"users": {"id": "integer"}, "orders": {"id": "integer"}})
        actual = model_of({"users": {"id": "integer"}})

        report = detector.compare_schemas(expected, actual)

        assert report.has_drift
        assert report.has_critical_drift
        assert report.critical_count == 1

        missing = [d for d in report.drift_items if d.drift_type == DriftType.MISSING_TABLE]
        assert len(missing) == 1
        # A model table always has a schema, so a finding names it (#227).
        assert missing[0].object_name == "public.orders"

    def test_extra_table_detected(self, mock_connection):
        """Test extra table is detected as warning."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = model_of({"users": {"id": "integer"}})
        actual = model_of({"users": {"id": "integer"}, "temp_data": {"id": "integer"}})

        report = detector.compare_schemas(expected, actual)

        assert report.has_drift
        assert not report.has_critical_drift
        assert report.warning_count == 1

        extra = [d for d in report.drift_items if d.drift_type == DriftType.EXTRA_TABLE]
        assert len(extra) == 1
        # A model table always has a schema, so a finding names it (#227).
        assert extra[0].object_name == "public.temp_data"

    def test_missing_column_detected(self, mock_connection):
        """Test missing column is detected as critical."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = model_of({"users": {"id": "integer", "email": "text"}})
        actual = model_of({"users": {"id": "integer"}})

        report = detector.compare_schemas(expected, actual)

        assert report.has_critical_drift
        missing = [d for d in report.drift_items if d.drift_type == DriftType.MISSING_COLUMN]
        assert len(missing) == 1
        assert missing[0].object_name == "public.users.email"

    def test_extra_column_detected(self, mock_connection):
        """Test extra column is detected as warning."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = model_of({"users": {"id": "integer"}})
        actual = model_of({"users": {"id": "integer", "legacy_field": "text"}})

        report = detector.compare_schemas(expected, actual)

        assert not report.has_critical_drift
        extra = [d for d in report.drift_items if d.drift_type == DriftType.EXTRA_COLUMN]
        assert len(extra) == 1
        assert extra[0].object_name == "public.users.legacy_field"

    def test_type_mismatch_detected(self, mock_connection):
        """Test column type mismatch is detected."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = model_of({"users": {"id": "integer"}})
        actual = model_of({"users": {"id": "bigint"}})

        report = detector.compare_schemas(expected, actual)

        mismatch = [d for d in report.drift_items if d.drift_type == DriftType.TYPE_MISMATCH]
        assert len(mismatch) == 1
        assert mismatch[0].severity == DriftSeverity.WARNING

    def test_type_aliases_compatible(self, mock_connection):
        """Test compatible type aliases don't trigger mismatch."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = model_of({"users": {"id": "integer"}})
        actual = model_of({"users": {"id": "int4"}})

        report = detector.compare_schemas(expected, actual)

        # integer and int4 are compatible
        mismatch = [d for d in report.drift_items if d.drift_type == DriftType.TYPE_MISMATCH]
        assert len(mismatch) == 0

    def test_nullable_mismatch_detected(self, mock_connection):
        """Test nullable mismatch is detected."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = model_of({"users": {"id": {"type": "integer", "nullable": False}}})
        actual = model_of({"users": {"id": {"type": "integer", "nullable": True}}})

        report = detector.compare_schemas(expected, actual)

        mismatch = [d for d in report.drift_items if d.drift_type == DriftType.NULLABLE_MISMATCH]
        assert len(mismatch) == 1

    def test_missing_index_detected(self, mock_connection):
        """Test missing index is detected as warning."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = model_of({"users": {"id": "integer"}}, indexes={"users": ["idx_users_email"]})
        actual = model_of({"users": {"id": "integer"}})

        report = detector.compare_schemas(expected, actual)

        missing = [d for d in report.drift_items if d.drift_type == DriftType.MISSING_INDEX]
        assert len(missing) == 1
        assert "idx_users_email" in missing[0].object_name

    def test_extra_index_detected(self, mock_connection):
        """Test extra index is detected as info."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = model_of({"users": {"id": "integer"}})
        actual = model_of({"users": {"id": "integer"}}, indexes={"users": ["idx_users_temp"]})

        report = detector.compare_schemas(expected, actual)

        extra = [d for d in report.drift_items if d.drift_type == DriftType.EXTRA_INDEX]
        assert len(extra) == 1
        assert extra[0].severity == DriftSeverity.INFO

    def test_ignore_tables(self, mock_connection):
        """Test ignored tables are not reported."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn, ignore_tables=["temp_data", "cache"])

        expected = model_of({"users": {"id": "integer"}})
        actual = model_of(
            {
                "users": {"id": "integer"},
                "temp_data": {"data": "jsonb"},
                "cache": {"key": "text"},
            }
        )

        report = detector.compare_schemas(expected, actual)

        # temp_data and cache should be ignored
        extra = [d for d in report.drift_items if d.drift_type == DriftType.EXTRA_TABLE]
        assert len(extra) == 0

    def test_system_tables_ignored(self, mock_connection):
        """Test Confiture system tables are always ignored."""
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)

        expected = SchemaModel()
        actual = model_of(
            {
                "tb_confiture": {"id": "integer"},
                "confiture_version": {"version": "text"},
            }
        )

        report = detector.compare_schemas(expected, actual)

        # System tables should be ignored
        assert not report.has_drift

    def test_parse_schema_from_sql(self):
        """Test parsing schema from SQL DDL."""
        sql = """
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) NOT NULL,
            name TEXT
        );

        CREATE INDEX idx_users_email ON users (email);

        CREATE TABLE orders (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id)
        );
        """

        tables = _parsed(sql)

        assert "public.users" in tables
        assert "public.orders" in tables
        assert tables["public.users"].column("id") is not None
        assert tables["public.users"].column("email") is not None
        assert [ix.name for ix in tables["public.users"].indexes] == ["idx_users_email"]

    def test_columns_carry_type_nullability_and_default(self):
        """Columns come out of the pglast walk with type, nullability and default."""
        create_stmt = """
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) NOT NULL,
            name TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """

        users = _parsed(create_stmt)["public.users"]
        columns = {c.folded: c for c in users.columns}

        assert list(columns) == ["id", "email", "name", "created_at"]
        assert columns["id"].not_null is True
        email = columns["email"]
        assert (email.type_text, email.not_null, email.default) == ("varchar(255)", True, None)
        assert columns["name"].not_null is False
        assert columns["created_at"].default == "now()"

    def test_types_compatible(self):
        """The pairs the deleted ``_types_compatible`` dict answered for, still answered.

        Its eleven aliases are now the one canonicaliser's, reached through
        ``type_lattice.same_type`` (#302). The wider table — typmods, arrays,
        domains, the parser's qualifier, the schema wildcard — is
        ``tests/unit/test_drift_type_comparison.py``.
        """
        assert same_type("integer", "int4")
        assert same_type("bigint", "int8")
        assert same_type("boolean", "bool")
        assert same_type("character varying", "varchar")
        assert same_type("timestamp with time zone", "timestamptz")

        assert not same_type("integer", "text")
        assert not same_type("boolean", "integer")

    # ------------------------------------------------------------------ #
    # Issue #175 — comment handling + silent-failure guard                #
    # ------------------------------------------------------------------ #

    def test_parse_schema_with_block_comment_separators(self):
        """confiture build's default block-comment file separators must not hide
        the CREATE TABLE that follows them (issue #175)."""
        sql = (
            _BUILD_BLOCK_SEP.format(rel="db/schema/10_tables/10_machine.sql")
            + "CREATE TABLE tb_machine (pk_machine UUID PRIMARY KEY, name TEXT NOT NULL);\n"
            + _BUILD_BLOCK_SEP.format(rel="db/schema/10_tables/20_part.sql")
            + "CREATE TABLE tb_part (pk_part UUID PRIMARY KEY, label TEXT NOT NULL);\n"
        )

        assert set(_parsed(sql)) == {"public.tb_machine", "public.tb_part"}

    def test_parse_schema_with_non_ascii_line_comment(self):
        """A non-ASCII (em-dash) line comment before a table must not hide it."""
        sql = (
            "-- Machine registry — core entity\n"
            "CREATE TABLE tb_machine (pk_machine UUID PRIMARY KEY, name TEXT NOT NULL);\n"
            "COMMENT ON TABLE tb_machine IS 'Machines';\n"
        )

        tables = _parsed(sql)

        assert "public.tb_machine" in tables
        assert tables["public.tb_machine"].column("name") is not None

    def test_create_table_in_function_body_not_parsed_as_table(self):
        """A dynamic ``CREATE TABLE`` inside a function body must not be mistaken
        for a real table, and must not trip the zero-tables guard when a real
        table is present."""
        sql = (
            "CREATE OR REPLACE FUNCTION make_tmp() RETURNS void LANGUAGE plpgsql AS $$\n"
            "BEGIN\n"
            "    EXECUTE 'CREATE TABLE tmp_scratch (id int)';\n"
            "END;\n"
            "$$;\n"
            "CREATE TABLE tb_real (id UUID PRIMARY KEY);\n"
        )

        assert list(_parsed(sql)) == ["public.tb_real"]

    def test_unparseable_schema_raises_instead_of_an_empty_expectation(self):
        """A schema pglast rejects must fail loudly (SCHEMA_202) instead of
        silently reporting every live table as spurious drift."""
        with pytest.raises(SchemaError) as excinfo:
            parse_expected_schema("CREATE TABEL users (id INTEGER PRIMARY KEY, email TEXT);")
        assert excinfo.value.error_code == "SCHEMA_202"

    def test_index_or_type_only_schema_does_not_raise(self):
        """A schema with no CREATE TABLE (indexes/types only) is a legitimate
        empty-table expectation, not a parse failure — must NOT raise."""
        sql = "CREATE TYPE order_status AS ENUM ('pending', 'shipped');\n"

        assert _parsed(sql) == {}  # must not raise

    def test_function_body_only_create_table_does_not_raise(self):
        """A schema whose only ``CREATE TABLE`` text lives inside a function body
        is table-less — the guard must not false-fire on it."""
        sql = (
            "CREATE OR REPLACE FUNCTION make_tmp() RETURNS void LANGUAGE plpgsql AS $$\n"
            "BEGIN\n"
            "    EXECUTE 'CREATE TABLE tmp_scratch (id int)';\n"
            "END;\n"
            "$$;\n"
        )

        assert _parsed(sql) == {}  # must not raise


class TestConstraintBackedIndexes:
    """A live index that backs a constraint is never an ``extra_index``."""

    @pytest.fixture
    def mock_connection(self):
        conn = Mock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        cursor.fetchone.return_value = ("test_db",)
        cursor.fetchall.return_value = []
        return conn, cursor

    def test_constraint_backed_live_index_is_not_extra(self, mock_connection):
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)
        expected = model_of({"users": {"id": "integer"}})
        actual = model_of(
            {"users": {"id": "integer"}},
            indexes={
                "users": [
                    index("users_pkey", "users", "id", unique=True, backs_constraint=True),
                    index("users_email_key", "users", "email", unique=True, backs_constraint=True),
                    "idx_users_tmp",
                ]
            },
        )

        report = detector.compare_schemas(expected, actual)

        extra = [d for d in report.drift_items if d.drift_type == DriftType.EXTRA_INDEX]
        # A model table always has a schema, so a finding names it (#227).
        assert [d.object_name for d in extra] == ["public.users.idx_users_tmp"]

    def test_declared_index_that_backs_a_constraint_is_matched_by_name(self, mock_connection):
        conn, _ = mock_connection
        detector = SchemaDriftDetector(conn)
        expected = model_of({"users": {"id": "integer"}}, indexes={"users": ["users_email_uq"]})
        actual = model_of(
            {"users": {"id": "integer"}},
            indexes={
                "users": [
                    index("users_pkey", "users", "id", unique=True, backs_constraint=True),
                    index("users_email_uq", "users", "email", unique=True, backs_constraint=True),
                ]
            },
        )

        report = detector.compare_schemas(expected, actual)

        assert [d for d in report.drift_items if d.drift_type == DriftType.MISSING_INDEX] == []
        assert [d for d in report.drift_items if d.drift_type == DriftType.EXTRA_INDEX] == []
