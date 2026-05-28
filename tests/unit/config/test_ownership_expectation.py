"""Unit tests for the ``ownership:`` config block (issue #124).

Mirrors :mod:`tests.unit.config.test_acl_config`. The ``ownership:`` block
is a single dict (not a list of expectations), and ``lint_enabled`` defaults
to ``True`` — opt-in by default per the issue's "Definition of done."
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from confiture.config.environment import (
    Environment,
    OwnershipApplyTo,
    OwnershipExpectation,
)
from confiture.exceptions import ConfigurationError


def _write_env_yaml(tmp_path: Path, body: str) -> Path:
    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True, exist_ok=True)
    header = "database_url: postgresql://localhost/test\ninclude_dirs: []\n"
    (env_dir / "test.yaml").write_text(header + textwrap.dedent(body))
    return tmp_path


# ---------------------------------------------------------------------------
# OwnershipExpectation model
# ---------------------------------------------------------------------------


def test_minimal_valid_config() -> None:
    e = OwnershipExpectation(
        expected_owner="migrator",
        apply_to=[OwnershipApplyTo(schema="tenant")],
    )
    assert e.expected_owner == "migrator"
    assert e.apply_to[0].schema_ == "tenant"
    assert e.apply_to[0].relkinds == ["r", "S", "v", "m"]
    assert e.ignore == []


def test_lint_enabled_defaults_true() -> None:
    """Opt-in by default per issue #124's Definition of done."""
    e = OwnershipExpectation(
        expected_owner="migrator",
        apply_to=[OwnershipApplyTo(schema="tenant")],
    )
    assert e.lint_enabled is True


def test_invalid_relkind_rejected() -> None:
    with pytest.raises(ValidationError, match="relkinds"):
        OwnershipApplyTo(schema="tenant", relkinds=["x"])


def test_invalid_owner_name_rejected_space() -> None:
    with pytest.raises(ValidationError, match="role identifier"):
        OwnershipExpectation(
            expected_owner="Drop Table",
            apply_to=[OwnershipApplyTo(schema="t")],
        )


def test_invalid_owner_name_rejected_punctuation() -> None:
    with pytest.raises(ValidationError, match="role identifier"):
        OwnershipExpectation(
            expected_owner="bad;role",
            apply_to=[OwnershipApplyTo(schema="t")],
        )


def test_quoted_owner_name_accepted() -> None:
    e = OwnershipExpectation(
        expected_owner='"Mixed Case"',
        apply_to=[OwnershipApplyTo(schema="t")],
    )
    assert e.expected_owner == '"Mixed Case"'


def test_ownership_expectation_rejects_unknown_key() -> None:
    with pytest.raises(ValidationError):
        OwnershipExpectation(
            expected_owner="migrator",
            apply_to=[OwnershipApplyTo(schema="t")],
            unknown_key="x",  # type: ignore[call-arg]
        )


def test_ignore_list_defaults_empty() -> None:
    e = OwnershipExpectation(
        expected_owner="migrator",
        apply_to=[OwnershipApplyTo(schema="t")],
    )
    assert e.ignore == []


def test_apply_to_custom_relkinds() -> None:
    a = OwnershipApplyTo(schema="t", relkinds=["r", "S"])
    assert a.relkinds == ["r", "S"]


# ---------------------------------------------------------------------------
# Environment integration
# ---------------------------------------------------------------------------


def test_environment_accepts_ownership_block(tmp_path: Path) -> None:
    project = _write_env_yaml(
        tmp_path,
        """
        ownership:
          expected_owner: migrator
          apply_to:
            - schema: tenant
              relkinds: [r, S, v, m]
            - schema: public
              relkinds: [r, S]
          ignore:
            - public.legacy_audit_log
          lint_enabled: true
        """,
    )
    env = Environment.load("test", project)
    assert env.ownership is not None
    assert env.ownership.expected_owner == "migrator"
    assert len(env.ownership.apply_to) == 2
    assert env.ownership.apply_to[0].schema_ == "tenant"
    assert env.ownership.apply_to[0].relkinds == ["r", "S", "v", "m"]
    assert env.ownership.apply_to[1].schema_ == "public"
    assert env.ownership.apply_to[1].relkinds == ["r", "S"]
    assert env.ownership.ignore == ["public.legacy_audit_log"]
    assert env.ownership.lint_enabled is True


