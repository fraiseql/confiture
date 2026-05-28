"""Unit tests for the bare-ALTER-OWNER lint rule (issue #137 part 3).

``own_002`` walks each migration's CREATE and ALTER OWNER statements
and flags ``ALTER … OWNER TO <expected_owner>`` statements that target
objects the migration did not itself create.  Three severity tiers:

  1. Inside an ``IF EXISTS`` guard AND the migration is
     ``requires_superuser=True``  → silent (intended pattern).
  2. Inside an ``IF EXISTS`` guard but no companion
     ``requires_superuser=True``  → WARNING.
  3. Bare ``ALTER OWNER``, no guard                 → ERROR.

AST-only: when pglast is not installed, the rule emits a single skip
notice and returns no violations.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from confiture.config.environment import OwnershipApplyTo, OwnershipExpectation
from confiture.core.linting.libraries.ownership import Own002BareAlterOwner
from confiture.core.linting.schema_linter import RuleSeverity

pglast = pytest.importorskip("pglast")


def _make_expectation(owner: str = "migrator") -> OwnershipExpectation:
    return OwnershipExpectation(
        expected_owner=owner,
        apply_to=[OwnershipApplyTo(schema="tenant"), OwnershipApplyTo(schema="public")],
    )


def _write_migration(tmp_path: Path, name: str, sql: str) -> Path:
    p = tmp_path / name
    p.write_text(sql)
    return p


# ---------------------------------------------------------------------------
# Cycle 1: bare ALTER OWNER on non-created object → ERROR
# ---------------------------------------------------------------------------


def test_flags_bare_alter_owner_on_pre_existing_object(tmp_path: Path) -> None:
    _write_migration(
        tmp_path,
        "20260528170000_fix.up.sql",
        "ALTER TABLE tenant.tb_foo OWNER TO migrator;\n",
    )
    rule = Own002BareAlterOwner(expectation=_make_expectation())
    violations = rule.check(tmp_path)
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_id == "own_002"
    assert v.severity == RuleSeverity.ERROR
    assert "tenant.tb_foo" in v.object_name


# ---------------------------------------------------------------------------
# Cycle 2: don't flag when CREATE in same migration
# ---------------------------------------------------------------------------


def test_does_not_flag_when_create_in_same_migration(tmp_path: Path) -> None:
    _write_migration(
        tmp_path,
        "20260528170100_create_and_alter.up.sql",
        "CREATE TABLE tenant.tb_foo (id int);\n"
        "ALTER TABLE tenant.tb_foo OWNER TO migrator;\n",
    )
    rule = Own002BareAlterOwner(expectation=_make_expectation())
    assert rule.check(tmp_path) == []


# ---------------------------------------------------------------------------
# Cycle 3: IF EXISTS guard inside DO block → WARNING
# ---------------------------------------------------------------------------


def test_if_exists_guard_downgrades_to_warning(tmp_path: Path) -> None:
    sql = textwrap.dedent(
        """\
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'tb_foo') THEN
                EXECUTE 'ALTER TABLE tenant.tb_foo OWNER TO migrator';
            END IF;
        END $$;
        """
    )
    _write_migration(tmp_path, "20260528170200_guarded.up.sql", sql)
    rule = Own002BareAlterOwner(expectation=_make_expectation())
    violations = rule.check(tmp_path)
    assert len(violations) == 1
    v = violations[0]
    assert v.severity == RuleSeverity.WARNING
    assert "tenant.tb_foo" in v.object_name


# ---------------------------------------------------------------------------
# Cycle 4: companion `.py` requires_superuser=True suppresses
# ---------------------------------------------------------------------------


def test_requires_superuser_companion_suppresses_guarded_warning(
    tmp_path: Path,
) -> None:
    """Guarded ALTER OWNER + companion requires_superuser=True → no violation."""
    base = tmp_path / "20260528170300_guarded_su"
    sql_file = base.with_suffix(".up.sql")
    sql_file.write_text(
        textwrap.dedent(
            """\
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'tb_foo') THEN
                    EXECUTE 'ALTER TABLE tenant.tb_foo OWNER TO migrator';
                END IF;
            END $$;
            """
        )
    )
    py_file = base.with_suffix(".py")
    py_file.write_text(
        "from confiture.models.migration import Migration\n"
        "class M(Migration):\n"
        "    version = '20260528170300'\n"
        "    name = 'guarded_su'\n"
        "    requires_superuser = True\n"
        "    def up(self): pass\n"
        "    def down(self): pass\n"
    )
    rule = Own002BareAlterOwner(expectation=_make_expectation())
    assert rule.check(tmp_path) == []


def test_requires_superuser_companion_does_not_suppress_bare_error(
    tmp_path: Path,
) -> None:
    """Bare ALTER OWNER + companion requires_superuser=True → still ERROR.

    The author needs an IF EXISTS guard OR no ALTER OWNER at all. The
    requires_superuser flag tells confiture *who* runs it, not *how*
    safely the migration handles missing objects.
    """
    base = tmp_path / "20260528170400_bare_su"
    sql_file = base.with_suffix(".up.sql")
    sql_file.write_text("ALTER TABLE tenant.tb_foo OWNER TO migrator;\n")
    py_file = base.with_suffix(".py")
    py_file.write_text(
        "from confiture.models.migration import Migration\n"
        "class M(Migration):\n"
        "    version = '20260528170400'\n"
        "    name = 'bare_su'\n"
        "    requires_superuser = True\n"
        "    def up(self): pass\n"
        "    def down(self): pass\n"
    )
    rule = Own002BareAlterOwner(expectation=_make_expectation())
    violations = rule.check(tmp_path)
    assert len(violations) == 1
    assert violations[0].severity == RuleSeverity.ERROR


# ---------------------------------------------------------------------------
# Cycle 5: violation message includes copy-paste remediation
# ---------------------------------------------------------------------------


def test_violation_message_includes_remediation_for_bare_case(
    tmp_path: Path,
) -> None:
    _write_migration(
        tmp_path,
        "20260528170500_bare.up.sql",
        "ALTER TABLE tenant.tb_foo OWNER TO migrator;\n",
    )
    rule = Own002BareAlterOwner(expectation=_make_expectation())
    violations = rule.check(tmp_path)
    assert len(violations) == 1
    msg = violations[0].message
    assert "confiture bootstrap" in msg or "requires_superuser" in msg


def test_violation_message_includes_remediation_for_guarded_case(
    tmp_path: Path,
) -> None:
    sql = textwrap.dedent(
        """\
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'tb_foo') THEN
                EXECUTE 'ALTER TABLE tenant.tb_foo OWNER TO migrator';
            END IF;
        END $$;
        """
    )
    _write_migration(tmp_path, "20260528170600_guarded.up.sql", sql)
    rule = Own002BareAlterOwner(expectation=_make_expectation())
    violations = rule.check(tmp_path)
    assert len(violations) == 1
    msg = violations[0].message
    assert "requires_superuser = True" in msg


# ---------------------------------------------------------------------------
# Out-of-scope schema → not flagged
# ---------------------------------------------------------------------------


def test_out_of_scope_schema_not_flagged(tmp_path: Path) -> None:
    """ALTER OWNER on a schema outside `apply_to` produces no violation."""
    _write_migration(
        tmp_path,
        "20260528170700_other.up.sql",
        "ALTER TABLE analytics.tb_facts OWNER TO migrator;\n",
    )
    rule = Own002BareAlterOwner(expectation=_make_expectation())
    assert rule.check(tmp_path) == []


# ---------------------------------------------------------------------------
# Different owner → not flagged
# ---------------------------------------------------------------------------


def test_alter_owner_to_different_role_not_flagged(tmp_path: Path) -> None:
    """ALTER OWNER TO <not-expected_owner> is out of scope for own_002."""
    _write_migration(
        tmp_path,
        "20260528170800_other_owner.up.sql",
        "ALTER TABLE tenant.tb_foo OWNER TO some_other_role;\n",
    )
    rule = Own002BareAlterOwner(expectation=_make_expectation())
    assert rule.check(tmp_path) == []
