"""The desired-state round trip: current schema, artifact, migration, preflight, apply, no drift.

``fraiseql compile --emit-ddl`` writes the schema the application wants; the
database carries the schema it has. What makes the artifact useful is the
round trip a deployer runs: diff the two, generate the migration, certify it
with preflight, apply it, and find nothing left to migrate. Every step here is
the CLI call the deployer would make, against the local test database.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
from typer.testing import CliRunner

from confiture.cli.main import app

ARTIFACT = Path(__file__).parent.parent / "fixtures" / "desired_state" / "emit_ddl"

runner = CliRunner()


def _invoke(*args: str):
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, f"{' '.join(args[:2])} exited {result.exit_code}: {result.output}"
    return result


def test_round_trip_leaves_nothing_to_migrate(
    clean_test_db: psycopg.Connection, test_db_url: str, tmp_path: Path
) -> None:
    # The database already carries one of the artifact's two tables.
    with clean_test_db.cursor() as cur:
        cur.execute((ARTIFACT / "user.sql").read_text())
    clean_test_db.commit()
    config = tmp_path / "local.yaml"
    config.write_text(f"name: test\ndatabase_url: {test_db_url}\n")
    migrations = tmp_path / "migrations"

    _invoke(
        "migrate", "diff", "--from", "db", "--to", str(ARTIFACT), "--config", str(config),
        "--generate", "--name", "adopt_post", "--migrations-dir", str(migrations),
    )  # fmt: skip
    written = sorted(p.name for p in migrations.iterdir())
    assert [n.split("_", 1)[1] for n in written] == ["adopt_post.down.sql", "adopt_post.up.sql"]

    preflight = _invoke(
        "migrate", "preflight", "--migrations-dir", str(migrations), "--config", str(config),
        "--format", "json",
    )  # fmt: skip
    payload = json.loads(preflight.stdout)
    assert payload["ok"] and payload["window_safe"], payload["issues"]
    assert {change["tier"] for change in payload["change_set"]["changes"]} == {"additive"}, payload[
        "change_set"
    ]

    _invoke("migrate", "up", "--migrations-dir", str(migrations), "--config", str(config))

    drift = _invoke("drift", "--schema", str(ARTIFACT), "--config", str(config), "--format", "json")
    report = json.loads(drift.stdout)
    assert report["has_drift"] is False, report["drift_items"]