def test_environment_without_ownership_block_is_valid(tmp_path: Path) -> None:
    project = _write_env_yaml(tmp_path, "")
    env = Environment.load("test", project)
    assert env.ownership is None


def test_environment_ownership_block_omitting_lint_enabled_defaults_true(
    tmp_path: Path,
) -> None:
    project = _write_env_yaml(
        tmp_path,
        """
        ownership:
          expected_owner: migrator
          apply_to:
            - schema: tenant
        """,
    )
    env = Environment.load("test", project)
    assert env.ownership is not None
    assert env.ownership.lint_enabled is True


def test_environment_ownership_expands_env_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OWNER", "realowner")
    project = _write_env_yaml(
        tmp_path,
        """
        ownership:
          expected_owner: ${OWNER}
          apply_to:
            - schema: tenant
        """,
    )
    env = Environment.load("test", project)
    assert env.ownership is not None
    assert env.ownership.expected_owner == "realowner"


def test_environment_ownership_missing_env_var_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OWNER", raising=False)
    project = _write_env_yaml(
        tmp_path,
        """
        ownership:
          expected_owner: ${OWNER}
          apply_to:
            - schema: tenant
        """,
    )
    with pytest.raises(ConfigurationError, match="OWNER"):
        Environment.load("test", project)


# ---------------------------------------------------------------------------
# bootstrap_connection_url + default_privileges (issue #137 / Phase C)
# ---------------------------------------------------------------------------


def test_bootstrap_connection_url_optional() -> None:
    """Bootstrap URL is optional; defaults to None when unset."""
    e = OwnershipExpectation(
        expected_owner="migrator",
        apply_to=[OwnershipApplyTo(schema="tenant")],
    )
    assert e.bootstrap_connection_url is None


def test_bootstrap_connection_url_accepts_string() -> None:
    e = OwnershipExpectation(
        expected_owner="migrator",
        apply_to=[OwnershipApplyTo(schema="tenant")],
        bootstrap_connection_url="postgresql://super@localhost/prod",
    )
    assert e.bootstrap_connection_url == "postgresql://super@localhost/prod"


def test_default_privileges_parses_nested_mapping() -> None:
    """`schema -> role -> [PRIV, ...]` parses with privilege-keyword validation."""
    e = OwnershipExpectation(
        expected_owner="migrator",
        apply_to=[OwnershipApplyTo(schema="tenant")],
        default_privileges={
            "tenant": {
                "app": ["SELECT", "INSERT", "UPDATE", "DELETE"],
                "readonly": ["SELECT"],
            }
        },
    )
    assert e.default_privileges is not None
    assert e.default_privileges["tenant"]["app"] == [
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
    ]
    assert e.default_privileges["tenant"]["readonly"] == ["SELECT"]


def test_default_privileges_rejects_unknown_keyword() -> None:
    with pytest.raises(ValidationError, match="DROP"):
        OwnershipExpectation(
            expected_owner="migrator",
            apply_to=[OwnershipApplyTo(schema="tenant")],
            default_privileges={"tenant": {"app": ["SELECT", "DROP"]}},
        )


def test_default_privileges_none_when_unconfigured() -> None:
    """Absent block → ``default_privileges is None`` (bootstrap step skipped)."""
    e = OwnershipExpectation(
        expected_owner="migrator",
        apply_to=[OwnershipApplyTo(schema="tenant")],
    )
    assert e.default_privileges is None
