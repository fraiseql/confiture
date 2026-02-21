"""Unit tests for SchemaIntrospector.

All database interactions are mocked so these tests run without PostgreSQL.
"""

from unittest.mock import MagicMock

from confiture.core.introspector import SchemaIntrospector, _detect_hints
from confiture.models.introspection import (
    FKReference,
    IntrospectedColumn,
    IntrospectedTable,
)


def _make_conn(rows_per_execute: list[list[tuple]]) -> MagicMock:
    """Build a mock psycopg connection whose cursor returns successive row sets.

    Each call to cursor.execute() is paired with a fetchall() that returns
    the next entry in rows_per_execute.
    """
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    cursor.fetchall.side_effect = rows_per_execute
    cursor.fetchone.return_value = ("testdb",)
    return conn


class TestListTables:
    """Tests for _list_tables()."""

    def test_default_filter_returns_only_tb_tables(self):
        """Only tables starting with tb_ are returned when all_tables=False."""
        conn = _make_conn([[("tb_user",), ("tb_post",)]])
        introspector = SchemaIntrospector(conn)
        tables = introspector._list_tables("public", all_tables=False)
        assert tables == ["tb_user", "tb_post"]

    def test_all_tables_returns_every_table(self):
        """all_tables=True returns all base tables regardless of name."""
        conn = _make_conn([[("audit_log",), ("tb_user",), ("users",)]])
        introspector = SchemaIntrospector(conn)
        tables = introspector._list_tables("public", all_tables=True)
        assert tables == ["audit_log", "tb_user", "users"]

    def test_empty_schema_returns_empty_list(self):
        """Empty schema yields empty list."""
        conn = _make_conn([[]])
        introspector = SchemaIntrospector(conn)
        assert introspector._list_tables("public", all_tables=False) == []


class TestGetPrimaryKeys:
    """Tests for _get_primary_keys()."""

    def test_single_pk_column(self):
        """Single-column primary key is returned as a one-element set."""
        conn = _make_conn([[("pk_user",)]])
        introspector = SchemaIntrospector(conn)
        pks = introspector._get_primary_keys("public", "tb_user")
        assert pks == {"pk_user"}

    def test_composite_pk(self):
        """Composite primary key returns all member columns."""
        conn = _make_conn([[("fk_left",), ("fk_right",)]])
        introspector = SchemaIntrospector(conn)
        pks = introspector._get_primary_keys("public", "tb_join")
        assert pks == {"fk_left", "fk_right"}

    def test_no_pk(self):
        """Table without a PK returns an empty set."""
        conn = _make_conn([[]])
        introspector = SchemaIntrospector(conn)
        assert introspector._get_primary_keys("public", "tb_nopk") == set()


class TestGetColumns:
    """Tests for _get_columns()."""

    def test_pg_type_preserved_verbatim(self):
        """pg_type values from format_type() are kept as-is."""
        rows = [
            ("pk_user", "bigint", False),
            ("id", "uuid", False),
            ("email", "character varying(255)", False),
            ("bio", "text", True),
        ]
        conn = _make_conn([rows])
        introspector = SchemaIntrospector(conn)
        cols = introspector._get_columns("public", "tb_user", {"pk_user"})

        assert cols[0].pg_type == "bigint"
        assert cols[2].pg_type == "character varying(255)"

    def test_primary_key_flag_set_correctly(self):
        """is_primary_key is True only for columns in the pk_cols set."""
        rows = [("pk_user", "bigint", False), ("username", "text", False)]
        conn = _make_conn([rows])
        introspector = SchemaIntrospector(conn)
        cols = introspector._get_columns("public", "tb_user", {"pk_user"})

        assert cols[0].is_primary_key is True
        assert cols[1].is_primary_key is False

    def test_nullable_flag(self):
        """nullable flag matches the NOT attnotnull expression."""
        rows = [("name", "text", True), ("required", "text", False)]
        conn = _make_conn([rows])
        introspector = SchemaIntrospector(conn)
        cols = introspector._get_columns("public", "tb_x", set())

        assert cols[0].nullable is True
        assert cols[1].nullable is False


