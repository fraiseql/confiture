"""Unit tests for SchemaIntrospector.

All database interactions are mocked so these tests run without PostgreSQL.
"""

from unittest.mock import MagicMock

import pytest

from confiture.core import live_catalog
from confiture.core.introspection.tables import SchemaIntrospector, _detect_hints
from confiture.core.schema_model import Column, Constraint, SchemaModel, Table, ref_for
from confiture.models.introspection import (
    FKReference,
    IntrospectedColumn,
    IntrospectedTable,
)


def stub_catalog(monkeypatch: pytest.MonkeyPatch, *tables: Table) -> list[dict]:
    """Answer ``live_catalog.read`` with *tables*; return the calls it received.

    The introspector reads the schema through ``core/live_catalog``; what is
    tested here is what it makes of the model. What the reader answers on a real
    server is ``tests/integration/test_introspection_live.py``.
    """
    calls: list[dict] = []

    def read(_conn: object, **kwargs: object) -> SchemaModel:
        calls.append(kwargs)
        return SchemaModel(tables={ref_for("table", t.schema, t.name): t for t in tables})

    monkeypatch.setattr(live_catalog, "read", read)
    return calls


def _conn() -> MagicMock:
    """A connection whose only query is ``current_database()``."""
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = ("testdb",)
    return conn


def column(name: str, type_text: str = "bigint", *, not_null: bool = False, pk: bool = False):
    return Column(
        name=name, folded=name, line=0, type_text=type_text, not_null=not_null, primary_key=pk
    )


def table(name: str, *columns: Column, constraints: tuple[Constraint, ...] = ()) -> Table:
    return Table(name=name, schema="public", columns=columns, constraints=constraints)


def fk(name: str, columns: tuple[str, ...], ref_table: str, ref_columns: tuple[str, ...]):
    return Constraint(
        kind="foreign_key",
        name=name,
        columns=columns,
        ref_table=ref_table,
        ref_columns=ref_columns,
    )


def introspect(monkeypatch: pytest.MonkeyPatch, *tables: Table, **kwargs: object):
    stub_catalog(monkeypatch, *tables)
    return SchemaIntrospector(_conn()).introspect(**kwargs)


class TestListTables:
    """Which tables are introspected."""

    def test_default_filter_returns_only_tb_tables(self, monkeypatch):
        """Only tables starting with tb_ are returned when all_tables=False."""
        result = introspect(
            monkeypatch, table("tb_user"), table("audit_log"), table("tb_post"), all_tables=False
        )
        assert [t.name for t in result.tables] == ["tb_user", "tb_post"]

    def test_all_tables_returns_every_table(self, monkeypatch):
        """all_tables=True returns all base tables regardless of name."""
        result = introspect(
            monkeypatch, table("audit_log"), table("tb_user"), table("users"), all_tables=True
        )
        assert [t.name for t in result.tables] == ["audit_log", "tb_user", "users"]

    def test_empty_schema_returns_empty_list(self, monkeypatch):
        """Empty schema yields empty list."""
        assert introspect(monkeypatch, all_tables=False).tables == []

    def test_reads_the_schema_asked_for_and_ordinary_tables_only(self, monkeypatch):
        """A partitioned parent is not read — ``introspect`` never read one."""
        calls = stub_catalog(monkeypatch)
        result = SchemaIntrospector(_conn()).introspect(schema="catalog")
        assert calls == [{"schemas": ["catalog"], "kinds": ("r",)}]
        assert (result.schema, result.database) == ("catalog", "testdb")


class TestPrimaryKeys:
    """is_primary_key comes from the primary key the reader found."""

    def test_single_pk_column(self, monkeypatch):
        """Single-column primary key flags exactly that column."""
        result = introspect(
            monkeypatch, table("tb_user", column("pk_user", pk=True), column("name", "text"))
        )
        assert {c.name for c in result.tables[0].columns if c.is_primary_key} == {"pk_user"}

    def test_composite_pk(self, monkeypatch):
        """Composite primary key flags all member columns."""
        result = introspect(
            monkeypatch,
            table("tb_join", column("fk_left", pk=True), column("fk_right", pk=True)),
        )
        assert {c.name for c in result.tables[0].columns if c.is_primary_key} == {
            "fk_left",
            "fk_right",
        }

    def test_no_pk(self, monkeypatch):
        """Table without a PK flags nothing."""
        result = introspect(monkeypatch, table("tb_nopk", column("a"), column("b")))
        assert not any(c.is_primary_key for c in result.tables[0].columns)


