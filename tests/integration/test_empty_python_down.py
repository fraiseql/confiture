"""A Python migration whose ``down()`` does nothing is refused, not run (#754).

``migrate down`` used to run the no-op ``down()``, delete the ledger row and report
success: the schema kept what the migration made, and the ledger said it was gone.
"""

from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

pytestmark = pytest.mark.integration


def _write(migrations: Path, down: str) -> None:
    (migrations / "001_add_t.up.sql").write_text("CREATE TABLE t (id int PRIMARY KEY);")
    (migrations / "001_add_t.down.sql").write_text("DROP TABLE t;")
    (migrations / "002_add_u.py").write_text(
        "from confiture.models.migration import Migration\n\n\n"
        "class AddU(Migration):\n    version = '002'\n    name = 'add_u'\n\n"
        "    def up(self):\n        self.execute('ALTER TABLE t ADD COLUMN u int')\n\n"
        f"    def down(self):\n        {down}\n"
    )


@pytest.fixture
def migrations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    directory = tmp_path / "migrations"
    directory.mkdir()
    return directory


def _cli(migrations: Path, database: str, *args: str) -> tuple[int, str]:
    result = CliRunner().invoke(
        app, ["migrate", *args, "--migrations-dir", str(migrations), "-d", database, "--no-config"]
    )
    return result.exit_code, result.output


def _state(database: str) -> tuple[list[str], bool]:
    with psycopg.connect(database) as conn:
        versions = [r[0] for r in conn.execute("SELECT version FROM tb_confiture ORDER BY version")]
        column = conn.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = 't' AND column_name = 'u'"
        ).fetchone()
    return versions, column == (1,)


@pytest.fixture
def applied_empty(migrations: Path, fresh_database: str) -> str:
    _write(migrations, "pass")
    code, out = _cli(migrations, fresh_database, "up")
    assert code == 0, out
    return fresh_database


@pytest.mark.parametrize(
    "command",
    [("down",), ("down", "--dry-run"), ("down-to", "001")],
    ids=["down", "dry-run", "down-to"],
)
def test_rolling_back_an_empty_down_is_refused(
    migrations: Path, applied_empty: str, command: tuple[str, ...]
) -> None:
    code, out = _cli(migrations, applied_empty, *command)

    assert code == 8, out  # ROLLBACK_600
    assert "002" in out
    assert _state(applied_empty) == (["001", "002"], True)


def test_require_reversible_refuses_an_empty_down(migrations: Path, fresh_database: str) -> None:
    _write(migrations, "pass")

    code, out = _cli(migrations, fresh_database, "up", "--require-reversible")

    assert code != 0, out
    assert "002" in out
    with psycopg.connect(fresh_database) as conn:
        assert conn.execute("SELECT to_regclass('t')").fetchone() == (None,)


def test_a_down_with_statements_still_rolls_back(migrations: Path, fresh_database: str) -> None:
    _write(migrations, "self.execute('ALTER TABLE t DROP COLUMN u')")
    assert _cli(migrations, fresh_database, "up", "--require-reversible")[0] == 0

    code, out = _cli(migrations, fresh_database, "down")

    assert code == 0, out
    assert _state(fresh_database) == (["001"], False)
