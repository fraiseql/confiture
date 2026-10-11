"""``migrate preflight --against`` says what failed, and only a connection failure is one (#722).

A pending migration ``migrate up`` would refuse to load (no ``.down.sql``) used to
end the run as ``CONFIG_006`` "Connection to --against URL failed", exit 3: a deploy
tool reads that as "database unreachable". It is that migration's replay failure;
the rest of the pending set is still replayed.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

pytestmark = pytest.mark.integration

_NO_DOWN = "20260401000001_add_t"
_OK = "20260401000002_add_u"


@pytest.fixture
def migrations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / f"{_NO_DOWN}.up.sql").write_text("CREATE TABLE t (id int);")
    (directory / f"{_OK}.up.sql").write_text("CREATE TABLE u (id int);")
    (directory / f"{_OK}.down.sql").write_text("DROP TABLE u;")
    return directory


def _preflight(migrations: Path, database: str, *args: str) -> tuple[int, str]:
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "preflight",
            "--migrations-dir",
            str(migrations),
            "--against",
            database,
            "-d",
            database,
            "--no-config",
            *args,
        ],
    )
    return result.exit_code, result.stdout


@pytest.mark.parametrize("scope", [("--scope", "pending"), ("--since", "0")])
def test_a_migration_with_no_down_is_its_replay_failure(
    migrations: Path, fresh_database: str, scope: tuple[str, str]
) -> None:
    code, out = _preflight(migrations, fresh_database, *scope, "--format", "json")
    payload = json.loads(out)

    assert code == 7, payload
    assert "error" not in payload
    replay = [i for i in payload["issues"] if i["code"] == "PFLIGHT_REPLAY_FAILED"]
    assert [i["migration"] for i in replay] == ["20260401000001"]
    assert "no matching .down.sql" in replay[0]["details"]["error"]
    assert payload["summary"]["migrations_checked"] == 2


def test_the_text_report_does_not_call_it_a_connection_failure(
    migrations: Path, fresh_database: str
) -> None:
    code, out = _preflight(migrations, fresh_database, "--scope", "pending")

    assert code == 7, out
    assert "Connection to --against URL failed" not in out
