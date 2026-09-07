"""``migrate diff --from … --to <artifact> --generate`` closes spec → migration (issue #196).

The desired state is a FraiseQL ``compile --emit-ddl`` artifact — a directory of
DDL files — or the same text on stdin; the current state is a schema file or the
configured database. No hand-authored target SQL anywhere.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "desired_state" / "emit_ddl"
USER_ONLY = (FIXTURE / "user.sql").read_text()


def test_generate_from_an_emit_ddl_directory(tmp_path: Path) -> None:
    current = tmp_path / "current.sql"
    current.write_text(USER_ONLY)
    migrations = tmp_path / "migrations"

    result = runner.invoke(
        app,
        [
            "migrate",
            "diff",
            "--from",
            str(current),
            "--to",
            str(FIXTURE),
            "--generate",
            "--name",
            "add_posts",
            "--migrations-dir",
            str(migrations),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source"] == {"kind": "sql", "path": str(FIXTURE)}
    assert payload["migration_generated"] is True
    generated = migrations / payload["migration_file"]
    assert generated.exists()
    body = generated.read_text()
    assert "tb_post" in body and "tb_user" not in body


def test_dash_reads_the_artifact_from_stdin(tmp_path: Path) -> None:
    current = tmp_path / "current.sql"
    current.write_text(USER_ONLY)
    artifact = "".join(p.read_text() for p in sorted(FIXTURE.glob("*.sql")))

    result = runner.invoke(
        app,
        ["migrate", "diff", "--from", str(current), "--to", "-", "--format", "json"],
        input=artifact,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source"] == {"kind": "sql", "path": "-"}
    assert [c["type"] for c in payload["changes"]] == ["ADD_TABLE"]


def test_positional_form_still_works_and_names_its_source(tmp_path: Path) -> None:
    current = tmp_path / "current.sql"
    current.write_text(USER_ONLY)
    target = tmp_path / "target.sql"
    target.write_text("".join(p.read_text() for p in sorted(FIXTURE.glob("*.sql"))))

    result = runner.invoke(app, ["migrate", "diff", str(current), str(target), "--format", "json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["source"] == {"kind": "sql", "path": str(target)}


def test_from_and_to_cannot_mix_with_the_positional_form(tmp_path: Path) -> None:
    current = tmp_path / "current.sql"
    current.write_text(USER_ONLY)

    result = runner.invoke(
        app,
        ["migrate", "diff", str(current), str(current), "--to", str(FIXTURE), "--format", "json"],
    )

    assert result.exit_code == 5, result.output


@pytest.mark.integration
def test_from_db_diffs_the_configured_database(
    clean_test_db: psycopg.Connection, test_db_url: str, tmp_path: Path
) -> None:
    with clean_test_db.cursor() as cur:
        cur.execute(USER_ONLY)
    clean_test_db.commit()
    config = tmp_path / "confiture.yaml"
    config.write_text(f"name: test\ndatabase_url: {test_db_url}\n")

    result = runner.invoke(
        app,
        [
            "migrate",
            "diff",
            "--from",
            "db",
            "--to",
            str(FIXTURE),
            "--config",
            str(config),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [(c["type"], "tb_post" in c["details"]) for c in payload["changes"]] == [
        ("ADD_TABLE", True)
    ]
    assert payload["source"] == {"kind": "sql", "path": str(FIXTURE)}
