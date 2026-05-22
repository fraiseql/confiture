"""Unit tests for the ACL coverage lint rule (issue #120, Phase 2 Cycle 2).

The rule walks a migrations directory, extracts ``CREATE TABLE``s and
``GRANT``s, then checks each created table against the ``acls:`` block
expectations.  Coverage can come from the same migration file or from
the configured global grant sweep directory (typically ``db/7_grant``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.config.environment import AclExpectation, AclGrant
from confiture.core.linting.libraries.acl import (
    Acl001GrantCoverage,
    _has_owner_only_directive,
)
from confiture.core.linting.schema_linter import RuleSeverity


def _make_expectations() -> list[AclExpectation]:
    return [
        AclExpectation(
            schema="public",
            apply_to="ALL_TABLES",
            grants=[AclGrant(role="my_app", privileges=["SELECT", "INSERT"])],
        )
    ]


def _write_migration(tmp_path: Path, name: str, sql: str) -> Path:
    migration = tmp_path / name
    migration.write_text(sql)
    return migration


# ---------------------------------------------------------------------------
# Same-migration coverage
# ---------------------------------------------------------------------------


def test_table_with_matching_grant_in_same_migration(tmp_path: Path) -> None:
    _write_migration(
        tmp_path,
        "20260522120000_add_foo.up.sql",
        "CREATE TABLE foo (id int);\nGRANT SELECT, INSERT ON foo TO my_app;",
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    assert rule.check(tmp_path) == []


def test_table_with_partial_grant_in_same_migration_is_flagged(tmp_path: Path) -> None:
    _write_migration(
        tmp_path,
        "20260522120000_add_foo.up.sql",
        "CREATE TABLE foo (id int);\nGRANT SELECT ON foo TO my_app;",
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    violations = rule.check(tmp_path)
    assert len(violations) == 1
    assert violations[0].rule_id == "acl_001"
    assert violations[0].severity == RuleSeverity.ERROR
    assert "INSERT" in violations[0].message
    assert "my_app" in violations[0].message
    assert "foo" in violations[0].object_name


def test_table_without_grant_anywhere(tmp_path: Path) -> None:
    _write_migration(tmp_path, "20260522120000_add_foo.up.sql", "CREATE TABLE foo (id int);")
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    violations = rule.check(tmp_path)
    assert len(violations) == 1
    assert violations[0].rule_id == "acl_001"
    assert violations[0].severity == RuleSeverity.ERROR
    assert "my_app" in violations[0].message


# ---------------------------------------------------------------------------
# Global grant sweep
# ---------------------------------------------------------------------------


def test_table_covered_by_global_grant_sweep(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    _write_migration(
        migrations, "20260522120000_add_foo.up.sql", "CREATE TABLE foo (id int);"
    )
    grant_dir = tmp_path / "7_grant"
    grant_dir.mkdir()
    (grant_dir / "grants.sql").write_text(
        "GRANT SELECT, INSERT ON foo TO my_app;"
    )

    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=grant_dir)
    assert rule.check(migrations) == []


def test_grant_dir_missing_does_not_crash(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    _write_migration(
        migrations, "20260522120000_add_foo.up.sql", "CREATE TABLE foo (id int);"
    )
    rule = Acl001GrantCoverage(
        expectations=_make_expectations(), grant_dir=tmp_path / "does_not_exist"
    )
    violations = rule.check(migrations)
    # foo still uncovered, just no extra crash from the missing dir.
    assert len(violations) == 1


# ---------------------------------------------------------------------------
# Magic comment opt-out
# ---------------------------------------------------------------------------


def test_magic_comment_opts_out(tmp_path: Path) -> None:
    _write_migration(
        tmp_path,
        "20260522120000_add_audit.up.sql",
        "-- confiture:owner-only\nCREATE TABLE tb_audit_ledger (id int);",
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    assert rule.check(tmp_path) == []


def test_magic_comment_above_blank_line_still_opts_out(tmp_path: Path) -> None:
    """Magic comment + blank lines + comments between it and CREATE TABLE."""
    _write_migration(
        tmp_path,
        "20260522120000_add_audit.up.sql",
        "-- confiture:owner-only\n-- audit ledger, only the owner reads/writes\n\nCREATE TABLE tb_audit_ledger (id int);",
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    assert rule.check(tmp_path) == []


def test_magic_comment_far_above_does_not_opt_out(tmp_path: Path) -> None:
    """Magic comment separated from CREATE TABLE by non-comment SQL doesn't apply."""
    _write_migration(
        tmp_path,
        "20260522120000.up.sql",
        "-- confiture:owner-only\nSELECT 1;\nCREATE TABLE foo (id int);",
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    # foo gets no grants and the magic comment is detached → violation.
    assert len(rule.check(tmp_path)) == 1


# Standalone helper test — the docstring locks magic-comment semantics.
def test_has_owner_only_directive_helper() -> None:
    text = "-- confiture:owner-only\nCREATE TABLE foo (id int);"
    assert _has_owner_only_directive(text, table_line=2) is True
    assert _has_owner_only_directive(text, table_line=1) is False  # Above the comment.

    detached = "-- confiture:owner-only\nSELECT 1;\nCREATE TABLE foo (id int);"
    assert _has_owner_only_directive(detached, table_line=3) is False


# ---------------------------------------------------------------------------
# Drops within same migration net out
# ---------------------------------------------------------------------------


def test_table_created_then_dropped_in_same_migration_emits_no_violation(
    tmp_path: Path,
) -> None:
    _write_migration(
        tmp_path,
        "20260522120000.up.sql",
        "CREATE TABLE scratch (id int);\nDROP TABLE scratch;",
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    assert rule.check(tmp_path) == []


# ---------------------------------------------------------------------------
# Scope / out-of-scope
# ---------------------------------------------------------------------------


def test_table_outside_apply_to_pattern_is_not_checked(tmp_path: Path) -> None:
    """Pattern list filters which tables the rule applies to."""
    _write_migration(
        tmp_path, "20260522120000.up.sql", "CREATE TABLE skip_me (id int);"
    )
    rule = Acl001GrantCoverage(
        expectations=[
            AclExpectation(
                schema="public",
                apply_to=["tb_*"],  # skip_me doesn't match
                grants=[AclGrant(role="my_app", privileges=["SELECT"])],
            )
        ],
        grant_dir=None,
    )
    assert rule.check(tmp_path) == []


def test_ignore_globs_exempt_tables(tmp_path: Path) -> None:
    _write_migration(
        tmp_path,
        "20260522120000.up.sql",
        "CREATE TABLE tb_foo_legacy (id int);",
    )
    rule = Acl001GrantCoverage(
        expectations=[
            AclExpectation(
                schema="public",
                apply_to="ALL_TABLES",
                ignore=["*_legacy"],
                grants=[AclGrant(role="my_app", privileges=["SELECT"])],
            )
        ],
        grant_dir=None,
    )
    assert rule.check(tmp_path) == []


def test_table_in_unrelated_schema_is_ignored(tmp_path: Path) -> None:
    _write_migration(
        tmp_path, "20260522120000.up.sql", "CREATE TABLE other.foo (id int);"
    )
    rule = Acl001GrantCoverage(
        expectations=[
            AclExpectation(
                schema="public",
                apply_to="ALL_TABLES",
                grants=[AclGrant(role="my_app", privileges=["SELECT"])],
            )
        ],
        grant_dir=None,
    )
    # other.foo doesn't match the public expectation → no violation.
    assert rule.check(tmp_path) == []


# ---------------------------------------------------------------------------
# Empty config → no-op
# ---------------------------------------------------------------------------


def test_empty_expectations_emits_no_violations(tmp_path: Path) -> None:
    """If config has no acls: block, the rule never fires."""
    _write_migration(
        tmp_path, "20260522120000.up.sql", "CREATE TABLE foo (id int);"
    )
    rule = Acl001GrantCoverage(expectations=[], grant_dir=None)
    assert rule.check(tmp_path) == []


# ---------------------------------------------------------------------------
# Only *.up.sql migrations are scanned (down files ignored)
# ---------------------------------------------------------------------------


def test_down_files_are_not_scanned(tmp_path: Path) -> None:
    _write_migration(
        tmp_path,
        "20260522120000.up.sql",
        "CREATE TABLE foo (id int);\nGRANT SELECT, INSERT ON foo TO my_app;",
    )
    # A .down.sql with a CREATE TABLE shouldn't be considered.
    _write_migration(
        tmp_path, "20260522120000.down.sql", "CREATE TABLE ghost (id int);"
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    assert rule.check(tmp_path) == []


@pytest.mark.parametrize(
    "filename",
    [
        "20260522120000_add_foo.up.sql",
        "001_legacy_add_foo.up.sql",  # legacy numeric prefix
        "20260522120000.up.sql",  # bare timestamp
    ],
)
def test_handles_various_migration_filename_styles(
    tmp_path: Path, filename: str
) -> None:
    _write_migration(
        tmp_path,
        filename,
        "CREATE TABLE foo (id int);\nGRANT SELECT, INSERT ON foo TO my_app;",
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    assert rule.check(tmp_path) == []
