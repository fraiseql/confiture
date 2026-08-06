"""DB-refined preflight against a real database (issue #199, cycle 6).

`ALTER TABLE … ALTER COLUMN … TYPE bigint` names the target and never the source,
so the direction of a type change is knowable only from the database being
migrated. `--against` points at a copy of that schema, which makes it the honest
place to read the current type from — before the replay, so it describes the
schema being migrated *from*.

The static path must be untouched: without a reachable target, the same
migrations must produce the same tier-less entry they always did.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.schema_facts import collect_schema_facts

pytestmark = pytest.mark.integration


@pytest.fixture
def target_schema(clean_test_db: psycopg.Connection) -> psycopg.Connection:
    """A table whose column types the preflight target will report."""
    with clean_test_db.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS tb_widget CASCADE")
        cur.execute(
            "CREATE TABLE tb_widget ("
            "  id bigint PRIMARY KEY,"
            "  label varchar(50) NOT NULL,"
            "  quantity integer NOT NULL"
            ")"
        )
    clean_test_db.commit()
    return clean_test_db


def _preflight(migrations: Path, dsn: str) -> dict:
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "preflight",
            "--migrations-dir",
            str(migrations),
            "--against",
            dsn,
            "--format",
            "json",
        ],
    )
    assert result.exit_code in (0, 7), result.output
    return json.loads(result.stdout)


def _entry(payload: dict, kind: str) -> dict:
    matches = [c for c in payload["change_set"]["changes"] if c["kind"] == kind]
    assert matches, payload["change_set"]
    return matches[0]


def test_collect_schema_facts_reads_types_and_version(
    target_schema: psycopg.Connection,
) -> None:
    facts = collect_schema_facts(target_schema)

    assert facts.column_type("public.tb_widget.id") == "bigint"
    assert facts.column_type("public.tb_widget.label") == "character varying(50)"
    assert facts.server_version is not None
    assert facts.server_version >= 9


def test_narrowing_is_irreversible_against_a_real_target(
    target_schema: psycopg.Connection, test_db_url: str, tmp_path: Path
) -> None:
    """`bigint`→`integer` loses data; the tier must say so."""
    migrations = tmp_path / "narrow"
    migrations.mkdir()
    (migrations / "20260806120000_narrow.up.sql").write_text(
        "ALTER TABLE tb_widget ALTER COLUMN id TYPE integer;\n"
    )
    (migrations / "20260806120000_narrow.down.sql").write_text(
        "ALTER TABLE tb_widget ALTER COLUMN id TYPE bigint;\n"
    )

    entry = _entry(_preflight(migrations, test_db_url), "alter_column_type")
    assert entry["tier"] == "irreversible"
    assert "narrowing" in entry["detail"]


def test_widening_without_a_rewrite_is_reversible_against_a_real_target(
    target_schema: psycopg.Connection, test_db_url: str, tmp_path: Path
) -> None:
    """`varchar(50)`→`text` is binary coercible: safe, and no heap rewrite."""
    migrations = tmp_path / "widen"
    migrations.mkdir()
    (migrations / "20260806120000_widen.up.sql").write_text(
        "ALTER TABLE tb_widget ALTER COLUMN label TYPE text;\n"
    )
    (migrations / "20260806120000_widen.down.sql").write_text(
        "ALTER TABLE tb_widget ALTER COLUMN label TYPE varchar(50);\n"
    )

    entry = _entry(_preflight(migrations, test_db_url), "alter_column_type")
    assert entry["tier"] == "reversible"
    assert "no rewrite" in entry["detail"]


def test_static_path_is_unchanged_without_a_target(tmp_path: Path) -> None:
    """No connection ⇒ the honest tier-less entry, exactly as before #199."""
    migrations = tmp_path / "static"
    migrations.mkdir()
    (migrations / "20260806120000_narrow.up.sql").write_text(
        "ALTER TABLE tb_widget ALTER COLUMN id TYPE integer;\n"
    )
    (migrations / "20260806120000_narrow.down.sql").write_text(
        "ALTER TABLE tb_widget ALTER COLUMN id TYPE bigint;\n"
    )

    result = CliRunner().invoke(
        app,
        ["migrate", "preflight", "--migrations-dir", str(migrations), "--format", "json"],
    )
    payload = json.loads(result.stdout)
    entry = _entry(payload, "alter_column_type")
    assert "tier" not in entry
