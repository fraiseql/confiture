"""What the ledger probe answers against a real PostgreSQL (#188).

``tests/unit/test_ledger.py`` pins the SQL shape. This file pins the semantics,
which is where the bug lived: a bare ``tb_confiture`` matched the table in *any*
schema, so the probe and the query it was a precondition for could disagree.

Every scenario here is provisioned in its own schema inside the shared test
database and torn down after, so the tests are order-independent and leave no
residue. The two role-based scenarios skip cleanly where the connection cannot
create a role — that is a permission of the environment, not a gap in cover.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from confiture.core.ledger import find_ledger_relations, probe_ledger


@pytest.fixture
def conn(test_db_url: str) -> Iterator[psycopg.Connection]:
    """An autocommit connection; each test owns its own schemas."""
    try:
        connection = psycopg.connect(test_db_url, autocommit=True)
    except psycopg.OperationalError as e:  # pragma: no cover - environment gate
        pytest.skip(f"PostgreSQL not available: {e}")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def tag() -> str:
    """A per-test suffix so parallel runs never collide on schema names."""
    return uuid.uuid4().hex[:10]


def _make_ledger(conn: psycopg.Connection, schema: str, name: str = "tb_confiture") -> None:
    conn.execute(f'CREATE SCHEMA "{schema}"')
    conn.execute(f'CREATE TABLE "{schema}"."{name}" (version text)')


def _drop_schemas(conn: psycopg.Connection, *schemas: str) -> None:
    for schema in schemas:
        conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


class TestSearchPathResolution:
    def test_ledger_on_search_path_resolves_to_its_real_schema(
        self, conn: psycopg.Connection, tag: str
    ) -> None:
        schema = f"onpath_{tag}"
        _make_ledger(conn, schema)
        try:
            conn.execute(f'SET search_path TO "{schema}", public')

            probe = probe_ledger(conn, "tb_confiture")

            assert probe.exists is True
            assert probe.resolved_name == f"{schema}.tb_confiture"
        finally:
            conn.execute("SET search_path TO public")
            _drop_schemas(conn, schema)

    def test_ledger_off_search_path_reports_absent(
        self, conn: psycopg.Connection, tag: str
    ) -> None:
        """The defect, stated positively.

        Pre-0.41.0 this returned present, so `migrate status` announced a
        ledger the session could not read and `initialize()` skipped a CREATE
        the session needed.
        """
        schema = f"offpath_{tag}"
        _make_ledger(conn, schema)
        try:
            conn.execute("SET search_path TO public")

            probe = probe_ledger(conn, "tb_confiture")

            assert probe.exists is False
            assert probe.resolved_name is None
            # ...but the relation is genuinely there. Without this the test
            # would pass just as well against an empty database.
            assert find_ledger_relations(conn, "tb_confiture") == [f"{schema}.tb_confiture"]
        finally:
            _drop_schemas(conn, schema)

    def test_same_name_in_two_schemas_resolves_to_the_first_on_search_path(
        self, conn: psycopg.Connection, tag: str
    ) -> None:
        first, second = f"first_{tag}", f"second_{tag}"
        _make_ledger(conn, first)
        _make_ledger(conn, second)
        try:
            conn.execute(f'SET search_path TO "{first}", "{second}"')
            assert probe_ledger(conn, "tb_confiture").resolved_name == f"{first}.tb_confiture"

            # Reversing the search_path reverses the answer — proof the probe
            # reads search_path rather than, say, OID order.
            conn.execute(f'SET search_path TO "{second}", "{first}"')
            assert probe_ledger(conn, "tb_confiture").resolved_name == f"{second}.tb_confiture"
        finally:
            conn.execute("SET search_path TO public")
            _drop_schemas(conn, first, second)

    def test_a_sequence_of_the_same_name_is_not_a_ledger(
        self, conn: psycopg.Connection, tag: str
    ) -> None:
        schema = f"seqonly_{tag}"
        conn.execute(f'CREATE SCHEMA "{schema}"')
        conn.execute(f'CREATE SEQUENCE "{schema}".tb_confiture')
        try:
            conn.execute(f'SET search_path TO "{schema}"')

            assert probe_ledger(conn, "tb_confiture").exists is False
        finally:
            conn.execute("SET search_path TO public")
            _drop_schemas(conn, schema)

    def test_a_view_of_the_same_name_still_counts(self, conn: psycopg.Connection, tag: str) -> None:
        """`information_schema.tables` counted views, so this one must not change."""
        schema = f"viewonly_{tag}"
        conn.execute(f'CREATE SCHEMA "{schema}"')
        conn.execute(f'CREATE VIEW "{schema}".tb_confiture AS SELECT 1 AS version')
        try:
            conn.execute(f'SET search_path TO "{schema}"')

            assert probe_ledger(conn, "tb_confiture").exists is True
        finally:
            conn.execute("SET search_path TO public")
            _drop_schemas(conn, schema)


class TestQualifiedProbeIsUnchanged:
    def test_qualified_name_finds_a_ledger_off_search_path(
        self, conn: psycopg.Connection, tag: str
    ) -> None:
        """Naming the schema is how you reach a ledger search_path cannot see."""
        schema = f"qualified_{tag}"
        _make_ledger(conn, schema)
        try:
            conn.execute("SET search_path TO public")

            probe = probe_ledger(conn, f"{schema}.tb_confiture")

            assert probe.exists is True
            assert probe.resolved_name == f"{schema}.tb_confiture"
        finally:
            _drop_schemas(conn, schema)

    def test_qualified_name_does_not_match_another_schema(
        self, conn: psycopg.Connection, tag: str
    ) -> None:
        schema = f"elsewhere_{tag}"
        _make_ledger(conn, schema)
        try:
            assert probe_ledger(conn, "public.tb_confiture").exists is False
        finally:
            _drop_schemas(conn, schema)


@pytest.fixture
def restricted(
    conn: psycopg.Connection, test_db_url: str, tag: str
) -> Iterator[tuple[str, psycopg.Connection]]:
    """A schema plus a connection as a role with no USAGE on it.

    This is the scenario #188's decision turns on: ``to_regclass('s.t')`` raises
    `permission denied for schema s` here, while `information_schema` returns
    cleanly. Skips where the test connection cannot create a role.
    """
    schema, role = f"restricted_{tag}", f"probe_role_{tag}"
    try:
        conn.execute(f'CREATE ROLE "{role}" LOGIN')
    except psycopg.errors.InsufficientPrivilege:  # pragma: no cover - environment gate
        pytest.skip("test connection cannot CREATE ROLE")
    _make_ledger(conn, schema)
    conn.execute(f'GRANT SELECT ON "{schema}".tb_confiture TO "{role}"')
    # Deliberately no GRANT USAGE ON SCHEMA.
    restricted_conn = None
    try:
        info = psycopg.conninfo.conninfo_to_dict(test_db_url)
        info["user"] = role
        info.pop("password", None)
        try:
            restricted_conn = psycopg.connect(psycopg.conninfo.make_conninfo(**info))
        except psycopg.OperationalError as e:  # pragma: no cover - environment gate
            pytest.skip(f"cannot connect as an unprivileged role: {e}")
        yield schema, restricted_conn
    finally:
        if restricted_conn is not None:
            restricted_conn.close()
        _drop_schemas(conn, schema)
        conn.execute(f'DROP ROLE IF EXISTS "{role}"')


class TestPrivileges:
    def test_qualified_probe_answers_cleanly_without_schema_usage(
        self, restricted: tuple[str, psycopg.Connection]
    ) -> None:
        """The regression guard for #182: no raw psycopg exception, ever.

        `information_schema` reports the row even though the role cannot read
        the table. That is a wrong answer to "can I read this?" — and the right
        answer to "is it there?", which is what this probe is for. #188's
        decision keeps it rather than swap a wrong answer for a crash.
        """
        schema, restricted_conn = restricted

        probe = probe_ledger(restricted_conn, f"{schema}.tb_confiture")

        assert probe.exists is True

    def test_bare_probe_skips_a_schema_the_role_cannot_use(
        self, restricted: tuple[str, psycopg.Connection]
    ) -> None:
        """Even with the schema on search_path, resolution yields NULL not an error.

        This is why the bare path needs no privilege special-casing: PostgreSQL
        silently drops search_path entries the role has no USAGE on.
        """
        schema, restricted_conn = restricted
        restricted_conn.execute(f'SET search_path TO "{schema}"')

        probe = probe_ledger(restricted_conn, "tb_confiture")

        assert probe.exists is False

    def test_a_readable_ledger_is_reported_present(
        self, conn: psycopg.Connection, restricted: tuple[str, psycopg.Connection], tag: str
    ) -> None:
        """Sanity anchor: the role is not simply blind to everything."""
        _schema, restricted_conn = restricted
        visible = f"visible_{tag}"
        _make_ledger(conn, visible)
        role = f"probe_role_{tag}"
        conn.execute(f'GRANT USAGE ON SCHEMA "{visible}" TO "{role}"')
        try:
            restricted_conn.execute(f'SET search_path TO "{visible}"')

            probe = probe_ledger(restricted_conn, "tb_confiture")

            assert probe.exists is True
            assert probe.resolved_name == f"{visible}.tb_confiture"
        finally:
            restricted_conn.rollback()
            _drop_schemas(conn, visible)

    def test_no_select_privilege_still_reports_present(
        self, conn: psycopg.Connection, tag: str
    ) -> None:
        """Presence, not readability — #188 dropped `readable` deliberately.

        ``has_table_privilege`` raises on the very USAGE-less case the field was
        meant to describe, so deriving readability from it would have traded one
        wrong answer for an exception.
        """
        schema = f"noselect_{tag}"
        _make_ledger(conn, schema)
        try:
            conn.execute(f'SET search_path TO "{schema}"')
            conn.execute(f'REVOKE ALL ON "{schema}".tb_confiture FROM PUBLIC')

            assert probe_ledger(conn, "tb_confiture").exists is True
        finally:
            conn.execute("SET search_path TO public")
            _drop_schemas(conn, schema)


class TestFindLedgerRelations:
    def test_finds_every_copy_across_schemas(self, conn: psycopg.Connection, tag: str) -> None:
        alpha, beta = f"alpha_{tag}", f"beta_{tag}"
        _make_ledger(conn, alpha)
        _make_ledger(conn, beta)
        try:
            found = find_ledger_relations(conn, "tb_confiture")

            assert f"{alpha}.tb_confiture" in found
            assert f"{beta}.tb_confiture" in found
        finally:
            _drop_schemas(conn, alpha, beta)

    def test_returns_empty_when_the_name_is_unused(
        self, conn: psycopg.Connection, tag: str
    ) -> None:
        assert find_ledger_relations(conn, f"tb_absent_{tag}") == []
