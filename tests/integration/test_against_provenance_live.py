"""``migrate preflight --against``: an ``IF NOT EXISTS`` create of a relation the database lacks (#692).

The ``--against`` database says which relations exist and where an unqualified
``CREATE`` lands. A ``CREATE TABLE IF NOT EXISTS t`` of a ``t`` it does not hold
— once the pending migrations before it are folded — creates ``t`` new, and an
index on it reaches no session: the index is replica-safe and additive. A ``t``
it holds, a pending rename onto the name, or a statement the fold cannot read
before the create keeps the index flagged.
"""

import json
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core import live_catalog
from confiture.core.schema_facts import collect_schema_facts

pytestmark = pytest.mark.integration

CREATE = "CREATE TABLE IF NOT EXISTS tb_note (id int, title text);\n"
INDEX = "CREATE INDEX ix_note_title ON tb_note (title);\n"


def _run(url: str, *statements: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        for statement in statements:
            conn.execute(statement)


def _migrations(tmp_path: Path, *ups: str) -> Path:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for number, up in enumerate(ups, start=1):
        stem = f"2026100100000{number}_m{number}"
        (migrations / f"{stem}.up.sql").write_text(up)
        (migrations / f"{stem}.down.sql").write_text("SELECT 1;\n")
    return migrations


def _preflight(migrations: Path, against: str) -> dict:
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "preflight",
            "--migrations-dir",
            str(migrations),
            "--against",
            against,
            "--format",
            "json",
        ],
    )
    # 0 = clean, 7 = a preflight finding; the issues are the subject here.
    assert result.exit_code in (0, 7), result.output
    return json.loads(result.stdout)


def _index(payload: dict) -> dict:
    [entry] = [c for c in payload["change_set"]["changes"] if c["kind"] == "create_index"]
    return entry


def _flagged(payload: dict) -> bool:
    return any(i["code"] == "PFLIGHT_REPLICA_CREATE_INDEX" for i in payload["issues"])


@pytest.fixture(autouse=True)
def _no_ambient_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)


def test_a_table_the_database_holds_stays_flagged(fresh_database: str, tmp_path: Path) -> None:
    _run(fresh_database, "CREATE TABLE tb_note (id int, title text)")

    payload = _preflight(_migrations(tmp_path, CREATE + INDEX), fresh_database)

    assert _flagged(payload)
    assert payload["window_safe"] is False
    assert _index(payload)["tier"] == "lock_risky"


def test_a_table_the_database_lacks_is_created(fresh_database: str, tmp_path: Path) -> None:
    payload = _preflight(_migrations(tmp_path, CREATE + INDEX), fresh_database)

    assert not _flagged(payload)
    assert payload["window_safe"] is True
    index = _index(payload)
    assert index["tier"] == "additive"
    assert index["detail"] == (
        "CREATE INDEX — on a relation this migration creates (the database does not hold it)"
    )


def test_a_pending_rename_onto_the_name_holds_it(fresh_database: str, tmp_path: Path) -> None:
    _run(fresh_database, "CREATE TABLE tb_big (id int, title text)")

    migrations = _migrations(tmp_path, "ALTER TABLE tb_big RENAME TO tb_note;\n", CREATE + INDEX)
    payload = _preflight(migrations, fresh_database)

    assert _flagged(payload)
    assert _index(payload)["tier"] == "lock_risky"


def test_a_pending_drop_frees_the_name(fresh_database: str, tmp_path: Path) -> None:
    _run(fresh_database, "CREATE TABLE tb_note (id int, title text)")

    migrations = _migrations(tmp_path, "DROP TABLE tb_note;\n", CREATE + INDEX)
    payload = _preflight(migrations, fresh_database)

    assert not _flagged(payload)
    assert _index(payload)["tier"] == "additive"


@pytest.mark.parametrize(
    "before",
    ["DO $$ BEGIN PERFORM 1; END $$;\n", "SET search_path = public;\n", "SELECT now();\n"],
)
def test_an_unreadable_statement_before_the_create_keeps_it_flagged(
    fresh_database: str, tmp_path: Path, before: str
) -> None:
    payload = _preflight(_migrations(tmp_path, before + CREATE + INDEX), fresh_database)

    assert _flagged(payload)
    assert payload["window_safe"] is False


def test_an_unqualified_name_lands_in_the_sessions_current_schema(
    fresh_database_factory, tmp_path: Path
) -> None:
    """``public.tb_note`` exists, but the session creates in ``app``: ``app.tb_note`` is new."""
    url = fresh_database_factory("confiture_t")
    _run(url, "CREATE SCHEMA app", "CREATE TABLE public.tb_note (id int, title text)")
    in_app = url + ("&" if "?" in url else "?") + "options=-csearch_path%3Dapp"

    payload = _preflight(_migrations(tmp_path, CREATE + INDEX), in_app)

    assert not _flagged(payload)
    assert _index(payload)["tier"] == "additive"


def test_the_live_reads(fresh_database: str) -> None:
    """Every relation of every kind is a name ``IF NOT EXISTS`` finds taken."""
    _run(
        fresh_database,
        "CREATE TABLE tb_a (id serial PRIMARY KEY)",
        "CREATE VIEW v_a AS SELECT id FROM tb_a",
        "CREATE SEQUENCE seq_a",
        "CREATE TYPE ty_a AS (c text)",
    )
    with psycopg.connect(fresh_database) as conn:
        names = live_catalog.relation_names(conn)
        assert live_catalog.current_schema(conn) == "public"
        facts = collect_schema_facts(conn)
    expected = {"tb_a", "tb_a_pkey", "tb_a_id_seq", "v_a", "seq_a", "ty_a"}
    assert {("public", name) for name in expected} <= names
    assert facts.relations == names
    assert facts.current_schema == "public"


TVIEW = "SELECT tviews.pg_tviews_create_or_replace('tv_note', 'SELECT id, title FROM tb_note');\n"
TVIEW_INDEX = "CREATE INDEX ix_tv_note_title ON tv_note (title);\n"


def test_a_tview_the_database_lacks_is_created_by_create_or_replace(
    fresh_database: str, tmp_path: Path
) -> None:
    """The spelling ``migrate diff --generate`` writes for a TVIEW (#786)."""
    _run(fresh_database, "CREATE TABLE tb_note (id int, title text)")

    payload = _preflight(_migrations(tmp_path, TVIEW + TVIEW_INDEX), fresh_database)

    assert not _flagged(payload)
    assert _index(payload)["tier"] == "additive"


def test_a_tview_the_database_holds_is_replaced_by_create_or_replace(
    fresh_database: str, tmp_path: Path
) -> None:
    _run(
        fresh_database,
        "CREATE TABLE tb_note (id int, title text)",
        "CREATE TABLE tv_note (id int, title text)",
    )

    payload = _preflight(_migrations(tmp_path, TVIEW + TVIEW_INDEX), fresh_database)

    assert _flagged(payload)
    assert _index(payload)["tier"] == "lock_risky"


def test_a_tview_an_earlier_pending_file_creates_is_held(
    fresh_database: str, tmp_path: Path
) -> None:
    _run(fresh_database, "CREATE TABLE tb_note (id int, title text)")

    payload = _preflight(_migrations(tmp_path, TVIEW, TVIEW + TVIEW_INDEX), fresh_database)

    assert _flagged(payload)
    assert _index(payload)["tier"] == "lock_risky"
