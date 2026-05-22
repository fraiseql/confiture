"""Unit tests for the ``acls:`` config block (issue #120).

These tests exercise the public loader path — ``Environment.load(env_name,
project_dir)`` — because env-var expansion lives inside that method, not at
Pydantic-model validation time.  Round-tripping through a temp YAML file is
the only way to cover the expansion behavior end-to-end.

The plan's ``_write_confiture_yaml`` helper is renamed to ``_write_env_yaml``
to reflect what ``Environment.load`` actually reads: ``db/environments/<env>.yaml``.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from confiture.config.environment import AclExpectation, AclGrant, Environment
from confiture.exceptions import ConfigurationError


def _write_env_yaml(tmp_path: Path, body: str) -> Path:
    """Write a minimal ``db/environments/test.yaml`` and return the project dir.

    ``body`` is dedented and appended after the required fields at the top
    level of the YAML document (no extra indentation).
    """
    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True, exist_ok=True)
    header = "database_url: postgresql://localhost/test\ninclude_dirs: []\n"
    (env_dir / "test.yaml").write_text(header + textwrap.dedent(body))
    return tmp_path


# ---------------------------------------------------------------------------
# YAML round-trip via Environment.load
# ---------------------------------------------------------------------------


def test_acls_block_parses(tmp_path: Path) -> None:
    project = _write_env_yaml(
        tmp_path,
        """
        acls:
          - schema: tenant
            apply_to: ALL_TABLES
            grants:
              - role: my_app
                privileges: [SELECT, INSERT]
        """,
    )
    env = Environment.load("test", project)
    assert len(env.acls) == 1
    assert env.acls[0].schema_ == "tenant"
    assert env.acls[0].apply_to == "ALL_TABLES"
    assert env.acls[0].grants[0].role == "my_app"
    assert env.acls[0].grants[0].privileges == ["SELECT", "INSERT"]


def test_acls_block_defaults_to_empty(tmp_path: Path) -> None:
    """Environments without an ``acls:`` key load with ``env.acls == []``."""
    project = _write_env_yaml(tmp_path, "")
    env = Environment.load("test", project)
    assert env.acls == []


def test_acls_apply_to_accepts_pattern_list(tmp_path: Path) -> None:
    project = _write_env_yaml(
        tmp_path,
        """
        acls:
          - schema: catalog
            apply_to: ["tb_*", "view_*"]
            grants:
              - role: r
                privileges: [SELECT]
        """,
    )
    env = Environment.load("test", project)
    assert env.acls[0].apply_to == ["tb_*", "view_*"]


def test_acls_ignore_globs_default_empty(tmp_path: Path) -> None:
    project = _write_env_yaml(
        tmp_path,
        """
        acls:
          - schema: s
            apply_to: ALL_TABLES
            grants: []
        """,
    )
    env = Environment.load("test", project)
    assert env.acls[0].ignore == []


def test_acls_ignore_globs_round_trip(tmp_path: Path) -> None:
    project = _write_env_yaml(
        tmp_path,
        """
        acls:
          - schema: s
            apply_to: ALL_TABLES
            ignore: ["tb_*_legacy", "*_tmp"]
            grants: []
        """,
    )
    env = Environment.load("test", project)
    assert env.acls[0].ignore == ["tb_*_legacy", "*_tmp"]


# ---------------------------------------------------------------------------
# Model-level validation (no YAML / no env required)
# ---------------------------------------------------------------------------


def test_acl_grant_model_normalizes_privilege_case() -> None:
    g = AclGrant(role="r", privileges=["select", "Insert"])
    assert g.privileges == ["SELECT", "INSERT"]


def test_acl_grant_model_rejects_unknown_privilege() -> None:
    with pytest.raises(ValidationError, match="EXECUTE"):
        AclGrant(role="r", privileges=["SELECT", "EXECUTE"])


def test_acl_grant_model_rejects_unknown_key() -> None:
    with pytest.raises(ValidationError):
        AclGrant(role="r", privileges=["SELECT"], unknown_key="x")  # type: ignore[call-arg]


def test_acl_expectation_rejects_unknown_key() -> None:
    with pytest.raises(ValidationError):
        AclExpectation(
            schema="s",
            apply_to="ALL_TABLES",
            grants=[],
            unknown_key="x",  # type: ignore[call-arg]
        )


def test_acl_expectation_rejects_invalid_apply_to() -> None:
    with pytest.raises(ValidationError):
        AclExpectation(
            schema="s",
            apply_to="EVERYTHING",  # type: ignore[arg-type]
            grants=[],
        )


# ---------------------------------------------------------------------------
# ${VAR} expansion happens at load time (not at Pydantic validation)
# ---------------------------------------------------------------------------


def test_acls_expands_env_vars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ROLE", "realapp")
    project = _write_env_yaml(
        tmp_path,
        """
        acls:
          - schema: s
            apply_to: ALL_TABLES
            grants:
              - role: ${APP_ROLE}
                privileges: [SELECT]
        """,
    )
    env = Environment.load("test", project)
    assert env.acls[0].grants[0].role == "realapp"


def test_acls_missing_env_var_fails_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ROLE", raising=False)
    project = _write_env_yaml(
        tmp_path,
        """
        acls:
          - schema: s
            apply_to: ALL_TABLES
            grants:
              - role: ${APP_ROLE}
                privileges: [SELECT]
        """,
    )
    with pytest.raises(ConfigurationError, match="APP_ROLE"):
        Environment.load("test", project)


# ---------------------------------------------------------------------------
# ``acls.lint_enabled`` opt-in (phase 03 of post-review fixes)
# ---------------------------------------------------------------------------


def test_acls_lint_enabled_defaults_false_for_legacy_list_shape(tmp_path: Path) -> None:
    """Old flat-list YAML loads with ``lint_enabled=False``."""
    project = _write_env_yaml(
        tmp_path,
        """
        acls:
          - schema: tenant
            apply_to: ALL_TABLES
            grants:
              - role: my_app
                privileges: [SELECT]
        """,
    )
    env = Environment.load("test", project)
    assert env.acls_lint_enabled is False
    assert len(env.acls) == 1  # back-compat: env.acls still a list


def test_acls_lint_enabled_true_when_set_in_nested_shape(tmp_path: Path) -> None:
    """Nested YAML with ``lint_enabled: true`` flips the flag."""
    project = _write_env_yaml(
        tmp_path,
        """
        acls:
          lint_enabled: true
          expectations:
            - schema: tenant
              apply_to: ALL_TABLES
              grants:
                - role: my_app
                  privileges: [SELECT]
        """,
    )
    env = Environment.load("test", project)
    assert env.acls_lint_enabled is True
    # env.acls still presents as a list of AclExpectation for back-compat.
    assert len(env.acls) == 1
    assert env.acls[0].schema_ == "tenant"


def test_acls_lint_enabled_false_explicit_in_nested_shape(tmp_path: Path) -> None:
    project = _write_env_yaml(
        tmp_path,
        """
        acls:
          lint_enabled: false
          expectations:
            - schema: tenant
              apply_to: ALL_TABLES
              grants: []
        """,
    )
    env = Environment.load("test", project)
    assert env.acls_lint_enabled is False
    assert len(env.acls) == 1


def test_acls_nested_shape_without_lint_enabled_defaults_false(tmp_path: Path) -> None:
    """Nested shape omitting ``lint_enabled`` is treated as opt-out."""
    project = _write_env_yaml(
        tmp_path,
        """
        acls:
          expectations:
            - schema: tenant
              apply_to: ALL_TABLES
              grants: []
        """,
    )
    env = Environment.load("test", project)
    assert env.acls_lint_enabled is False
    assert len(env.acls) == 1


# ---------------------------------------------------------------------------
# ``AclExpectation`` → ``AclTableExpectation`` rename (phase 07)
#
# The new name lives in confiture.config.environment.  The old name keeps
# working as a deprecated alias so existing imports don't break.
# ---------------------------------------------------------------------------


def test_acl_table_expectation_is_importable() -> None:
    """``AclTableExpectation`` is the new canonical name."""
    from confiture.config.environment import AclTableExpectation

    e = AclTableExpectation(
        schema="public",
        apply_to="ALL_TABLES",
        grants=[AclGrant(role="r", privileges=["SELECT"])],
    )
    assert e.schema_ == "public"


def test_acl_expectation_alias_still_resolves_to_same_class() -> None:
    """Old import path remains for back-compat."""
    from confiture.config.environment import AclExpectation, AclTableExpectation

    assert AclExpectation is AclTableExpectation


def test_acls_lint_enabled_with_no_expectations(tmp_path: Path) -> None:
    """Setting the flag without expectations is a no-op for the lint rule."""
    project = _write_env_yaml(
        tmp_path,
        """
        acls:
          lint_enabled: true
        """,
    )
    env = Environment.load("test", project)
    assert env.acls_lint_enabled is True
    assert env.acls == []
