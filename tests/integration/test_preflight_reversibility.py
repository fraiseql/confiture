"""What ``migrate preflight --format json`` says ``migrate down`` cannot undo (#754).

A deploy tool reads the pending set's preflight to decide whether a failed deploy
can be rolled back with ``migrate down`` or needs the full-database template. Each
test here is one of the payloads #754 captured, which said nothing.
"""

import json
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

pytestmark = pytest.mark.integration

_BASE = "001_add_t"


@pytest.fixture
def migrations(tmp_path: Path) -> Path:
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / f"{_BASE}.up.sql").write_text("CREATE TABLE t (id int PRIMARY KEY, v int);")
    (directory / f"{_BASE}.down.sql").write_text("DROP TABLE t;")
    return directory


@pytest.fixture
def applied(migrations: Path, fresh_database: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """A database whose ledger holds ``001``: what follows is the pending set."""
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = CliRunner().invoke(
        app,
        ["migrate", "up", "--migrations-dir", str(migrations), "-d", fresh_database, "--no-config"],
    )
    assert result.exit_code == 0, result.output
    with psycopg.connect(fresh_database) as conn:
        assert conn.execute("SELECT to_regclass('t')").fetchone() == ("t",)
    return fresh_database


def _preflight(migrations: Path, database: str, *args: str) -> tuple[int, dict]:
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "preflight",
            "--migrations-dir",
            str(migrations),
            "-d",
            database,
            "--no-config",
            "--scope",
            "pending",
            "--format",
            "json",
            *args,
        ],
    )
    return result.exit_code, json.loads(result.stdout)


def _codes(payload: dict, code: str) -> list[dict]:
    return [i for i in payload["issues"] if i["code"] == code]


@pytest.mark.parametrize("against", [False, True], ids=["static", "against"])
def test_an_irreversible_marker_reaches_the_wire_without_the_gate(
    migrations: Path, applied: str, against: bool
) -> None:
    (migrations / "002_overwrite_v.up.sql").write_text(
        "-- confiture:irreversible overwrites t.v\nUPDATE t SET v = 0;"
    )
    (migrations / "002_overwrite_v.down.sql").write_text("SELECT 1;")

    code, payload = _preflight(migrations, applied, *(["--against", applied] if against else []))

    assert code == 0, payload
    (marked,) = _codes(payload, "PFLIGHT_IRREVERSIBLE")
    assert marked["migration"] == "002"
    assert marked["file"] == "002_overwrite_v.up.sql"
    assert marked["severity"] == "info"
    assert marked["details"] == {"irreversible": ["overwrites t.v"]}
    assert not _codes(payload, "PFLIGHT_DESTRUCTIVE_GATED")
    assert payload["reversible"] is False


def _python(migrations: Path, down: str) -> None:
    (migrations / "002_add_u.py").write_text(
        "from confiture.models.migration import Migration\n\n\n"
        "class AddU(Migration):\n    version = '002'\n    name = 'add_u'\n\n"
        "    def up(self):\n        self.execute('ALTER TABLE t ADD COLUMN u int')\n\n"
        f"    def down(self):\n        {down}\n"
    )


@pytest.mark.parametrize("against", [False, True], ids=["static", "against"])
def test_a_python_down_that_is_pass_reaches_the_wire(
    migrations: Path, applied: str, against: bool
) -> None:
    _python(migrations, "pass")

    code, payload = _preflight(migrations, applied, *(["--against", applied] if against else []))

    assert code == 0, payload
    (empty,) = _codes(payload, "PFLIGHT_DOWN_EMPTY")
    assert (empty["migration"], empty["file"], empty["severity"]) == (
        "002",
        "002_add_u.py",
        "warning",
    )
    assert not _codes(payload, "PFLIGHT_MISSING_DOWN")
    assert [i["migration"] for i in _codes(payload, "PFLIGHT_REPLICA_UNCLASSIFIED")] == ["002"]
    assert payload["reversible"] is False


def test_a_python_down_with_statements_is_unverified(migrations: Path, applied: str) -> None:
    _python(migrations, "self.execute('ALTER TABLE t DROP COLUMN u')")

    code, payload = _preflight(migrations, applied, "--against", applied)

    assert code == 0, payload
    (unverified,) = _codes(payload, "PFLIGHT_DOWN_UNVERIFIED")
    assert unverified["migration"] == "002"
    assert unverified["details"] == {"down": "present"}


@pytest.mark.parametrize("against", [False, True], ids=["static", "against"])
def test_a_pending_set_down_can_undo_is_reversible(
    migrations: Path, applied: str, against: bool
) -> None:
    (migrations / "002_add_u.up.sql").write_text("ALTER TABLE t ADD COLUMN u int;")
    (migrations / "002_add_u.down.sql").write_text("ALTER TABLE t DROP COLUMN u;")

    code, payload = _preflight(migrations, applied, *(["--against", applied] if against else []))

    assert code == 0, payload
    assert payload["reversible"] is True
