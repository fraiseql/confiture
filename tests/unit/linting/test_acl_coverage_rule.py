"""Unit tests for the ACL coverage lint rule (issue #120).

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
    _write_migration(migrations, "20260522120000_add_foo.up.sql", "CREATE TABLE foo (id int);")
    grant_dir = tmp_path / "7_grant"
    grant_dir.mkdir()
    (grant_dir / "grants.sql").write_text("GRANT SELECT, INSERT ON foo TO my_app;")

    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=grant_dir)
    assert rule.check(migrations) == []


def test_grant_dir_missing_does_not_crash(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    _write_migration(migrations, "20260522120000_add_foo.up.sql", "CREATE TABLE foo (id int);")
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
    _write_migration(tmp_path, "20260522120000.up.sql", "CREATE TABLE skip_me (id int);")
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
    _write_migration(tmp_path, "20260522120000.up.sql", "CREATE TABLE other.foo (id int);")
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
    _write_migration(tmp_path, "20260522120000.up.sql", "CREATE TABLE foo (id int);")
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
    _write_migration(tmp_path, "20260522120000.down.sql", "CREATE TABLE ghost (id int);")
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
def test_handles_various_migration_filename_styles(tmp_path: Path, filename: str) -> None:
    _write_migration(
        tmp_path,
        filename,
        "CREATE TABLE foo (id int);\nGRANT SELECT, INSERT ON foo TO my_app;",
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    assert rule.check(tmp_path) == []


# ---------------------------------------------------------------------------
# Python-migration coverage (issue #162 twin gap — same blind spot as the
# grant-accompaniment gate)
# ---------------------------------------------------------------------------


def test_python_migration_create_with_grant_is_covered(tmp_path: Path) -> None:
    _write_migration(
        tmp_path,
        "20260613130000_add_foo.py",
        "from confiture import Migration\n"
        "class M(Migration):\n"
        "    def up(self):\n"
        "        self.execute('CREATE TABLE foo (id int);')\n"
        "        self.execute('GRANT SELECT, INSERT ON foo TO my_app;')\n",
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    assert rule.check(tmp_path) == []


def test_python_migration_create_without_grant_is_flagged(tmp_path: Path) -> None:
    _write_migration(
        tmp_path,
        "20260613130000_add_foo.py",
        "from confiture import Migration\n"
        "class M(Migration):\n"
        "    def up(self):\n"
        "        self.execute('CREATE TABLE foo (id int);')\n",
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    violations = rule.check(tmp_path)
    assert len(violations) >= 1


def test_python_init_and_private_modules_are_skipped(tmp_path: Path) -> None:
    # __init__.py / _-prefixed modules are package machinery, not migrations.
    _write_migration(tmp_path, "__init__.py", "")
    _write_migration(
        tmp_path,
        "_helpers.py",
        "x = 'CREATE TABLE ghost (id int);'\n",
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    assert rule.check(tmp_path) == []


# ---------------------------------------------------------------------------
# Owner-only directive — per-table scoping
#
# The directive must apply only to the immediately-following CREATE TABLE.
# Before phase 02 (issue #120) the implementation used substring containment
# inside a 200-character tail window; that leaked to adjacent and
# substring-prefix relnames.  The tests below pin the corrected scoping.
# ---------------------------------------------------------------------------


def test_owner_only_does_not_leak_to_short_relname(tmp_path: Path) -> None:
    """Directive on ``a_owner_only`` must NOT silence the adjacent ``b``."""
    _write_migration(
        tmp_path,
        "20260522120000.up.sql",
        (
            "-- confiture:owner-only\n"
            "CREATE TABLE a_owner_only (id int);\n"
            "CREATE TABLE b (id int);\n"
        ),
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    violations = rule.check(tmp_path)
    flagged = {v.object_name for v in violations}
    assert "public.b" in flagged
    assert "public.a_owner_only" not in flagged


def test_owner_only_does_not_leak_to_prefix_relname(tmp_path: Path) -> None:
    """Directive on ``tb_foo`` must NOT silence the adjacent ``tb_foobar``."""
    _write_migration(
        tmp_path,
        "20260522120000.up.sql",
        (
            "-- confiture:owner-only\n"
            "CREATE TABLE tb_foo (id int);\n"
            "CREATE TABLE tb_foobar (id int);\n"
        ),
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    violations = rule.check(tmp_path)
    flagged = {v.object_name for v in violations}
    assert "public.tb_foobar" in flagged
    assert "public.tb_foo" not in flagged


def test_owner_only_applies_to_immediately_following_table(tmp_path: Path) -> None:
    """Plain happy-path: directive above a CREATE TABLE opts that table out."""
    _write_migration(
        tmp_path,
        "20260522120000.up.sql",
        "-- confiture:owner-only\nCREATE TABLE my_table (id int);\n",
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    assert rule.check(tmp_path) == []


def test_owner_only_inline_does_not_opt_out(tmp_path: Path) -> None:
    """Inline directive after the CREATE TABLE is NOT recognized."""
    _write_migration(
        tmp_path,
        "20260522120000.up.sql",
        "CREATE TABLE foo (id int); -- confiture:owner-only\n",
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    violations = rule.check(tmp_path)
    assert any(v.object_name == "public.foo" for v in violations)


def test_owner_only_block_comment_does_not_opt_out(tmp_path: Path) -> None:
    """Block-comment form is NOT recognized — directive must be a -- line."""
    _write_migration(
        tmp_path,
        "20260522120000.up.sql",
        "/* confiture:owner-only */\nCREATE TABLE foo (id int);\n",
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    violations = rule.check(tmp_path)
    assert any(v.object_name == "public.foo" for v in violations)


# ---------------------------------------------------------------------------
# Declarative partitioning
#
# Partition children inherit grants from their partitioned parent; flagging
# them would be a false positive that multiplies with every new partition.
# The lint rule must look at the parent only.
# ---------------------------------------------------------------------------


def test_lint_does_not_flag_partition_children(tmp_path: Path) -> None:
    _write_migration(
        tmp_path,
        "20260522120000.up.sql",
        (
            "CREATE TABLE foo (id int, d date) PARTITION BY RANGE (d);\n"
            "GRANT SELECT, INSERT ON foo TO my_app;\n"
            "CREATE TABLE foo_2026 PARTITION OF foo "
            "FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');\n"
        ),
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    # The child must not be reported.  ``foo`` has full coverage.
    assert rule.check(tmp_path) == []


def test_lint_flags_partitioned_parent_without_grant(tmp_path: Path) -> None:
    _write_migration(
        tmp_path,
        "20260522120000.up.sql",
        (
            "CREATE TABLE foo (id int, d date) PARTITION BY RANGE (d);\n"
            "CREATE TABLE foo_2026 PARTITION OF foo "
            "FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');\n"
        ),
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    violations = rule.check(tmp_path)
    # Exactly one violation, on the parent ``foo`` (the child is excluded).
    assert {v.object_name for v in violations} == {"public.foo"}


# ---------------------------------------------------------------------------
# Lint auto-fire gating — Phase 03 opt-in
#
# ``SchemaLinter.lint()`` must NOT run ACL coverage when
# ``acls_lint_enabled`` is False, even if expectations are configured.
# ---------------------------------------------------------------------------


def test_schema_linter_skips_acl_rule_when_lint_disabled(tmp_path: Path) -> None:
    """SchemaLinter must not invoke ACL coverage with lint_enabled=False."""
    from unittest.mock import patch

    from confiture.config.environment import Environment
    from confiture.core.linting.schema_linter import LintConfig, SchemaLinter

    # Build a minimal project directory with the nested-shape acls block.
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "test.yaml").write_text(
        "database_url: postgresql://localhost/test\n"
        "include_dirs: []\n"
        "acls:\n"
        "  expectations:\n"
        "    - schema: public\n"
        "      apply_to: ALL_TABLES\n"
        "      grants:\n"
        "        - role: my_app\n"
        "          privileges: [SELECT]\n"
    )
    # Migration directory that WOULD produce a violation if checked.
    migrations = tmp_path / "db" / "migrations"
    migrations.mkdir()
    (migrations / "20260522120000.up.sql").write_text("CREATE TABLE uncovered (id int);")

    env = Environment.load("test", tmp_path)
    assert env.acls_lint_enabled is False  # confirms the gate

    linter = SchemaLinter(env="test", project_dir=tmp_path, config=LintConfig())
    # Skip the schema-load step (we only care about the ACL branch).
    with patch.object(linter, "_load_schema"):
        linter._schema_sql = "-- empty schema"
        report = linter.lint()

    # Zero ACL violations because the gate kept the rule off.
    assert all(v.rule_id != "acl_001" for v in report.errors)


def test_schema_linter_runs_acl_rule_when_lint_enabled(tmp_path: Path) -> None:
    """With ``lint_enabled: true``, the ACL rule runs and flags the gap."""
    from unittest.mock import patch

    from confiture.config.environment import Environment
    from confiture.core.linting.schema_linter import LintConfig, SchemaLinter

    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "test.yaml").write_text(
        "database_url: postgresql://localhost/test\n"
        "include_dirs: []\n"
        "acls:\n"
        "  lint_enabled: true\n"
        "  expectations:\n"
        "    - schema: public\n"
        "      apply_to: ALL_TABLES\n"
        "      grants:\n"
        "        - role: my_app\n"
        "          privileges: [SELECT]\n"
    )
    migrations = tmp_path / "db" / "migrations"
    migrations.mkdir()
    (migrations / "20260522120000.up.sql").write_text("CREATE TABLE uncovered (id int);")

    env = Environment.load("test", tmp_path)
    assert env.acls_lint_enabled is True

    linter = SchemaLinter(env="test", project_dir=tmp_path, config=LintConfig())
    with patch.object(linter, "_load_schema"):
        linter._schema_sql = "-- empty schema"
        report = linter.lint()

    acl_violations = [v for v in report.errors if v.rule_id == "acl_001"]
    assert len(acl_violations) >= 1


def test_owner_only_with_crlf_line_endings(tmp_path: Path) -> None:
    """The directive walk-back works on Windows-style ``\\r\\n`` line endings."""
    (tmp_path / "20260522120000.up.sql").write_bytes(
        b"-- confiture:owner-only\r\nCREATE TABLE foo (id int);\r\n"
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    assert rule.check(tmp_path) == []


def test_owner_only_case_insensitive(tmp_path: Path) -> None:
    """``-- CONFITURE:OWNER-ONLY`` (uppercase) still opts out."""
    _write_migration(
        tmp_path,
        "20260522120000.up.sql",
        "-- CONFITURE:OWNER-ONLY\nCREATE TABLE foo (id int);\n",
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    assert rule.check(tmp_path) == []


def test_owner_only_in_realistic_migration(tmp_path: Path) -> None:
    """Five-table sweep: directive on tables 2 and 4, expect 1, 3, 5 flagged."""
    _write_migration(
        tmp_path,
        "20260522120000.up.sql",
        (
            "CREATE TABLE one (id int);\n"
            "\n"
            "-- confiture:owner-only\n"
            "CREATE TABLE two (id int);\n"
            "\n"
            "CREATE TABLE three (id int);\n"
            "\n"
            "-- confiture:owner-only\n"
            "CREATE TABLE four (id int);\n"
            "\n"
            "CREATE TABLE five (id int);\n"
        ),
    )
    rule = Acl001GrantCoverage(expectations=_make_expectations(), grant_dir=None)
    flagged = {v.object_name for v in rule.check(tmp_path)}
    assert flagged == {"public.one", "public.three", "public.five"}
