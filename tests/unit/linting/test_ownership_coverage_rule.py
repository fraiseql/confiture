"""Unit tests for the ownership coverage lint rule (issue #124).

The rule walks a migrations directory and verifies that every
``CREATE { TABLE | VIEW | MATERIALIZED VIEW | SEQUENCE }`` is paired with
an ``ALTER … OWNER TO <expected_owner>`` later in the same file (or the
file declares ``-- confiture:run-as <expected_owner>`` front-matter).

AST-only: when pglast is not installed, the rule emits a skip notice and
returns an empty violation list — see :mod:`tests.unit.linting.test_ownership_pglast_absent`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.config.environment import OwnershipApplyTo, OwnershipExpectation
from confiture.core.linting.libraries.ownership import Own001OwnershipCoverage
from confiture.core.linting.schema_linter import RuleSeverity

# Mark the entire module as requiring pglast.  The skip-when-absent path
# has its own dedicated test file.
pglast = pytest.importorskip("pglast")


def _make_expectation(owner: str = "migrator") -> OwnershipExpectation:
    return OwnershipExpectation(
        expected_owner=owner,
        apply_to=[OwnershipApplyTo(schema="public", relkinds=["r", "S", "v", "m"])],
    )


def _write(tmp_path: Path, name: str, sql: str) -> Path:
    p = tmp_path / name
    p.write_text(sql)
    return p


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_create_table_with_matching_alter_owner_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n"
        "ALTER TABLE public.foo OWNER TO migrator;\n",
    )
    rule = Own001OwnershipCoverage(expectation=_make_expectation())
    assert rule.check(tmp_path) == []


# ---------------------------------------------------------------------------
# Missing ALTER OWNER — flagged for every relkind in scope
# ---------------------------------------------------------------------------


def test_create_table_without_alter_owner_violates_own_001(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )
    rule = Own001OwnershipCoverage(expectation=_make_expectation())
    violations = rule.check(tmp_path)
    assert len(violations) == 1
    assert violations[0].rule_id == "own_001"
    assert violations[0].severity == RuleSeverity.ERROR
    assert "public.foo" in violations[0].object_name
    assert "migrator" in violations[0].message


def test_create_view_requires_alter_owner(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_add_view.up.sql",
        "CREATE TABLE public.t (id int);\n"
        "ALTER TABLE public.t OWNER TO migrator;\n"
        "CREATE VIEW public.v AS SELECT id FROM public.t;\n",
    )
    rule = Own001OwnershipCoverage(expectation=_make_expectation())
    violations = rule.check(tmp_path)
    assert any("public.v" in v.object_name for v in violations)


def test_create_materialized_view_requires_alter_owner(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_add_mv.up.sql",
        "CREATE TABLE public.t (id int);\n"
        "ALTER TABLE public.t OWNER TO migrator;\n"
        "CREATE MATERIALIZED VIEW public.mv AS SELECT id FROM public.t;\n",
    )
    rule = Own001OwnershipCoverage(expectation=_make_expectation())
    violations = rule.check(tmp_path)
    assert any("public.mv" in v.object_name for v in violations)


def test_create_sequence_requires_alter_owner(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_add_seq.up.sql",
        "CREATE SEQUENCE public.s;\n",
    )
    rule = Own001OwnershipCoverage(expectation=_make_expectation())
    violations = rule.check(tmp_path)
    assert any("public.s" in v.object_name for v in violations)


# ---------------------------------------------------------------------------
# Cross-relkind matching: ALTER must apply to the same qualified name
# ---------------------------------------------------------------------------


def test_alter_owner_on_different_table_does_not_satisfy(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n"
        "CREATE TABLE public.bar (id int);\n"
        "ALTER TABLE public.bar OWNER TO migrator;\n",
    )
    rule = Own001OwnershipCoverage(expectation=_make_expectation())
    violations = rule.check(tmp_path)
    assert len(violations) == 1
    assert "public.foo" in violations[0].object_name


# ---------------------------------------------------------------------------
# Apply_to scope: relkinds outside the scope are not flagged
# ---------------------------------------------------------------------------


def test_table_outside_apply_to_relkinds_not_flagged(tmp_path: Path) -> None:
    """When ``relkinds: [S]`` only, a missing ALTER OWNER on a table is ignored."""
    _write(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )
    expectation = OwnershipExpectation(
        expected_owner="migrator",
        apply_to=[OwnershipApplyTo(schema="public", relkinds=["S"])],
    )
    rule = Own001OwnershipCoverage(expectation=expectation)
    assert rule.check(tmp_path) == []


def test_schema_outside_apply_to_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE other.foo (id int);\n",
    )
    rule = Own001OwnershipCoverage(expectation=_make_expectation())
    assert rule.check(tmp_path) == []


# ---------------------------------------------------------------------------
# Ignore list
# ---------------------------------------------------------------------------


def test_ignore_list_suppresses_violation(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_legacy.up.sql",
        "CREATE TABLE public.legacy (id int);\n",
    )
    expectation = OwnershipExpectation(
        expected_owner="migrator",
        apply_to=[OwnershipApplyTo(schema="public")],
        ignore=["public.legacy"],
    )
    rule = Own001OwnershipCoverage(expectation=expectation)
    assert rule.check(tmp_path) == []


# ---------------------------------------------------------------------------
# Directives
# ---------------------------------------------------------------------------


def test_owner_skip_directive_suppresses_violation(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_ext.up.sql",
        "-- confiture:owner-skip  (intentional: extension-owned)\n"
        "CREATE TABLE public.ext_tab (id int);\n",
    )
    rule = Own001OwnershipCoverage(expectation=_make_expectation())
    assert rule.check(tmp_path) == []


def test_run_as_directive_skips_whole_file_when_role_matches(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_run_as.up.sql",
        "-- confiture:run-as migrator\n"
        "CREATE TABLE public.foo (id int);\n",
    )
    rule = Own001OwnershipCoverage(expectation=_make_expectation())
    assert rule.check(tmp_path) == []


def test_run_as_directive_with_wrong_role_does_not_skip(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_run_as.up.sql",
        "-- confiture:run-as some_other_role\n"
        "CREATE TABLE public.foo (id int);\n",
    )
    rule = Own001OwnershipCoverage(expectation=_make_expectation())
    violations = rule.check(tmp_path)
    assert len(violations) == 1


# ---------------------------------------------------------------------------
# AST-only behaviour
# ---------------------------------------------------------------------------


def test_alter_owner_inside_do_block_does_not_count(tmp_path: Path) -> None:
    """A top-level ALTER OWNER must satisfy the rule — one inside DO does not."""
    _write(
        tmp_path,
        "20260527090000_do_block.up.sql",
        "CREATE TABLE public.foo (id int);\n"
        "DO $$ BEGIN EXECUTE 'ALTER TABLE public.foo OWNER TO migrator'; END $$;\n",
    )
    rule = Own001OwnershipCoverage(expectation=_make_expectation())
    violations = rule.check(tmp_path)
    assert len(violations) == 1
    assert "public.foo" in violations[0].object_name


def test_create_in_string_literal_does_not_trigger(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_log.up.sql",
        "CREATE TABLE public.log (entry text);\n"
        "ALTER TABLE public.log OWNER TO migrator;\n"
        "INSERT INTO public.log (entry) VALUES ('CREATE TABLE x (id int)');\n",
    )
    rule = Own001OwnershipCoverage(expectation=_make_expectation())
    assert rule.check(tmp_path) == []


# ---------------------------------------------------------------------------
# Lint disabled
# ---------------------------------------------------------------------------


def test_lint_disabled_is_no_op(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )
    expectation = OwnershipExpectation(
        expected_owner="migrator",
        apply_to=[OwnershipApplyTo(schema="public")],
        lint_enabled=False,
    )
    rule = Own001OwnershipCoverage(expectation=expectation)
    assert rule.check(tmp_path) == []


# ---------------------------------------------------------------------------
# Default-schema CREATE (no qualifier) — assumed to live in ``public``
# ---------------------------------------------------------------------------


def test_unqualified_create_treated_as_public(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_unq.up.sql",
        "CREATE TABLE foo (id int);\nALTER TABLE foo OWNER TO migrator;\n",
    )
    rule = Own001OwnershipCoverage(expectation=_make_expectation())
    assert rule.check(tmp_path) == []


def test_unqualified_create_without_alter_owner_is_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_unq.up.sql",
        "CREATE TABLE foo (id int);\n",
    )
    rule = Own001OwnershipCoverage(expectation=_make_expectation())
    violations = rule.check(tmp_path)
    assert len(violations) == 1
    assert "foo" in violations[0].object_name
