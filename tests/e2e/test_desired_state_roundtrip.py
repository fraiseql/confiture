"""The desired-state round trip: current schema, artifact, migration, preflight, apply, no drift.

``fraiseql compile --emit-ddl`` writes the schema the application wants; the
database carries the schema it has. What makes the artifact useful is the
round trip a deployer runs: diff the two, generate the migration, certify it
with preflight, apply it, and find nothing left to migrate. Every step here is
the CLI call the deployer would make, against the local test database.

The artifact indexes ``tv_product``, a relation the application's own schema
declares and the artifact does not. Diffed alone it is refused (``DIFFER_406``):
a desired state is whole, and one without ``tv_product`` would drop it. The
deployer composes the artifact into the tree that declares it.
"""

import json
import shutil
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


#: The relation the artifact indexes, which the application's own schema declares.
TV_PRODUCT = "CREATE TABLE tv_product (id INTEGER NOT NULL, data JSONB NOT NULL);\n"


def _database(connection: psycopg.Connection, url: str, tmp_path: Path) -> Path:
    """The database carries one of the artifact's two tables, and the application's own."""
    with connection.cursor() as cur:
        cur.execute((ARTIFACT / "user.sql").read_text())
        cur.execute(TV_PRODUCT)
    connection.commit()
    config = tmp_path / "local.yaml"
    config.write_text(f"name: test\ndatabase_url: {url}\n")
    return config


def test_the_artifact_alone_is_refused(
    clean_test_db: psycopg.Connection, test_db_url: str, tmp_path: Path
) -> None:
    config = _database(clean_test_db, test_db_url, tmp_path)

    result = runner.invoke(
        app,
        ["migrate", "diff", "--from", "db", "--to", str(ARTIFACT), "--config", str(config),
         "--format", "json"],
    )  # fmt: skip

    assert result.exit_code == 5, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "DIFFER_406"
    assert "tv_product" in error["message"]


def test_round_trip_leaves_nothing_to_migrate(
    clean_test_db: psycopg.Connection, test_db_url: str, tmp_path: Path
) -> None:
    config = _database(clean_test_db, test_db_url, tmp_path)
    composed = tmp_path / "schema"
    shutil.copytree(ARTIFACT, composed)
    (composed / "10_tv_product.sql").write_text(TV_PRODUCT)
    migrations = tmp_path / "migrations"

    _invoke(
        "migrate", "diff", "--from", "db", "--to", str(composed), "--config", str(config),
        "--generate", "--name", "adopt_post", "--migrations-dir", str(migrations),
    )  # fmt: skip
    written = sorted(p.name for p in migrations.iterdir())
    assert [n.split("_", 1)[1] for n in written] == ["adopt_post.down.sql", "adopt_post.up.sql"]
    up = (migrations / written[1]).read_text()
    assert (
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tv_product_name_fr ON public.tv_product" in up
    )

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

    drift = _invoke("drift", "--schema", str(composed), "--config", str(config), "--format", "json")
    report = json.loads(drift.stdout)
    assert report["has_drift"] is False, report["drift_items"]
