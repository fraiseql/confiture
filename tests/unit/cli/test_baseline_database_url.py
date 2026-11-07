"""``migrate baseline --database-url`` (#813): the target taken as its siblings take it.

``migrate up``, ``current`` and ``down-to`` resolve their database under the #152
precedence; ``baseline`` read only ``--config``, so a deploy that names its target by
URL had to write a config file for this one command.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.unit._doubles import migrator_double
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()
URL = "postgresql://deploy@db.internal/app"


@pytest.fixture
def opened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Any]]:
    """The configurations ``baseline`` opened a connection with, in a project with no config."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    (tmp_path / "db" / "migrations" / "001_first.up.sql").write_text("SELECT 1;\n")
    seen: list[Any] = []

    @contextmanager
    def _open(config: Any) -> Iterator[object]:
        seen.append(config)
        yield object()

    first = tmp_path / "db/migrations/001_first.up.sql"
    with (
        patch("confiture.cli.commands.migrate.baseline.open_connection", _open),
        patch(
            "confiture.core.migrator.Migrator",
            return_value=migrator_double(
                initialize=None, get_applied_versions=[], find_migration_files=[first]
            ),
        ),
    ):
        yield seen


def test_the_flag_names_the_target(opened: list[Any]) -> None:
    result = runner.invoke(
        app,
        ["migrate", "baseline", "--through", "001", "--database-url", URL, "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert [c["database_url"] for c in opened] == [URL]


def test_the_canonical_variable_names_the_target(
    opened: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no config file, ``CONFITURE_DATABASE_URL`` is the target (#152, step 5)."""
    monkeypatch.setenv("CONFITURE_DATABASE_URL", URL)
    result = runner.invoke(app, ["migrate", "baseline", "--through", "001", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert [c["database_url"] for c in opened] == [URL]


def test_an_explicit_config_and_the_canonical_variable_are_refused(
    opened: list[Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two explicit sources fail loud (#152, step 3): the context is read without ``ctx``."""
    monkeypatch.setenv("CONFITURE_DATABASE_URL", URL)
    config = tmp_path / "prod.yaml"
    config.write_text("database_url: postgresql://localhost/other\n")
    result = runner.invoke(
        app, ["migrate", "baseline", "--through", "001", "--config", str(config), "--dry-run"]
    )
    assert result.exit_code == 5, result.output
    assert opened == []


def test_a_malformed_flag_is_refused_before_connecting(opened: list[Any]) -> None:
    result = runner.invoke(
        app,
        ["migrate", "baseline", "--through", "001", "--database-url", "mysql://u:pw@h/db"],
    )
    assert result.exit_code == 5, result.output
    assert opened == []
    assert "pw" not in result.output.replace("postgres", "")
