"""``plpgsql_check``, run over the DDL built into a throwaway database (#245).

The check needs three things to line up: a writable maintenance server, a
scratch database built from the schema files, and the extension available on
that server. Only the last is unusual — no PostgreSQL distribution ships
``plpgsql_check`` — so every one of these tests skips where it is absent, and
the skip path itself is covered by the unit tests instead.

What is being established here is that the *seam* works: the DDL reaches a real
database through ``ExpectedSchemaDB.from_source``, the analyser reaches every
routine in it, and the database is gone afterwards.
"""

from __future__ import annotations

import psycopg
import pytest
from tests._helpers import plpgsql_check_url

from confiture.core.linting import bodies

#: The issue's own reproduction: a ``UUID`` variable fed from a ``BIGINT``
#: column. PostgreSQL stores this body without resolving a thing, so it deploys
#: clean and raises on the first call.
REPRODUCTION = """CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE app.tb_widget (pk_widget BIGINT PRIMARY KEY, name TEXT NOT NULL);
CREATE FUNCTION app.fn_widget_pk(p_name TEXT) RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE
    v_pk UUID;
BEGIN
    SELECT pk_widget INTO v_pk FROM app.tb_widget WHERE name = p_name;
    RETURN v_pk;
END;
$$;
"""

CLEAN = """CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE app.tb_widget (pk_widget BIGINT PRIMARY KEY, name TEXT NOT NULL);
CREATE FUNCTION app.fn_widget_pk(p_name TEXT) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_pk BIGINT;
BEGIN
    SELECT pk_widget INTO v_pk FROM app.tb_widget WHERE name = p_name;
    RETURN v_pk;
END;
$$;
"""

#: A trigger function cannot be checked without the relation it fires on, and
#: asking for one without it raises `missing trigger relation` — which, in a
#: single query over every routine, would take the whole analysis down with it.
WITH_TRIGGER = (
    CLEAN
    + """CREATE FUNCTION app.fn_upper() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.name := upper(NEW.name);
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_upper BEFORE INSERT ON app.tb_widget
FOR EACH ROW EXECUTE FUNCTION app.fn_upper();
"""
)


#: A body that names a relation without its schema. It resolves at run time
#: through ``search_path`` and nowhere else, so the analyser has to be told the
#: same one the application uses or it reports a relation that is really there.
UNQUALIFIED = """CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE app.tb_widget (pk_widget BIGINT PRIMARY KEY, name TEXT NOT NULL);
CREATE FUNCTION app.fn_count() RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_n BIGINT;
BEGIN
    SELECT count(*) INTO v_n FROM tb_widget;
    RETURN v_n;
END;
$$;
"""


@pytest.fixture(scope="session")
def check_server() -> str:
    """A server carrying ``plpgsql_check``, or a skip naming what is missing."""
    url = plpgsql_check_url()
    if url is None:
        pytest.skip(
            "no server carrying plpgsql_check: set CONFITURE_TEST_DB_URL to one "
            "(the extension is in no stock PostgreSQL)"
        )
    return url


def _databases(url: str) -> set[str]:
    with psycopg.connect(url) as connection:
        return {row[0] for row in connection.execute("SELECT datname FROM pg_database")}


class TestTheSeam:
    def test_a_clean_schema_yields_no_diagnosis(self, check_server: str) -> None:
        assert bodies.diagnose(check_server, CLEAN) == []

    def test_the_analyser_reaches_a_routine_the_ddl_created(self, check_server: str) -> None:
        found = bodies.diagnose(check_server, REPRODUCTION)

        assert [d.identity for d in found] == ["app.fn_widget_pk(text)"]

    def test_postgresql_s_own_diagnosis_is_carried_verbatim(self, check_server: str) -> None:
        """confiture does not paraphrase: the SQLSTATE and the message are PostgreSQL's."""
        found = bodies.diagnose(check_server, REPRODUCTION)

        assert found[0].sqlstate == "42804"
        assert "type" in found[0].message

    def test_the_line_is_counted_in_the_body_s_own_frame(self, check_server: str) -> None:
        """``plpgsql_check`` numbers from the body's first line, not the file's."""
        found = bodies.diagnose(check_server, REPRODUCTION)

        assert found[0].body_line == 5

    def test_a_trigger_function_does_not_abort_the_analysis(self, check_server: str) -> None:
        """One query over every routine must survive the one kind that needs a relation."""
        assert bodies.diagnose(check_server, WITH_TRIGGER) == []

    def test_the_scratch_database_is_gone_afterwards(self, check_server: str) -> None:
        before = _databases(check_server)

        bodies.diagnose(check_server, REPRODUCTION)

        assert _databases(check_server) == before


class TestTheSearchPathTheApplicationUses:
    """``lint.search_path`` is the one the analyser is given, for the same reason
    ``build_003`` reads it: an unqualified name means nothing without it."""

    def test_an_unqualified_name_does_not_resolve_without_one(self, check_server: str) -> None:
        found = bodies.diagnose(check_server, UNQUALIFIED)

        assert [d.sqlstate for d in found] == ["42P01"]

    def test_the_configured_search_path_resolves_it(self, check_server: str) -> None:
        assert bodies.diagnose(check_server, UNQUALIFIED, search_path=["app"]) == []
