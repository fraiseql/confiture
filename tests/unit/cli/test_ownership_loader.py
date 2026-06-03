"""Unit tests for ``confiture.core.validation.config_loaders`` (issue #124).

Mirrors :mod:`tests.unit.cli.test_acl_loader` in spirit. The loader is
consumed by both ``drift --check-ownership`` and
``migrate validate --check-ownership-coverage``. As of Phase 03 it raises
``ConfigurationError`` (CONFIG_001 → exit 5) instead of ``typer.Exit(2)``, so
its callers funnel the failure through their ``fail()`` boundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from confiture.core.validation.config_loaders import load_ownership_expectation
from confiture.exceptions import ConfigurationError


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


def test_load_missing_ownership_block_with_require_true_is_config_error() -> None:
    config_data: dict[str, Any] = {}
    with pytest.raises(ConfigurationError) as exc_info:
        load_ownership_expectation(config_data, Path("confiture.yaml"), require=True)
    assert exc_info.value.exit_code == 5


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


def test_invalid_yaml_block_raises_config_error() -> None:
    config_data: dict[str, Any] = {
        "ownership": {
            "expected_owner": "bad role with spaces",
            "apply_to": [{"schema": "tenant"}],
        }
    }
    with pytest.raises(ConfigurationError) as exc_info:
        load_ownership_expectation(config_data, Path("confiture.yaml"), require=True)
    assert exc_info.value.exit_code == 5


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
