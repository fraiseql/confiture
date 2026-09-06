"""Tests for the regex/AST backend dispatcher in ``patterns.py``.

These tests bypass the autouse ``idempotency_backend`` parametrization
by setting/unsetting the force-regex env var inline and checking that
the dispatcher picks the right backend.
"""

from __future__ import annotations

import pytest

from confiture.core.idempotency import patterns
from confiture.core.idempotency.ast_detector import is_pglast_available

# This file doesn't care about parity sweeps — every test here is about
# the dispatcher's selection logic. Skip the AST run; the regex run is
# enough because we control backend selection per-test.
pytestmark = pytest.mark.regex_only(reason="dispatcher tests pick backend per-test inline")


def test_pglast_is_actually_available_in_dev_env():
    """Dev env has the ``[ast]`` extra installed — the dispatcher path under test."""
    assert is_pglast_available() is True


def test_force_regex_env_var_routes_to_regex(monkeypatch):
    """Setting CONFITURE_IDEMPOTENCY_FORCE_REGEX=1 pins the dispatcher to regex."""
    monkeypatch.setenv("CONFITURE_IDEMPOTENCY_FORCE_REGEX", "1")
    calls: list[str] = []

    def stub_ast(_sql):
        calls.append("ast")
        return []

    def stub_regex(_sql):
        calls.append("regex")
        return []

    monkeypatch.setattr(patterns, "_detect_via_ast", stub_ast)
    monkeypatch.setattr(patterns, "_detect_via_regex", stub_regex)

    patterns.detect_non_idempotent_patterns("CREATE TABLE foo (id INT);")
    assert calls == ["regex"]


def test_unset_env_var_uses_ast_when_available(monkeypatch):
    """No env var + pglast importable → AST is preferred."""
    monkeypatch.delenv("CONFITURE_IDEMPOTENCY_FORCE_REGEX", raising=False)
    calls: list[str] = []

    def stub_ast(_sql):
        calls.append("ast")
        return []

    def stub_regex(_sql):
        calls.append("regex")
        return []

    monkeypatch.setattr(patterns, "_detect_via_ast", stub_ast)
    monkeypatch.setattr(patterns, "_detect_via_regex", stub_regex)

    patterns.detect_non_idempotent_patterns("CREATE TABLE foo (id INT);")
    assert calls == ["ast"]


def test_ast_parse_error_falls_through_to_regex(monkeypatch):
    """An exception from the AST backend (e.g. ParseError) falls through silently."""
    monkeypatch.delenv("CONFITURE_IDEMPOTENCY_FORCE_REGEX", raising=False)
    calls: list[str] = []

    def stub_ast(_sql):
        calls.append("ast")
        raise RuntimeError("simulated parse failure")

    def stub_regex(_sql):
        calls.append("regex")
        return []

    monkeypatch.setattr(patterns, "_detect_via_ast", stub_ast)
    monkeypatch.setattr(patterns, "_detect_via_regex", stub_regex)

    patterns.detect_non_idempotent_patterns("malformed SQL")
    assert calls == ["ast", "regex"]


@pytest.mark.parametrize("value", ["0", "false", "no", "", "off"])
def test_falsy_env_var_does_not_force_regex(monkeypatch, value):
    """The env var must be truthy to flip the switch — 0/false/empty don't count."""
    monkeypatch.setenv("CONFITURE_IDEMPOTENCY_FORCE_REGEX", value)
    calls: list[str] = []

    def stub_ast(_sql):
        calls.append("ast")
        return []

    def stub_regex(_sql):
        calls.append("regex")
        return []

    monkeypatch.setattr(patterns, "_detect_via_ast", stub_ast)
    monkeypatch.setattr(patterns, "_detect_via_regex", stub_regex)

    patterns.detect_non_idempotent_patterns("CREATE TABLE foo (id INT);")
    assert calls == ["ast"]
