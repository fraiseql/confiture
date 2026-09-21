"""``confiture migrate verify-checksums``, run by its command line against a real ledger.

It is the callable behind the top-level ``verify-checksums``, registered a second
time under ``migrate``, where users look for it (#311). The unit tests pin that
the two names share one option list. This file pins that the name under
``migrate`` does the job against a database: two migrations are applied with
``migrate up``, which records their checksums. A clean tree then verifies, a file
edited after it was applied is reported as a mismatch at exit ``FINDINGS``, the
top-level name reports the same thing, and ``--fix`` re-records exactly that
file.

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
from confiture.error_codes import FINDINGS

pytestmark = pytest.mark.integration

runner = CliRunner()

_CREATE = "20260101000000_create_gizmos"
_ADD = "20260102000000_add_label"
_EDITED = Path("db/migrations") / f"{_ADD}.up.sql"


@pytest.fixture
def applied(tmp_path: Path, fresh_database: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """A project whose two migrations ``migrate up`` has applied; the database URL."""
    migrations = tmp_path / "db" / "migrations"
    migrations.mkdir(parents=True)
    (tmp_path / "db" / "schema").mkdir()
    (migrations / f"{_CREATE}.up.sql").write_text("CREATE TABLE gizmos (id INT);\n")
    (migrations / f"{_CREATE}.down.sql").write_text("DROP TABLE gizmos;\n")
    (migrations / f"{_ADD}.up.sql").write_text("ALTER TABLE gizmos ADD COLUMN label TEXT;\n")
    (migrations / f"{_ADD}.down.sql").write_text("ALTER TABLE gizmos DROP COLUMN label;\n")
    (tmp_path / "confiture.yaml").write_text(
        yaml.safe_dump(
            {"name": "test", "database_url": fresh_database, "include_dirs": ["db/schema"]}
        )
    )
    monkeypatch.chdir(tmp_path)
    up = runner.invoke(
        app, ["migrate", "up", "-c", "confiture.yaml", "--migrations-dir", "db/migrations"]
    )
    assert up.exit_code == 0, up.output
    return fresh_database


def _verify(*command: str, fix: bool = False) -> tuple[int, dict]:
    argv = [*command, "-c", "confiture.yaml", "--migrations-dir", "db/migrations"]
    result = runner.invoke(app, [*argv, "--format", "json", *(["--fix"] if fix else [])])
    return result.exit_code, json.loads(result.stdout)


def _stored_checksum(url: str, version: str) -> str:
    with psycopg.connect(url) as conn:
        row = conn.execute(
            "SELECT checksum FROM tb_confiture WHERE version = %s", (version,)
        ).fetchone()
    assert row is not None
    return row[0]


def test_an_untouched_tree_verifies(applied: str) -> None:
    result = runner.invoke(
        app,
        [
            "migrate",
            "verify-checksums",
            "-c",
            "confiture.yaml",
            "--migrations-dir",
            "db/migrations",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert (payload["ok"], payload["command"]) == (True, "migrate verify-checksums")
    assert (payload["summary"]["checked"], payload["summary"]["mismatched"]) == (2, 0)
    assert payload["issues"] == []


def test_a_file_edited_after_it_was_applied_is_a_mismatch(applied: str) -> None:
    _EDITED.write_text("ALTER TABLE gizmos ADD COLUMN label VARCHAR(10);\n")

    code, payload = _verify("migrate", "verify-checksums")

    assert code == FINDINGS
    assert payload["ok"] is False
    assert (payload["summary"]["checked"], payload["summary"]["mismatched"]) == (2, 1)
    (issue,) = payload["issues"]
    assert (issue["code"], issue["migration"], issue["file"]) == (
        "CHECKSUM_MISMATCH",
        "20260102000000",
        str(_EDITED),
    )
    assert issue["details"]["expected"] == _stored_checksum(applied, "20260102000000")
    assert issue["details"]["actual"] != issue["details"]["expected"]


def test_the_name_under_migrate_reports_what_the_top_level_name_reports(applied: str) -> None:
    _EDITED.write_text("ALTER TABLE gizmos ADD COLUMN label VARCHAR(10);\n")

    under_migrate = runner.invoke(
        app,
        [
            "migrate",
            "verify-checksums",
            "-c",
            "confiture.yaml",
            "--migrations-dir",
            "db/migrations",
            "--format",
            "json",
        ],
    )
    top_level = runner.invoke(
        app,
        [
            "verify-checksums",
            "-c",
            "confiture.yaml",
            "--migrations-dir",
            "db/migrations",
            "--format",
            "json",
        ],
    )

    assert under_migrate.exit_code == top_level.exit_code == FINDINGS
    ours, theirs = json.loads(under_migrate.stdout), json.loads(top_level.stdout)
    assert (ours.pop("command"), theirs.pop("command")) == (
        "migrate verify-checksums",
        "verify-checksums",
    )
    assert ours == theirs


def test_fix_re_records_the_edited_file_and_only_that_one(applied: str) -> None:
    untouched = _stored_checksum(applied, "20260101000000")
    _EDITED.write_text("ALTER TABLE gizmos ADD COLUMN label VARCHAR(10);\n")
    _, before = _verify("migrate", "verify-checksums")

    code, fixed = _verify("migrate", "verify-checksums", fix=True)

    assert code == 0
    assert fixed["fixed"] == 1
    assert _stored_checksum(applied, "20260102000000") == before["issues"][0]["details"]["actual"]
    assert _stored_checksum(applied, "20260101000000") == untouched
    assert _verify("migrate", "verify-checksums")[0] == 0
