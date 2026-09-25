"""``confiture introspect``, run by its command line against a real database.

The command is how an agent learns a schema it cannot see, so each test compares
its output with the DDL the test ran: every table the filter admits, each column
with ``format_type``'s spelling, nullability and primary-key membership, and the
foreign-key graph read from both ends. JSON comes from the whole of stdout,
because a consumer parses the stream. YAML goes to ``--output``, and is read
back from that file.

The ``xfail`` test records a defect found while writing this file.

Every test runs in a database of its own.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app

pytestmark = pytest.mark.integration

runner = CliRunner()


@pytest.fixture
def database(fresh_database: str) -> str:
    """``tb_owner`` ← ``tb_pet`` in ``public``, an unprefixed ``audit_log``, and
    ``inv.tb_item`` referencing ``public.tb_owner`` from another schema."""
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE tb_owner ("
            " pk_owner BIGINT PRIMARY KEY, id UUID NOT NULL, name VARCHAR(50))"
        )
        conn.execute(
            "CREATE TABLE tb_pet ("
            " pk_pet BIGINT PRIMARY KEY,"
            " fk_owner BIGINT NOT NULL REFERENCES tb_owner (pk_owner),"
            " nickname TEXT)"
        )
        conn.execute("CREATE TABLE audit_log (event TEXT NOT NULL)")
        conn.execute("CREATE SCHEMA inv")
        conn.execute(
            "CREATE TABLE inv.tb_item ("
            " pk_item BIGINT PRIMARY KEY,"
            " fk_owner BIGINT REFERENCES public.tb_owner (pk_owner))"
        )
        conn.execute("CREATE TABLE inv.stock_log (qty INTEGER)")
    return fresh_database


def _tables(payload: dict) -> dict[str, dict]:
    return {table["name"]: table for table in payload["tables"]}


def _columns(table: dict) -> list[tuple[str, str, bool, bool]]:
    return [(c["name"], c["pg_type"], c["nullable"], c["is_primary_key"]) for c in table["columns"]]


def test_json_holds_the_tables_columns_and_foreign_keys(database: str) -> None:
    result = runner.invoke(app, ["introspect", "--db", database, "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert (payload["ok"], payload["command"], payload["schema"]) == (True, "introspect", "public")
    assert payload["database"] == database.rsplit("/", 1)[1]
    tables = _tables(payload)
    assert sorted(tables) == ["tb_owner", "tb_pet"]
    assert _columns(tables["tb_owner"]) == [
        ("pk_owner", "bigint", False, True),
        ("id", "uuid", False, False),
        ("name", "character varying(50)", True, False),
    ]
    assert _columns(tables["tb_pet"]) == [
        ("pk_pet", "bigint", False, True),
        ("fk_owner", "bigint", False, False),
        ("nickname", "text", True, False),
    ]
    assert tables["tb_pet"]["outbound_fks"] == [
        {
            "from_table": None,
            "to_table": "tb_owner",
            "via_column": "fk_owner",
            "on_column": "pk_owner",
        }
    ]
    assert tables["tb_owner"]["inbound_fks"] == [
        {
            "from_table": "tb_pet",
            "to_table": None,
            "via_column": "fk_owner",
            "on_column": "pk_owner",
        }
    ]
    assert tables["tb_owner"]["hints"] == {"surrogate_pk": "pk_owner", "natural_id": "id"}


def test_all_tables_admits_a_table_without_the_prefix(database: str) -> None:
    result = runner.invoke(app, ["introspect", "--db", database, "--all-tables", "--no-hints"])

    assert result.exit_code == 0, result.output
    tables = _tables(json.loads(result.stdout))
    assert sorted(tables) == ["audit_log", "tb_owner", "tb_pet"]
    assert _columns(tables["audit_log"]) == [("event", "text", False, False)]
    assert {name: table["hints"] for name, table in tables.items()} == dict.fromkeys(tables)


def test_yaml_for_another_schema_goes_to_the_output_file(database: str, tmp_path: Path) -> None:
    out = tmp_path / "inv.yaml"

    result = runner.invoke(
        app,
        ["introspect", "--db", database, "--schema", "inv", "--format", "yaml", "-o", str(out)],
    )

    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    payload = yaml.safe_load(out.read_text())
    assert payload["schema"] == "inv"
    tables = _tables(payload)
    assert sorted(tables) == ["tb_item"]
    assert _columns(tables["tb_item"]) == [
        ("pk_item", "bigint", False, True),
        ("fk_owner", "bigint", True, False),
    ]
    assert [(fk["via_column"], fk["on_column"]) for fk in tables["tb_item"]["outbound_fks"]] == [
        ("fk_owner", "pk_owner")
    ]


def test_a_key_into_another_schema_is_not_given_to_a_same_named_table(
    database: str,
) -> None:
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("CREATE TABLE inv.tb_owner (pk_owner BIGINT PRIMARY KEY)")

    result = runner.invoke(app, ["introspect", "--db", database, "--schema", "inv"])

    assert result.exit_code == 0, result.output
    assert _tables(json.loads(result.stdout))["tb_owner"]["inbound_fks"] == []
