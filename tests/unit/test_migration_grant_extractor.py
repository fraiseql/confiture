"""Unit tests for :class:`MigrationGrantExtractor` (issue #120).

The extractor pulls ``CREATE TABLE`` targets and ``GRANT … ON … TO …``
tuples out of a migration's SQL text.  pglast is the primary parser
(no token limits, accurate names); sqlparse + regex is the fallback
when pglast isn't installed.

Both parser paths must agree on every fixture below — the
``test_pglast_sqlparse_parity_*`` block at the bottom of the file is
the contract: if you add a fixture there, both backends MUST produce
the same result.  That's the point of this file.
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
    monkeypatch.setattr("confiture.core.migration_grant_extractor._HAS_PGLAST", False)
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


def _grant(
    schema: str, table: str, role: str, privs: set[str]
) -> tuple[str, str, str, frozenset[str]]:
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
    monkeypatch.setattr("confiture.core.migration_grant_extractor._HAS_PGLAST", False)
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


# ---------------------------------------------------------------------------
# Parity harness — every fixture runs against BOTH backends and the
# results MUST match.  If you add a case here, you are pinning that the
# pglast primary path and the sqlparse fallback agree on it.
# ---------------------------------------------------------------------------


# Each fixture is (method, sql, expected) where method names the
# extractor method to invoke.  ``set(...)`` comparison so ordering
# differences between backends don't trip the parity gate.
_PARITY_FIXTURES: list[tuple[str, str, set]] = [
    # Multi-target GRANT — pglast splits via stmt.objects; sqlparse must
    # split the comma-list manually.
    (
        "extract_grants",
        "GRANT SELECT ON a, b, c TO r;",
        {
            ("public", "a", "r", frozenset({"SELECT"})),
            ("public", "b", "r", frozenset({"SELECT"})),
            ("public", "c", "r", frozenset({"SELECT"})),
        },
    ),
    # Multi-target DROP TABLE.
    (
        "extract_drops",
        "DROP TABLE a, b, c;",
        {("public", "a"), ("public", "b"), ("public", "c")},
    ),
    # ``WITH GRANT OPTION`` must be stripped from the role list, not
    # absorbed into the role name.
    (
        "extract_grants",
        "GRANT SELECT ON foo TO r WITH GRANT OPTION;",
        {("public", "foo", "r", frozenset({"SELECT"}))},
    ),
    # PUBLIC pseudo-role: both paths emit the literal "PUBLIC".
    (
        "extract_grants",
        "GRANT SELECT ON foo TO PUBLIC;",
        {("public", "foo", "PUBLIC", frozenset({"SELECT"}))},
    ),
    # CREATE TEMP TABLE: both paths exclude (TEMP doesn't persist).
    (
        "extract_creates",
        "CREATE TEMP TABLE foo (id int);",
        set(),
    ),
    # CREATE UNLOGGED TABLE: both paths include (UNLOGGED is permanent).
    (
        "extract_creates",
        "CREATE UNLOGGED TABLE foo (id int);",
        {("public", "foo")},
    ),
    # Partitioned parent: both paths include (grants applied here
    # propagate to all children).
    (
        "extract_creates",
        "CREATE TABLE foo (id int, d date) PARTITION BY RANGE (d);",
        {("public", "foo")},
    ),
    # Partition child: both paths exclude (the child inherits grants
    # from the parent — flagging it would be a false positive).
    (
        "extract_creates",
        "CREATE TABLE foo_2026 PARTITION OF foo FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');",
        set(),
    ),
]


@pytest.mark.parametrize(
    "method,sql,expected",
    _PARITY_FIXTURES,
    ids=[
        "grant_multi_target",
        "drop_multi_target",
        "grant_with_grant_option",
        "grant_to_public",
        "create_temp_table",
        "create_unlogged_table",
        "create_partitioned_parent",
        "create_partition_child",
    ],
)
def test_pglast_sqlparse_parity(
    method: str,
    sql: str,
    expected: set,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both extractor backends must return the same set for the same SQL."""
    extractor = MigrationGrantExtractor()

    # pglast path (default).
    pglast_result = set(getattr(extractor, method)(sql))

    # sqlparse fallback path.
    monkeypatch.setattr("confiture.core.migration_grant_extractor._HAS_PGLAST", False)
    sqlparse_result = set(getattr(MigrationGrantExtractor(), method)(sql))

    assert pglast_result == expected, f"pglast diverged on {sql!r}"
    assert sqlparse_result == expected, f"sqlparse diverged on {sql!r}"
    assert pglast_result == sqlparse_result, (
        f"backends disagree on {sql!r}: pglast={pglast_result} sqlparse={sqlparse_result}"
    )
