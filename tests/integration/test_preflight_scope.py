"""``migrate preflight --scope pending`` judges what a ledger has not applied (#687).

Migration A (applied) drops a column, which no replica window survives; B
(pending) adds a nullable one, which every window does. Judged whole, the
directory is not window-safe forever after A; judged as what is about to run,
it is. Confiture never narrows on its own: the default stays ``all``.
"""

import json
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

pytestmark = pytest.mark.integration

_A = "20260401000001_drop_note"
_B = "20260401000002_add_tag"


@pytest.fixture
def migrations(tmp_path: Path) -> Path:
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / f"{_A}.up.sql").write_text("ALTER TABLE tb_item DROP COLUMN note;")
    (directory / f"{_A}.down.sql").write_text("ALTER TABLE tb_item ADD COLUMN note text;")
    return directory


@pytest.fixture
def applied(migrations: Path, fresh_database: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """A database whose ledger holds A, with B written after it ran."""
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute("CREATE TABLE tb_item (id int PRIMARY KEY, note text)")
    result = CliRunner().invoke(
        app,
        ["migrate", "up", "--migrations-dir", str(migrations), "-d", fresh_database, "--no-config"],
    )
    assert result.exit_code == 0, result.output
    (migrations / f"{_B}.up.sql").write_text("ALTER TABLE tb_item ADD COLUMN tag text;")
    (migrations / f"{_B}.down.sql").write_text("ALTER TABLE tb_item DROP COLUMN tag;")
    return fresh_database


def _preflight(migrations: Path, *args: str) -> tuple[int, dict]:
    result = CliRunner().invoke(
        app,
        ["migrate", "preflight", "--migrations-dir", str(migrations), "--format", "json", *args],
    )
    return result.exit_code, json.loads(result.stdout)


def _versions(payload: dict) -> set[str]:
    return {change["migration"] for change in payload["change_set"]["changes"]}


def test_pending_judges_only_what_has_not_run(migrations: Path, applied: str) -> None:
    code, payload = _preflight(migrations, "--scope", "pending", "-d", applied, "--no-config")

    assert code == 0, payload
    assert payload["scope"] == "pending"
    assert payload["window_safe"] is True
    assert _versions(payload) == {"20260401000002"}
    assert payload["ledger"] == {"table": "tb_confiture", "exists": True}


def test_the_default_judges_the_whole_directory(migrations: Path, applied: str) -> None:
    _, payload = _preflight(migrations, "-d", applied, "--no-config")

    assert payload["scope"] == "all"
    assert payload["window_safe"] is False
    assert _versions(payload) == {"20260401000001", "20260401000002"}
    assert "ledger" not in payload


def test_the_canonical_environment_variable_is_a_source(
    migrations: Path, applied: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fraisier's call: ``CONFITURE_DATABASE_URL`` injected, ``--no-config``."""
    monkeypatch.setenv("CONFITURE_DATABASE_URL", applied)

    _, payload = _preflight(migrations, "--scope", "pending", "--no-config")

    assert payload["window_safe"] is True
    assert _versions(payload) == {"20260401000002"}


def test_pending_without_a_database_is_refused(
    migrations: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    code, payload = _preflight(migrations, "--scope", "pending")

    assert code == 5
    assert payload["error"]["code"] == "CONFIG_010"


def test_an_unreachable_ledger_is_a_connection_failure(
    migrations: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)

    code, payload = _preflight(
        migrations,
        "--scope",
        "pending",
        "-d",
        "postgresql://localhost/nonexistent",
        "--no-config",
    )

    assert code == 3
    assert payload["error"]["code"] == "CONFIG_006"


def test_a_database_with_no_ledger_has_everything_pending(
    migrations: Path, fresh_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)

    _, payload = _preflight(migrations, "--scope", "pending", "-d", fresh_database, "--no-config")

    assert payload["scope"] == "pending"
    assert payload["ledger"] == {"table": "tb_confiture", "exists": False}
    assert _versions(payload) == {"20260401000001"}


def test_a_ledger_only_in_another_schema_is_refused(
    migrations: Path, fresh_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reading it as missing would judge everything under a ``pending`` label."""
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA staging")
        conn.execute("CREATE TABLE staging.tb_confiture (version text)")

    code, payload = _preflight(
        migrations, "--scope", "pending", "-d", fresh_database, "--no-config"
    )

    assert code == 5
    assert payload["error"]["code"] == "CONFIG_015"
    assert "staging.tb_confiture" in payload["error"]["message"]


def test_since_and_pending_are_two_answers_to_one_question(migrations: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "preflight",
            "--migrations-dir",
            str(migrations),
            "--scope",
            "pending",
            "--since",
            "20260401000002",
        ],
    )

    assert result.exit_code == 2


def test_against_with_pending_reads_one_set(migrations: Path, applied: str) -> None:
    code, payload = _preflight(
        migrations, "--scope", "pending", "-d", applied, "--no-config", "--against", applied
    )

    assert code == 0, payload
    assert payload["scope"] == "pending"
    assert _versions(payload) == {"20260401000002"}
    assert payload["summary"]["migrations_checked"] == 1
