"""Unit tests for ``MigrationAnalyzer`` — the **regex fallback** backend.

The pglast (AST) path is exercised in ``test_preflight.py``; that suite is
gated on ``importorskip("pglast")`` and never runs the regex fallback, which
``analyze()`` uses only when pglast is unavailable. This file forces that
path (by making ``import pglast`` fail) so the fallback's statement taxonomy
has direct coverage.

Note: the two backends intentionally disagree on database statements — the
AST path reports ``CREATEDB``/``DROPDB`` (node names) while the regex path
reports ``CREATE DATABASE``/``DROP DATABASE`` (matched text). These tests pin
the regex behavior specifically.
"""

from __future__ import annotations

import sys

import pytest

from confiture.core.migration_analyzer import MigrationAnalyzer


@pytest.fixture
def analyzer_regex(monkeypatch) -> MigrationAnalyzer:
    """A MigrationAnalyzer pinned to the regex fallback (pglast made absent)."""
    monkeypatch.setitem(sys.modules, "pglast", None)
    return MigrationAnalyzer()


def test_create_index_concurrently_captures_name(analyzer_regex):
    sql = "CREATE INDEX CONCURRENTLY idx_users_email ON users(email);"
    assert analyzer_regex.analyze(sql) == ["CREATE INDEX CONCURRENTLY: idx_users_email"]


def test_create_unique_index_concurrently_captures_name(analyzer_regex):
    sql = "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_users_email ON users(email);"
    assert analyzer_regex.analyze(sql) == ["CREATE INDEX CONCURRENTLY: uq_users_email"]


def test_regular_create_index_not_flagged(analyzer_regex):
    assert analyzer_regex.analyze("CREATE INDEX idx_users_email ON users(email);") == []


def test_drop_index_concurrently(analyzer_regex):
    assert analyzer_regex.analyze("DROP INDEX CONCURRENTLY idx_users_email;") == [
        "DROP INDEX CONCURRENTLY"
    ]


def test_alter_type_add_value(analyzer_regex):
    assert analyzer_regex.analyze("ALTER TYPE status ADD VALUE 'archived';") == [
        "ALTER TYPE status ADD VALUE"
    ]


def test_reindex_concurrently(analyzer_regex):
    assert analyzer_regex.analyze("REINDEX INDEX CONCURRENTLY idx_users_email;") == [
        "REINDEX CONCURRENTLY"
    ]


def test_create_database(analyzer_regex):
    assert analyzer_regex.analyze("CREATE DATABASE analytics;") == ["CREATE DATABASE"]


def test_drop_database(analyzer_regex):
    assert analyzer_regex.analyze("DROP DATABASE analytics;") == ["DROP DATABASE"]


def test_vacuum(analyzer_regex):
    assert analyzer_regex.analyze("VACUUM ANALYZE users;") == ["VACUUM"]


def test_cluster(analyzer_regex):
    assert analyzer_regex.analyze("CLUSTER users USING idx_users_email;") == ["CLUSTER"]


def test_purely_transactional_returns_empty(analyzer_regex):
    sql = """
    CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT);
    ALTER TABLE users ADD COLUMN email TEXT;
    CREATE INDEX idx_users_name ON users(name);
    """
    assert analyzer_regex.analyze(sql) == []


def test_multiple_non_transactional_all_detected(analyzer_regex):
    sql = """
    ALTER TABLE users ADD COLUMN bio TEXT;
    CREATE INDEX CONCURRENTLY idx_a ON t(a);
    VACUUM users;
    """
    result = analyzer_regex.analyze(sql)
    assert "CREATE INDEX CONCURRENTLY: idx_a" in result
    assert "VACUUM" in result
    assert len(result) == 2
