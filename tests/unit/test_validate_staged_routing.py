"""ARCH-L1: pin where ``migrate validate --staged`` actually routes.

The pre-Phase-03 code carried a dead ``target_ref = "HEAD" if not staged else
"HEAD"`` ternary for the drift and migration-accompaniment checks — both
branches were ``"HEAD"``, so ``--staged`` was a silent no-op there. The staged
index is only honored by the grant-accompaniment check (``staged_only=staged``).

These tests pin that contract: ``--staged`` reaches grant-accompaniment as
``staged_only=True``, while drift/accompaniment receive ``target_ref="HEAD"``
regardless. The git-validation functions are patched on their source module
(``confiture.cli.git_validation``) since ``migrate_validate`` imports them lazily.
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

    def fake_grant(**kwargs: Any) -> dict[str, Any]:
        calls["grant"] = kwargs
        return {"is_valid": True}

    monkeypatch.setattr("confiture.cli.git_validation.validate_git_flags_in_repo", fake_flags)
    monkeypatch.setattr("confiture.cli.git_validation.validate_git_drift", fake_drift)
    monkeypatch.setattr(
        "confiture.cli.git_validation.validate_migration_accompaniment", fake_accompaniment
    )
    monkeypatch.setattr("confiture.cli.git_validation.validate_grant_accompaniment", fake_grant)
    return calls


def test_staged_reaches_grant_accompaniment_only(
    captured_git_calls: dict[str, dict[str, Any]],
) -> None:
    result = runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-drift",
            "--require-migration",
            "--require-grant-migration",
            "--staged",
        ],
    )
    assert result.exit_code == 0, result.output
    # ARCH-L1: drift/accompaniment ignore --staged (committed-ref comparison).
    assert captured_git_calls["drift"]["target_ref"] == "HEAD"
    assert captured_git_calls["accompaniment"]["target_ref"] == "HEAD"
    # The staged index is honored only by grant-accompaniment.
    assert captured_git_calls["grant"]["staged_only"] is True


def test_non_staged_grant_accompaniment_is_not_staged(
    captured_git_calls: dict[str, dict[str, Any]],
) -> None:
    result = runner.invoke(
        app,
        ["migrate", "validate", "--require-grant-migration"],
    )
    assert result.exit_code == 0, result.output
    assert captured_git_calls["grant"]["staged_only"] is False