class TestColumns:
    """Columns, in order, as the reader spelled them."""

    def test_pg_type_preserved_verbatim(self, monkeypatch):
        """pg_type values from format_type() are kept as-is."""
        result = introspect(
            monkeypatch,
            table(
                "tb_user",
                column("pk_user", "bigint", pk=True),
                column("id", "uuid"),
                column("email", "character varying(255)"),
                column("bio", "text"),
            ),
        )
        cols = result.tables[0].columns
        assert cols[0].pg_type == "bigint"
        assert cols[2].pg_type == "character varying(255)"

    def test_primary_key_flag_set_correctly(self, monkeypatch):
        """is_primary_key is True only for primary-key columns."""
        result = introspect(
            monkeypatch,
            table("tb_user", column("pk_user", pk=True), column("username", "text")),
        )
        cols = result.tables[0].columns
        assert cols[0].is_primary_key is True
        assert cols[1].is_primary_key is False

    def test_nullable_flag(self, monkeypatch):
        """nullable is the negation of NOT NULL."""
        result = introspect(
            monkeypatch,
            table("tb_x", column("name", "text"), column("required", "text", not_null=True)),
        )
        cols = result.tables[0].columns
        assert cols[0].nullable is True
        assert cols[1].nullable is False


class TestOutboundFks:
    """Outbound FKs, one reference per column pair."""

    def test_single_fk(self, monkeypatch):
        """Single FK produces one FKReference with to_table set."""
        result = introspect(
            monkeypatch,
            table(
                "tb_post",
                column("fk_user"),
                constraints=(fk("fk_post_user", ("fk_user",), "tb_user", ("pk_user",)),),
            ),
        )
        fks = result.tables[0].outbound_fks
        assert len(fks) == 1
        assert fks[0].to_table == "tb_user"
        assert fks[0].via_column == "fk_user"
        assert fks[0].on_column == "pk_user"
        assert fks[0].from_table is None

    def test_no_fks(self, monkeypatch):
        """Table without FKs returns empty list."""
        result = introspect(monkeypatch, table("tb_user", column("pk_user", pk=True)))
        assert result.tables[0].outbound_fks == []

    def test_multiple_fks(self, monkeypatch):
        """Multiple FK columns produce one FKReference each."""
        result = introspect(
            monkeypatch,
            table(
                "tb_post",
                constraints=(
                    fk("a_user", ("fk_user",), "tb_user", ("pk_user",)),
                    fk("b_category", ("fk_category",), "tb_category", ("pk_category",)),
                ),
            ),
        )
        assert len(result.tables[0].outbound_fks) == 2

    def test_composite_fk_pairs_columns_in_key_order(self, monkeypatch):
        """A composite key pairs position with position — never a cross product."""
        result = introspect(
            monkeypatch,
            table("tb_child", constraints=(fk("zz_pair", ("pb", "pa"), "tb_pair", ("b", "a")),)),
        )
        assert [(f.via_column, f.on_column) for f in result.tables[0].outbound_fks] == [
            ("pb", "b"),
            ("pa", "a"),
        ]

    def test_a_qualified_reference_names_the_bare_table(self, monkeypatch):
        """``pg_get_constraintdef`` qualifies a table ``search_path`` misses."""
        result = introspect(
            monkeypatch,
            table("tb_child", constraints=(fk("fk_ext", ("ext_id",), "other.tb_ext", ("id",)),)),
        )
        assert result.tables[0].outbound_fks[0].to_table == "tb_ext"

    def test_other_constraints_are_not_foreign_keys(self, monkeypatch):
        result = introspect(
            monkeypatch,
            table(
                "tb_x",
                constraints=(
                    Constraint(kind="primary_key", name="tb_x_pkey", columns=("id",)),
                    Constraint(kind="check", name="ck", expression="id > 0"),
                ),
            ),
        )
        assert result.tables[0].outbound_fks == []


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
        assert introspector._resolve_inbound_fks([tb_post]) is None
        assert tb_post.inbound_fks == []

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
