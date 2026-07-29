"""#194: ``migrate validate`` git checks must honor ``--env``.

The drift / migration-accompaniment / unmigrated-bodies checks all build the
expected schema via ``GitSchemaBuilder(env)`` — but the CLI hardcoded
``env="local"`` at every call site, silently ignoring ``--env``. On projects
whose *local* environment includes seed data (e.g. ``COPY … FROM stdin``
blocks that no SQL parser accepts), that made ``--require-migration`` a
silent no-op: the pglast pass failed on the seed data, the sqlparse fallback
missed the DDL, and the gate reported "No DDL changes detected" forever.
Pointing the check at a DDL-only environment (``--env production``) is the
documented escape hatch — so the flag has to actually reach the checker.

Patch style mirrors ``test_validate_staged_routing.py``: the git-validation
functions are patched on their source module because ``migrate_validate``
imports them lazily.
"""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


@pytest.fixture
def captured_git_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    calls: dict[str, dict[str, Any]] = {}

    def fake_flags() -> object:
        return object()

    def fake_drift(**kwargs: Any) -> dict[str, Any]:
        calls["drift"] = kwargs
        return {"passed": True}

    def fake_accompaniment(**kwargs: Any) -> dict[str, Any]:
        calls["accompaniment"] = kwargs
        return {"is_valid": True}

    def fake_bodies(**kwargs: Any) -> dict[str, Any]:
        calls["bodies"] = kwargs
        return {"violations": []}

    monkeypatch.setattr("confiture.cli.git_validation.validate_git_flags_in_repo", fake_flags)
    monkeypatch.setattr("confiture.cli.git_validation.validate_git_drift", fake_drift)
    monkeypatch.setattr(
        "confiture.cli.git_validation.validate_migration_accompaniment", fake_accompaniment
    )
    monkeypatch.setattr("confiture.cli.git_validation.report_unmigrated_bodies", fake_bodies)
    return calls


def test_require_migration_passes_env_through(
    captured_git_calls: dict[str, dict[str, Any]],
) -> None:
    result = runner.invoke(
        app,
        ["migrate", "validate", "--require-migration", "--env", "production"],
    )
    assert result.exit_code == 0, result.output
    assert captured_git_calls["accompaniment"]["env"] == "production"


def test_require_migration_defaults_to_local_env(
    captured_git_calls: dict[str, dict[str, Any]],
) -> None:
    result = runner.invoke(app, ["migrate", "validate", "--require-migration"])
    assert result.exit_code == 0, result.output
    assert captured_git_calls["accompaniment"]["env"] == "local"


def test_check_drift_passes_env_through(
    captured_git_calls: dict[str, dict[str, Any]],
) -> None:
    result = runner.invoke(
        app,
        ["migrate", "validate", "--check-drift", "--env", "production"],
    )
    assert result.exit_code == 0, result.output
    assert captured_git_calls["drift"]["env"] == "production"


def test_list_unmigrated_bodies_passes_env_through(
    captured_git_calls: dict[str, dict[str, Any]],
) -> None:
    result = runner.invoke(
        app,
        ["migrate", "validate", "--list-unmigrated-bodies", "--env", "production"],
    )
    assert result.exit_code == 0, result.output
    assert captured_git_calls["bodies"]["env"] == "production"
