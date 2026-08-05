"""ARCH-L1: pin where ``migrate validate --staged`` actually routes.

Before 0.42.0 the answer was "almost nowhere": drift and migration
accompaniment received ``target_ref="HEAD"`` whether or not ``--staged`` was
passed, so the pre-commit flag compared the last commit against itself and the
staged change — the thing being committed — was invisible. Only
grant-accompaniment honoured the index.

#184 makes ``--staged`` a real scope for the whole group. These tests pin the
new routing at the seam, one level below the end-to-end behaviour in
``tests/integration/test_validate_staged_scope.py``:

- drift and accompaniment receive the **staged index as a tree OID** in place
  of ``"HEAD"``, and accompaniment additionally receives ``two_dot=True``,
  because ``base...tree`` is not a valid symmetric difference;
- grant-accompaniment keeps its own ``staged_only`` path against ``"HEAD"`` —
  it diffs grant *files* through the index and never built a schema from a ref;
- without ``--staged``, every ref is ``"HEAD"`` and nothing is two-dot.

``--base-ref HEAD`` is explicit throughout: the default ``origin/main`` does not
resolve in a shallow CI checkout, and staged mode verifies the base ref up front
(GIT_003). The git-validation functions are patched on their source module
(``confiture.cli.git_validation``) since ``migrate_validate`` imports them lazily.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_OID_RE = re.compile(r"^[0-9a-f]{40}$")


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


def test_staged_scopes_drift_and_accompaniment_to_the_index(
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
            "--base-ref",
            "HEAD",
            "--staged",
        ],
    )
    assert result.exit_code == 0, result.output

    # #184: the target is the index written out as a tree, not the last commit.
    staged_tree = captured_git_calls["drift"]["target_ref"]
    assert _OID_RE.match(staged_tree), staged_tree
    assert captured_git_calls["accompaniment"]["target_ref"] == staged_tree
    # A tree has no merge base, so the file diffs must run two-dot.
    assert captured_git_calls["accompaniment"]["two_dot"] is True
    # Both checks share one resolved base, so they cannot disagree about scope.
    assert (
        captured_git_calls["drift"]["base_ref"] == captured_git_calls["accompaniment"]["base_ref"]
    )
    # Grant accompaniment reaches the index its own way, against HEAD.
    assert captured_git_calls["grant"]["staged_only"] is True
    assert captured_git_calls["grant"]["target_ref"] == "HEAD"


def test_without_staged_every_check_compares_committed_refs(
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
            "--base-ref",
            "HEAD",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured_git_calls["drift"]["target_ref"] == "HEAD"
    assert captured_git_calls["accompaniment"]["target_ref"] == "HEAD"
    assert captured_git_calls["accompaniment"]["two_dot"] is False
    assert captured_git_calls["grant"]["staged_only"] is False


def test_non_staged_grant_accompaniment_is_not_staged(
    captured_git_calls: dict[str, dict[str, Any]],
) -> None:
    result = runner.invoke(
        app,
        ["migrate", "validate", "--require-grant-migration"],
    )
    assert result.exit_code == 0, result.output
    assert captured_git_calls["grant"]["staged_only"] is False
