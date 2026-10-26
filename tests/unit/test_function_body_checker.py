"""Unit tests for FunctionBodyChecker (#178).

Mirrors ``test_function_signature_checker.py``. The checker is static (no DB):
it compares function *bodies* between the routines of two trees and requires a
body change to be carried by a migration that re-defines the function.
"""

from pathlib import Path

from confiture.core.function_body_checker import (
    FunctionBodyChecker,
    FunctionBodyViolation,
)
from confiture.core.function_signature_drift import declared_routines


def _check(old: str | None, new: str | None, migrations: list[Path]) -> list[FunctionBodyViolation]:
    """The body check between two trees, each given as its DDL (``None``: no routine)."""
    return FunctionBodyChecker().check(
        declared_routines(old or ""), declared_routines(new or ""), migrations
    )


def _fn(body: str) -> str:
    return (
        f"CREATE OR REPLACE FUNCTION public.calc(p_id integer) RETURNS numeric\n"
        f"LANGUAGE sql AS $$ {body} $$;"
    )


OLD = _fn("SELECT p_id * 1")
NEW_SAME_LOGIC_DIFF_FORMAT = _fn("select   p_id * 1  -- unchanged\n")
NEW_CHANGED = _fn("SELECT p_id * 2")


class TestNoViolation:
    def test_unchanged_body(self):
        assert _check(OLD, OLD, []) == []

    def test_body_change_only_in_formatting_is_not_drift(self):
        """Comment/whitespace/case-only change must not count as a body change."""
        assert _check(OLD, NEW_SAME_LOGIC_DIFF_FORMAT, []) == []

    def test_new_function_is_not_a_body_violation(self):
        # Function absent in old ref — creation, handled by coarse accompaniment.
        assert _check(None, NEW_CHANGED, []) == []

    def test_deleted_function_is_not_a_body_violation(self):
        assert _check(OLD, "-- no functions", []) == []

    def test_body_change_with_carrying_migration_is_clean(self, tmp_path):
        mig = tmp_path / "20260708_fix.up.sql"
        mig.write_text(_fn("SELECT p_id * 2"))  # migration re-defines the function
        violations = _check(OLD, NEW_CHANGED, [mig])
        assert violations == []

    def test_carrying_migration_may_be_a_python_file(self, tmp_path):
        mig = tmp_path / "20260708_fix.py"
        mig.write_text(
            "def up(self):\n"
            '    self.execute("""CREATE OR REPLACE FUNCTION public.calc(p_id integer) '
            'RETURNS numeric LANGUAGE sql AS $b$ SELECT p_id * 2 $b$;""")\n'
        )
        assert _check(OLD, NEW_CHANGED, [mig]) == []

    def test_signature_change_is_not_a_body_violation(self):
        """A param-type change is a different overload — signature checker's job."""
        old = (
            "CREATE FUNCTION public.calc(p_id integer) RETURNS void AS $$ SELECT 1 $$ LANGUAGE sql;"
        )
        new = (
            "CREATE FUNCTION public.calc(p_id bigint) RETURNS void AS $$ SELECT 2 $$ LANGUAGE sql;"
        )
        assert _check(old, new, []) == []

    def test_c_language_none_body_skipped(self):
        old = "CREATE FUNCTION public.f() RETURNS int AS 'symbol_a' LANGUAGE c;"
        new = "CREATE FUNCTION public.f() RETURNS int AS 'symbol_b' LANGUAGE c;"
        # bodies are None (C) → cannot compare → not a violation
        assert _check(old, new, []) == []


class TestViolation:
    def test_body_change_without_migration_is_violation(self):
        violations = _check(OLD, NEW_CHANGED, [])
        assert len(violations) == 1
        v = violations[0]
        assert isinstance(v, FunctionBodyViolation)
        assert v.function_key == "public.calc"
        assert v.signature_key == "public.calc(integer)"
        assert v.migration_file is None

    def test_violation_carries_unified_diff(self):
        v = _check(OLD, NEW_CHANGED, [])[0]
        assert "-select p_id * 1" in v.unified_diff
        assert "+select p_id * 2" in v.unified_diff

    def test_violation_to_dict_shape(self):
        v = _check(OLD, NEW_CHANGED, [])[0]
        d = v.to_dict()
        assert d["function_key"] == "public.calc"
        assert d["signature_key"] == "public.calc(integer)"
        assert d["migration_file"] is None
        assert "unified_diff" in d
        assert "message" in d

    def test_unrelated_migration_does_not_carry_the_change(self, tmp_path):
        mig = tmp_path / "20260708_other.up.sql"
        mig.write_text(
            "CREATE OR REPLACE FUNCTION public.other() RETURNS void AS $$ $$ LANGUAGE sql;"
        )
        violations = _check(OLD, NEW_CHANGED, [mig])
        assert len(violations) == 1
