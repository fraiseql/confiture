"""The destructive gate: a migration that loses data is applied only when the deployer says so.

The generator marks such a migration with ``-- confiture:destructive``;
``migrate up`` refuses it (exit 5, ``VALID_002``) unless ``--allow-destructive``
is given, and ``migrate preflight`` says the gate is there before anyone runs
``up``. Against the local test database.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

GATED_UP = (
    "-- confiture:destructive\n"
    "-- confiture:tier irreversible\n"
    "ALTER TABLE tb_user DROP COLUMN display_name;\n"
)
GATED_DOWN = "-- confiture:tier additive\nALTER TABLE tb_user ADD COLUMN display_name text;\n"


def _project(tmp_path: Path, test_db_url: str) -> tuple[Path, Path]:
    config = tmp_path / "local.yaml"
    config.write_text(f"name: test\ndatabase_url: {test_db_url}\n")
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "20260101000000_drop_display_name.up.sql").write_text(GATED_UP)
    (migrations / "20260101000000_drop_display_name.down.sql").write_text(GATED_DOWN)
    return config, migrations


def _has_display_name(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'tb_user' AND column_name = 'display_name'"
        )
        return cur.fetchone() is not None


def _seed(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE tb_user (id integer NOT NULL, display_name text)")
    conn.commit()


def test_up_refuses_a_gated_migration_without_the_flag(
    clean_test_db: psycopg.Connection, test_db_url: str, tmp_path: Path
) -> None:
    _seed(clean_test_db)
    config, migrations = _project(tmp_path, test_db_url)

    result = runner.invoke(
        app,
        ["migrate", "up", "--migrations-dir", str(migrations), "--config", str(config), "--format", "json"],
    )  # fmt: skip

    assert result.exit_code == 5, result.output
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "VALID_002", payload
    assert "20260101000000" in payload["error"]["message"]
    assert _has_display_name(clean_test_db)


def test_up_applies_a_gated_migration_with_the_flag(
    clean_test_db: psycopg.Connection, test_db_url: str, tmp_path: Path
) -> None:
    _seed(clean_test_db)
    config, migrations = _project(tmp_path, test_db_url)

    result = runner.invoke(
        app,
        ["migrate", "up", "--migrations-dir", str(migrations), "--config", str(config), "--allow-destructive"],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert not _has_display_name(clean_test_db)


def test_preflight_names_the_gate(
    clean_test_db: psycopg.Connection, test_db_url: str, tmp_path: Path
) -> None:
    _seed(clean_test_db)
    config, migrations = _project(tmp_path, test_db_url)

    result = runner.invoke(
        app,
        ["migrate", "preflight", "--migrations-dir", str(migrations), "--config", str(config), "--format", "json"],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    gated = [i for i in payload["issues"] if i["code"] == "PFLIGHT_DESTRUCTIVE_GATED"]
    assert [i["file"] for i in gated] == ["20260101000000_drop_display_name.up.sql"], payload[
        "issues"
    ]
    assert gated[0]["severity"] == "warning"
    assert "--allow-destructive" in gated[0]["actionable"]


CURRENT = "CREATE TABLE tb_user (id integer NOT NULL, display_name text);\n"
DESIRED = "CREATE TABLE tb_user (id integer NOT NULL);\n"


def _diff(tmp_path: Path, *extra: str) -> tuple[int, dict]:
    (tmp_path / "current.sql").write_text(CURRENT)
    (tmp_path / "desired.sql").write_text(DESIRED)
    result = runner.invoke(
        app,
        ["migrate", "diff", "--from", str(tmp_path / "current.sql"), "--to", str(tmp_path / "desired.sql"),
         "--generate", "--name", "drop_display_name", "--migrations-dir", str(tmp_path / "migrations"),
         "--config", str(tmp_path / "local.yaml"), "--format", "json", *extra],
    )  # fmt: skip
    return result.exit_code, json.loads(result.output)


def test_generation_is_gated_by_default(tmp_path: Path) -> None:
    code, payload = _diff(tmp_path)
    assert code == 0, payload
    assert payload["destructive_gate"] == "gated"
    up = tmp_path / "migrations" / payload["migration_file"]
    assert up.read_text().splitlines()[3] == "-- confiture:destructive"


def test_the_config_can_forbid_generation(tmp_path: Path) -> None:
    (tmp_path / "local.yaml").write_text("name: test\nmigration:\n  destructive: forbid\n")
    code, payload = _diff(tmp_path)
    assert code == 5, payload
    assert payload["error"]["code"] == "DIFFER_401"
    written = (
        list((tmp_path / "migrations").glob("*")) if (tmp_path / "migrations").exists() else []
    )
    assert written == []


def test_a_flag_overrides_the_config(tmp_path: Path) -> None:
    (tmp_path / "local.yaml").write_text("name: test\nmigration:\n  destructive: forbid\n")
    code, payload = _diff(tmp_path, "--allow-destructive")
    assert code == 0, payload
    assert payload["destructive_gate"] == "allow"
    up = tmp_path / "migrations" / payload["migration_file"]
    assert "confiture:destructive" not in up.read_text()


def test_the_two_flags_cannot_mix(tmp_path: Path) -> None:
    code, payload = _diff(tmp_path, "--allow-destructive", "--forbid-destructive")
    assert code == 5, payload
    assert payload["error"]["code"] == "VALID_001"
