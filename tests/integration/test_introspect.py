"""Integration tests for SchemaIntrospector.

These tests require a running PostgreSQL instance accessible at
CONFITURE_TEST_DB_URL (default: postgresql://localhost/confiture_test).

Run with:
    uv run pytest tests/integration/test_introspect.py -v
"""

import psycopg
import pytest

from confiture.core.introspector import SchemaIntrospector


@pytest.fixture
def introspect_db(clean_test_db: psycopg.Connection) -> psycopg.Connection:
    """Set up a minimal schema for introspection tests.

    Creates:
      - tb_user  (pk_user bigint PK, id uuid, username text)
      - tb_post  (pk_post bigint PK, id uuid, fk_user → tb_user.pk_user, title text)
      - tb_comment (pk_comment bigint PK, fk_post → tb_post.pk_post, body text)
      - audit_log (no tb_ prefix — used to test table filtering)
    """
    conn = clean_test_db
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE tb_user (
                pk_user  BIGINT PRIMARY KEY,
                id       UUID   NOT NULL,
                username TEXT   NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE tb_post (
                pk_post  BIGINT PRIMARY KEY,
                id       UUID   NOT NULL,
                fk_user  BIGINT NOT NULL REFERENCES tb_user(pk_user),
                title    TEXT   NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE tb_comment (
                pk_comment BIGINT PRIMARY KEY,
                fk_post    BIGINT NOT NULL REFERENCES tb_post(pk_post),
                body       TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE audit_log (
                log_id    BIGSERIAL PRIMARY KEY,
                event     TEXT NOT NULL,
                logged_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        conn.commit()
    return conn


class TestIntrospectorIntegration:
    """Integration tests against a real PostgreSQL database."""

    def test_returns_only_tb_tables_by_default(self, introspect_db):
        """Default filter includes only tb_* tables."""
        introspector = SchemaIntrospector(introspect_db)
        result = introspector.introspect(schema="public", all_tables=False)

        names = {t.name for t in result.tables}
        assert "tb_user" in names
        assert "tb_post" in names
        assert "tb_comment" in names
        assert "audit_log" not in names

    def test_all_tables_includes_non_prefixed(self, introspect_db):
        """--all-tables includes audit_log alongside tb_* tables."""
        introspector = SchemaIntrospector(introspect_db)
        result = introspector.introspect(schema="public", all_tables=True)

        names = {t.name for t in result.tables}
        assert "audit_log" in names
        assert "tb_user" in names

    def test_column_types_are_accurate(self, introspect_db):
        """Column pg_type values match what PostgreSQL actually stores."""
        introspector = SchemaIntrospector(introspect_db)
        result = introspector.introspect(schema="public")

        tb_user = next(t for t in result.tables if t.name == "tb_user")
        col_map = {c.name: c for c in tb_user.columns}

        assert col_map["pk_user"].pg_type == "bigint"
        assert col_map["id"].pg_type == "uuid"
        assert col_map["username"].pg_type == "text"

    def test_primary_key_flagged(self, introspect_db):
        """The declared primary key column has is_primary_key=True."""
        introspector = SchemaIntrospector(introspect_db)
        result = introspector.introspect(schema="public")

        tb_user = next(t for t in result.tables if t.name == "tb_user")
        col_map = {c.name: c for c in tb_user.columns}

        assert col_map["pk_user"].is_primary_key is True
        assert col_map["id"].is_primary_key is False
        assert col_map["username"].is_primary_key is False

    def test_outbound_fk_graph(self, introspect_db):
        """tb_post declares an outbound FK to tb_user."""
        introspector = SchemaIntrospector(introspect_db)
        result = introspector.introspect(schema="public")

        tb_post = next(t for t in result.tables if t.name == "tb_post")
        assert len(tb_post.outbound_fks) == 1
        fk = tb_post.outbound_fks[0]
        assert fk.to_table == "tb_user"
        assert fk.via_column == "fk_user"
        assert fk.on_column == "pk_user"
        assert fk.from_table is None

    def test_inbound_fk_graph(self, introspect_db):
        """tb_user receives an inbound FK from tb_post."""
        introspector = SchemaIntrospector(introspect_db)
        result = introspector.introspect(schema="public")

        tb_user = next(t for t in result.tables if t.name == "tb_user")
        assert len(tb_user.inbound_fks) == 1
        fk = tb_user.inbound_fks[0]
        assert fk.from_table == "tb_post"
        assert fk.via_column == "fk_user"
        assert fk.on_column == "pk_user"
        assert fk.to_table is None

    def test_hints_detected(self, introspect_db):
        """Surrogate PK and natural ID hints are detected on tb_user."""
        introspector = SchemaIntrospector(introspect_db)
        result = introspector.introspect(schema="public", include_hints=True)

        tb_user = next(t for t in result.tables if t.name == "tb_user")
        assert tb_user.hints is not None
        assert tb_user.hints.surrogate_pk == "pk_user"
        assert tb_user.hints.natural_id == "id"

    def test_no_hints_flag(self, introspect_db):
        """include_hints=False leaves hints as None on every table."""
        introspector = SchemaIntrospector(introspect_db)
        result = introspector.introspect(schema="public", include_hints=False)

        assert all(t.hints is None for t in result.tables)

    def test_to_dict_is_json_serialisable(self, introspect_db):
        """to_dict() produces a structure that round-trips through json.dumps."""
        import json

        introspector = SchemaIntrospector(introspect_db)
        result = introspector.introspect(schema="public")
        serialised = json.dumps(result.to_dict())
        parsed = json.loads(serialised)
        assert parsed["schema"] == "public"
        assert isinstance(parsed["tables"], list)
