"""Tests for the regex/AST backend dispatcher in ``patterns.py``.

These tests bypass the autouse ``idempotency_backend`` parametrization
by setting/unsetting the force-regex env var inline and checking that
the dispatcher picks the right backend.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

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


def test_slim_install_falls_back_to_regex(monkeypatch):
    """When pglast is not importable, dispatcher goes straight to regex.

    Simulated by making ``importlib.util.find_spec`` return None for
    pglast and clearing the cached availability check.
    """
    from confiture.core.idempotency import ast_detector

    monkeypatch.delenv("CONFITURE_IDEMPOTENCY_FORCE_REGEX", raising=False)
    ast_detector.is_pglast_available.cache_clear()

    real_find_spec = sys.modules["importlib.util"].find_spec

    def fake_find_spec(name, *a, **kw):
        if name == "pglast":
            return None
        return real_find_spec(name, *a, **kw)

    calls: list[str] = []

    def stub_ast(_sql):
        calls.append("ast")
        return []

    def stub_regex(_sql):
        calls.append("regex")
        return []

    with patch("importlib.util.find_spec", fake_find_spec):
        ast_detector.is_pglast_available.cache_clear()
        monkeypatch.setattr(patterns, "_detect_via_ast", stub_ast)
        monkeypatch.setattr(patterns, "_detect_via_regex", stub_regex)
        patterns.detect_non_idempotent_patterns("CREATE TABLE foo (id INT);")

    ast_detector.is_pglast_available.cache_clear()
    assert calls == ["regex"]


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE users (id INT);",
        "CREATE INDEX idx_email ON users(email);",
        "CREATE UNIQUE INDEX idx_uniq ON users(email);",
        "ALTER TABLE users ADD COLUMN email TEXT;",
        "ALTER TABLE app.users ADD COLUMN email TEXT;",
        "DROP TABLE old_users;",
        "DROP INDEX idx_x;",
        "CREATE VIEW v_users AS SELECT * FROM users;",
        "CREATE FUNCTION fn() RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;",
        "CREATE EXTENSION btree_gin;",
        "CREATE SCHEMA app;",
        "CREATE SEQUENCE seq1;",
    ],
)
def test_fixer_output_is_byte_identical_across_backends(monkeypatch, sql):
    """``IdempotencyFixer.fix`` and ``dry_run`` produce identical output on both backends.

    The fixer's rewrite path is regex-only (it doesn't consult the
    detector at all), so ``fix`` is naturally backend-agnostic. The
    ``dry_run`` path *does* call the detector and builds suggestions
    from ``match.sql_snippet`` — divergence there would mean the AST
    backend's snippet boundaries drift from the regex backend's,
    breaking downstream consumers that rely on stable snippet text.
    """
    from confiture.core.idempotency.fixer import IdempotencyFixer  # noqa: PLC0415

    monkeypatch.setenv("CONFITURE_IDEMPOTENCY_FORCE_REGEX", "1")
    regex_fixer = IdempotencyFixer()
    regex_fix = regex_fixer.fix(sql)
    regex_dry = [(c.pattern, c.suggested_fix, c.line_number) for c in regex_fixer.dry_run(sql)]

    monkeypatch.delenv("CONFITURE_IDEMPOTENCY_FORCE_REGEX", raising=False)
    ast_fixer = IdempotencyFixer()
    ast_fix = ast_fixer.fix(sql)
    ast_dry = [(c.pattern, c.suggested_fix, c.line_number) for c in ast_fixer.dry_run(sql)]

    assert regex_fix == ast_fix, "fix() output diverges across backends"
    assert regex_dry == ast_dry, "dry_run() output diverges across backends"


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
