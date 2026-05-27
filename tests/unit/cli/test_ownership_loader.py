"""Unit tests for ``confiture.cli.ownership_loader`` (issue #124).

Mirrors :mod:`tests.unit.cli.test_acl_loader` in spirit. The loader is
consumed by both ``drift --check-ownership`` and
``migrate validate --check-ownership-coverage``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import typer

from confiture.cli.ownership_loader import load_ownership_expectation


def test_load_minimal_config() -> None:
    config_data: dict[str, Any] = {
        "ownership": {
            "expected_owner": "migrator",
            "apply_to": [{"schema": "tenant"}],
        }
    }
    result = load_ownership_expectation(config_data, Path("confiture.yaml"), require=True)
    assert result is not None
    assert result.expected_owner == "migrator"
    assert result.apply_to[0].schema_ == "tenant"


def test_load_missing_ownership_block_with_require_true_exits_2() -> None:
    config_data: dict[str, Any] = {}
    with pytest.raises(typer.Exit) as exc_info:
        load_ownership_expectation(config_data, Path("confiture.yaml"), require=True)
    assert exc_info.value.exit_code == 2


def test_load_missing_ownership_block_with_require_false_returns_none() -> None:
    config_data: dict[str, Any] = {}
    result = load_ownership_expectation(config_data, Path("confiture.yaml"), require=False)
    assert result is None


def test_env_var_expansion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OWNER", "realowner")
    config_data: dict[str, Any] = {
        "ownership": {
            "expected_owner": "${OWNER}",
            "apply_to": [{"schema": "tenant"}],
        }
    }
    result = load_ownership_expectation(config_data, Path("confiture.yaml"), require=True)
    assert result is not None
    assert result.expected_owner == "realowner"


def test_invalid_yaml_block_raises_typer_exit() -> None:
    config_data: dict[str, Any] = {
        "ownership": {
            "expected_owner": "bad role with spaces",
            "apply_to": [{"schema": "tenant"}],
        }
    }
    with pytest.raises(typer.Exit) as exc_info:
        load_ownership_expectation(config_data, Path("confiture.yaml"), require=True)
    assert exc_info.value.exit_code == 2


def test_load_block_with_lint_enabled_false() -> None:
    config_data: dict[str, Any] = {
        "ownership": {
            "expected_owner": "migrator",
            "apply_to": [{"schema": "tenant"}],
            "lint_enabled": False,
        }
    }
    result = load_ownership_expectation(config_data, Path("confiture.yaml"), require=True)
    assert result is not None
    assert result.lint_enabled is False


def test_load_block_with_ignore_list() -> None:
    config_data: dict[str, Any] = {
        "ownership": {
            "expected_owner": "migrator",
            "apply_to": [{"schema": "tenant"}],
            "ignore": ["tenant.legacy", "*.audit_log"],
        }
    }
    result = load_ownership_expectation(config_data, Path("confiture.yaml"), require=True)
    assert result is not None
    assert result.ignore == ["tenant.legacy", "*.audit_log"]
