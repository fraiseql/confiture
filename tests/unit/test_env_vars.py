"""Unit tests for ``${VAR}`` expansion semantics.

The expander supports ``${UPPER_NAME}`` only.  Anything that *looks* like
an env-var reference but doesn't match the strict form is rejected with
``ConfigurationError`` so users get an actionable error instead of a
cryptic downstream failure (typically "role does not exist" from
psycopg).
"""

from __future__ import annotations

import pytest

from confiture.config._env_vars import expand_env_vars
from confiture.exceptions import ConfigurationError


def test_expands_strict_upper_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_ROLE", "app_role")
    assert expand_env_vars("${MY_ROLE}", context="t") == "app_role"


def test_raises_on_missing_strict_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING", raising=False)
    with pytest.raises(ConfigurationError, match="MISSING"):
        expand_env_vars("${MISSING}", context="t")


def test_raises_on_default_value_syntax() -> None:
    """``${VAR:-default}`` — bash default syntax — is not supported."""
    with pytest.raises(ConfigurationError) as excinfo:
        expand_env_vars("${VAR:-default}", context="t")
    msg = str(excinfo.value)
    assert ":-" in msg or "default" in msg.lower()


def test_raises_on_lowercase_var_name() -> None:
    """Lowercase var names are rejected with a casing hint."""
    with pytest.raises(ConfigurationError) as excinfo:
        expand_env_vars("${lower_var}", context="t")
    msg = str(excinfo.value)
    # The diagnostic should hint at the casing rule.
    assert "upper" in msg.lower() or "case" in msg.lower() or "LOWER_VAR" in msg


def test_raises_on_unclosed_brace() -> None:
    """``${VAR`` without closing brace is rejected."""
    with pytest.raises(ConfigurationError) as excinfo:
        expand_env_vars("${VAR", context="t")
    msg = str(excinfo.value)
    assert "unclosed" in msg.lower() or "}" in msg


def test_raises_on_empty_braces() -> None:
    """``${}`` is rejected (no var name)."""
    with pytest.raises(ConfigurationError):
        expand_env_vars("${}", context="t")


def test_does_not_recurse_into_expanded_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Single-pass substitution: the result is not re-scanned for ``${...}``."""
    monkeypatch.setenv("OUTER", "${INNER}")
    monkeypatch.setenv("INNER", "value")
    # Single-pass: OUTER expands to the literal "${INNER}" — we then check
    # the result for residual ``${...}`` and raise to avoid silent surprises.
    with pytest.raises(ConfigurationError) as excinfo:
        expand_env_vars("${OUTER}", context="t")
    assert "nested" in str(excinfo.value).lower() or "${" in str(excinfo.value)


def test_strict_form_inside_larger_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROLE", "app")
    assert expand_env_vars("prefix_${ROLE}_suffix", context="t") == "prefix_app_suffix"


def test_env_var_value_with_special_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hyphens, dots, and dollar signs in the *value* flow through unchanged."""
    monkeypatch.setenv("ROLE_NAME", "role-with-dashes.and.dots")
    assert expand_env_vars("${ROLE_NAME}", context="t") == "role-with-dashes.and.dots"


def test_dollar_sign_without_braces_passes_through() -> None:
    """``$VAR`` (no braces) is not an env-var reference here — leave it alone."""
    assert expand_env_vars("plain $literal text", context="t") == "plain $literal text"


def test_walks_nested_dicts_and_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R", "alpha")
    data = {"a": [{"role": "${R}"}, "${R}"], "b": "${R}"}
    assert expand_env_vars(data, context="t") == {
        "a": [{"role": "alpha"}, "alpha"],
        "b": "alpha",
    }


def test_context_appears_in_error_message() -> None:
    with pytest.raises(ConfigurationError, match="acls"):
        expand_env_vars("${unsupported_lowercase}", context="acls")
