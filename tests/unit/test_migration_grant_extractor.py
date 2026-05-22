"""Unit tests for :class:`MigrationGrantExtractor` (issue #120, Phase 2 Cycle 1).

The extractor pulls ``CREATE TABLE`` targets and ``GRANT … ON … TO …``
tuples out of a migration's SQL text.  pglast is the primary parser
(no token limits, accurate names); sqlparse + regex is the fallback
when pglast isn't installed.

Both parser paths must agree on every fixture below.
"""

from __future__ import annotations

import pytest

from confiture.core.migration_grant_extractor import (
    _ALL_TABLE_PRIVILEGES,
    MigrationGrantExtractor,
)

# ---------------------------------------------------------------------------
# CREATE TABLE extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("CREATE TABLE foo (id int);", [("public", "foo")]),
        ("CREATE TABLE IF NOT EXISTS s.t (id int);", [("s", "t")]),
        (
            "-- comment\nCREATE TABLE a (id int);\nCREATE TABLE b (id int);",
            [("public", "a"), ("public", "b")],
        ),
        ('CREATE TABLE "MyTable" (id int);', [("public", "MyTable")]),
        ("CREATE TABLE foo AS SELECT 1;", [("public", "foo")]),
    ],
)
def test_extracts_create_table_pglast(sql: str, expected: list[tuple[str, str]]) -> None:
    assert MigrationGrantExtractor().extract_creates(sql) == expected


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("CREATE TABLE foo (id int);", [("public", "foo")]),
        ("CREATE TABLE IF NOT EXISTS s.t (id int);", [("s", "t")]),
        (
            "-- comment\nCREATE TABLE a (id int);\nCREATE TABLE b (id int);",
            [("public", "a"), ("public", "b")],
        ),
        ('CREATE TABLE "MyTable" (id int);', [("public", "MyTable")]),
        ("CREATE TABLE foo AS SELECT 1;", [("public", "foo")]),
    ],
)
def test_extracts_create_table_sqlparse_fallback(
    sql: str,
    expected: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "confiture.core.migration_grant_extractor._HAS_PGLAST", False
    )
    assert MigrationGrantExtractor().extract_creates(sql) == expected


def test_create_table_inside_comment_is_ignored() -> None:
    sql = "/* CREATE TABLE ghost (id int); */\nCREATE TABLE real_one (id int);"
    assert MigrationGrantExtractor().extract_creates(sql) == [("public", "real_one")]


def test_drop_table_within_same_text_is_extractable() -> None:
    sql = "CREATE TABLE foo (id int);\nDROP TABLE foo;"
    extractor = MigrationGrantExtractor()
    assert extractor.extract_creates(sql) == [("public", "foo")]
    assert extractor.extract_drops(sql) == [("public", "foo")]


# ---------------------------------------------------------------------------
# GRANT extraction
# ---------------------------------------------------------------------------


def _grant(schema: str, table: str, role: str, privs: set[str]) -> tuple[str, str, str, frozenset[str]]:
    return (schema, table, role, frozenset(privs))


@pytest.mark.parametrize(
    "sql,expected",
    [
        (
            "GRANT SELECT ON foo TO r;",
            [_grant("public", "foo", "r", {"SELECT"})],
        ),
        (
            "GRANT SELECT, INSERT ON s.t TO r1, r2;",
            [
                _grant("s", "t", "r1", {"SELECT", "INSERT"}),
                _grant("s", "t", "r2", {"SELECT", "INSERT"}),
            ],
        ),
        (
            "GRANT ALL ON s.t TO r;",
            [_grant("s", "t", "r", _ALL_TABLE_PRIVILEGES)],
        ),
        (
            "GRANT ALL PRIVILEGES ON s.t TO r;",
            [_grant("s", "t", "r", _ALL_TABLE_PRIVILEGES)],
        ),
    ],
)
def test_extracts_grants_pglast(sql: str, expected: list) -> None:
    assert MigrationGrantExtractor().extract_grants(sql) == expected


@pytest.mark.parametrize(
    "sql,expected",
    [
        (
            "GRANT SELECT ON foo TO r;",
            [_grant("public", "foo", "r", {"SELECT"})],
        ),
        (
            "GRANT SELECT, INSERT ON s.t TO r1, r2;",
            [
                _grant("s", "t", "r1", {"SELECT", "INSERT"}),
                _grant("s", "t", "r2", {"SELECT", "INSERT"}),
            ],
        ),
        (
            "GRANT ALL ON s.t TO r;",
            [_grant("s", "t", "r", _ALL_TABLE_PRIVILEGES)],
        ),
    ],
)
def test_extracts_grants_sqlparse_fallback(
    sql: str,
    expected: list,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "confiture.core.migration_grant_extractor._HAS_PGLAST", False
    )
    assert MigrationGrantExtractor().extract_grants(sql) == expected


def test_revoke_is_not_extracted_as_grant() -> None:
    sql = "REVOKE SELECT ON foo FROM r;"
    assert MigrationGrantExtractor().extract_grants(sql) == []


# ---------------------------------------------------------------------------
# Dynamic SQL detection — informational, must not crash
# ---------------------------------------------------------------------------


def test_dynamic_sql_create_table_emits_info() -> None:
    sql = "DO $$ BEGIN EXECUTE format('CREATE TABLE %I (id int)', 'invisible'); END $$;"
    extractor = MigrationGrantExtractor()
    # Dynamic SQL is invisible to static parsing — must not raise and must
    # not "find" the table.
    assert extractor.extract_creates(sql) == []
    assert extractor.has_dynamic_sql(sql) is True


def test_static_only_sql_has_no_dynamic_sql() -> None:
    sql = "CREATE TABLE foo (id int);"
    assert MigrationGrantExtractor().has_dynamic_sql(sql) is False


# ---------------------------------------------------------------------------
# Sanity: pglast available by default in this test env
# ---------------------------------------------------------------------------


def test_pglast_is_the_default_parser() -> None:
    from confiture.core import migration_grant_extractor as mod

    assert mod._HAS_PGLAST is True