class TestGetOutboundFks:
    """Tests for _get_outbound_fks()."""

    def test_single_fk(self):
        """Single FK produces one FKReference with to_table set."""
        rows = [("fk_user", "tb_user", "pk_user")]
        conn = _make_conn([rows])
        introspector = SchemaIntrospector(conn)
        fks = introspector._get_outbound_fks("public", "tb_post")

        assert len(fks) == 1
        assert fks[0].to_table == "tb_user"
        assert fks[0].via_column == "fk_user"
        assert fks[0].on_column == "pk_user"
        assert fks[0].from_table is None

    def test_no_fks(self):
        """Table without FKs returns empty list."""
        conn = _make_conn([[]])
        introspector = SchemaIntrospector(conn)
        assert introspector._get_outbound_fks("public", "tb_user") == []

    def test_multiple_fks(self):
        """Multiple FK columns produce one FKReference each."""
        rows = [
            ("fk_user", "tb_user", "pk_user"),
            ("fk_category", "tb_category", "pk_category"),
        ]
        conn = _make_conn([rows])
        introspector = SchemaIntrospector(conn)
        fks = introspector._get_outbound_fks("public", "tb_post")
        assert len(fks) == 2


class TestResolveInboundFks:
    """Tests for _resolve_inbound_fks()."""

    def test_outbound_fk_creates_inbound_on_target(self):
        """An outbound FK on tb_post creates an inbound FK on tb_user."""
        tb_user = IntrospectedTable("tb_user", [], [], [], None)
        tb_post = IntrospectedTable(
            "tb_post",
            [],
            [
                FKReference(
                    from_table=None, to_table="tb_user", via_column="fk_user", on_column="pk_user"
                )
            ],
            [],
            None,
        )
        introspector = SchemaIntrospector(MagicMock())
        introspector._resolve_inbound_fks([tb_user, tb_post])

        assert len(tb_user.inbound_fks) == 1
        inbound = tb_user.inbound_fks[0]
        assert inbound.from_table == "tb_post"
        assert inbound.to_table is None
        assert inbound.via_column == "fk_user"
        assert inbound.on_column == "pk_user"

    def test_fk_to_unknown_table_is_silently_skipped(self):
        """FK pointing outside the introspected set does not error."""
        tb_post = IntrospectedTable(
            "tb_post",
            [],
            [
                FKReference(
                    from_table=None, to_table="external_table", via_column="fk_ext", on_column="id"
                )
            ],
            [],
            None,
        )
        introspector = SchemaIntrospector(MagicMock())
        introspector._resolve_inbound_fks([tb_post])  # should not raise

    def test_no_fks_leaves_inbound_empty(self):
        """Tables with no outbound FKs keep empty inbound_fks."""
        tb_a = IntrospectedTable("tb_a", [], [], [], None)
        tb_b = IntrospectedTable("tb_b", [], [], [], None)
        introspector = SchemaIntrospector(MagicMock())
        introspector._resolve_inbound_fks([tb_a, tb_b])
        assert tb_a.inbound_fks == []
        assert tb_b.inbound_fks == []


class TestDetectHints:
    """Tests for the _detect_hints() module-level function."""

    def test_surrogate_pk_detected(self):
        """pk_* primary key column is surfaced as surrogate_pk."""
        cols = [
            IntrospectedColumn("pk_user", "bigint", False, True),
            IntrospectedColumn("username", "text", False, False),
        ]
        hints = _detect_hints(cols)
        assert hints is not None
        assert hints.surrogate_pk == "pk_user"

    def test_natural_id_detected(self):
        """Column named 'id' is surfaced as natural_id."""
        cols = [
            IntrospectedColumn("pk_user", "bigint", False, True),
            IntrospectedColumn("id", "uuid", False, False),
        ]
        hints = _detect_hints(cols)
        assert hints is not None
        assert hints.natural_id == "id"

    def test_both_detected_together(self):
        """surrogate_pk and natural_id can both be present."""
        cols = [
            IntrospectedColumn("pk_user", "bigint", False, True),
            IntrospectedColumn("id", "uuid", False, False),
            IntrospectedColumn("email", "text", False, False),
        ]
        hints = _detect_hints(cols)
        assert hints is not None
        assert hints.surrogate_pk == "pk_user"
        assert hints.natural_id == "id"

    def test_no_pattern_returns_none(self):
        """Tables with no recognised conventions return None (not empty hints)."""
        cols = [
            IntrospectedColumn("user_id", "bigint", False, True),
            IntrospectedColumn("email", "text", False, False),
        ]
        assert _detect_hints(cols) is None

    def test_non_pk_column_named_pk_prefix_ignored(self):
        """pk_ prefix is only meaningful on primary-key columns."""
        cols = [
            IntrospectedColumn("pk_alias", "text", True, False),  # not a PK
            IntrospectedColumn("real_pk", "bigint", False, True),
        ]
        hints = _detect_hints(cols)
        # pk_alias is not a PK column — no surrogate_pk; no 'id' col either
        assert hints is None
