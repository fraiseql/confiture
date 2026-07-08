"""Unit tests for FunctionBodyChecker (#178).

Mirrors ``test_function_signature_checker.py``. The checker is git-based and
static (no DB): it compares function *bodies* between two refs and requires a
body change to be carried by a migration that re-defines the function.
"""

from pathlib import Path
from unittest.mock import MagicMock

from confiture.core.function_body_checker import (
    FunctionBodyChecker,
    FunctionBodyViolation,
)


def _make_checker(old_content: str | None, new_content: str | None) -> FunctionBodyChecker:
    """Build a checker whose git_repo returns fixed content at refs."""
    git_repo = MagicMock()

    def show_at_ref(path, ref):
        return old_content if ref == "HEAD~1" else new_content

    git_repo.show_file_at_ref.side_effect = show_at_ref
    return FunctionBodyChecker(git_repo)


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
        checker = _make_checker(OLD, OLD)
        assert checker.check([Path("db/schema/f.sql")], [], "HEAD~1", "HEAD") == []

    def test_body_change_only_in_formatting_is_not_drift(self):
        """Comment/whitespace/case-only change must not count as a body change."""
        checker = _make_checker(OLD, NEW_SAME_LOGIC_DIFF_FORMAT)
        assert checker.check([Path("db/schema/f.sql")], [], "HEAD~1", "HEAD") == []

    def test_new_function_is_not_a_body_violation(self):
        # Function absent in old ref — creation, handled by coarse accompaniment.
        checker = _make_checker(None, NEW_CHANGED)
        assert checker.check([Path("db/schema/f.sql")], [], "HEAD~1", "HEAD") == []

    def test_deleted_function_is_not_a_body_violation(self):
        checker = _make_checker(OLD, "-- no functions")
        assert checker.check([Path("db/schema/f.sql")], [], "HEAD~1", "HEAD") == []

    def test_body_change_with_carrying_migration_is_clean(self, tmp_path):
        mig = tmp_path / "20260708_fix.up.sql"
        mig.write_text(_fn("SELECT p_id * 2"))  # migration re-defines the function
        checker = _make_checker(OLD, NEW_CHANGED)
        violations = checker.check([Path("db/schema/f.sql")], [mig], "HEAD~1", "HEAD")
        assert violations == []

    def test_carrying_migration_may_be_a_python_file(self, tmp_path):
        mig = tmp_path / "20260708_fix.py"
        mig.write_text(
            "def up(self):\n"
            '    self.execute("""CREATE OR REPLACE FUNCTION public.calc(p_id integer) '
            'RETURNS numeric LANGUAGE sql AS $b$ SELECT p_id * 2 $b$;""")\n'
        )
        checker = _make_checker(OLD, NEW_CHANGED)
        assert checker.check([Path("db/schema/f.sql")], [mig], "HEAD~1", "HEAD") == []

    def test_signature_change_is_not_a_body_violation(self):
        """A param-type change is a different overload — signature checker's job."""
        old = (
            "CREATE FUNCTION public.calc(p_id integer) RETURNS void AS $$ SELECT 1 $$ LANGUAGE sql;"
        )
        new = (
            "CREATE FUNCTION public.calc(p_id bigint) RETURNS void AS $$ SELECT 2 $$ LANGUAGE sql;"
        )
        checker = _make_checker(old, new)
        assert checker.check([Path("db/schema/f.sql")], [], "HEAD~1", "HEAD") == []

    def test_c_language_none_body_skipped(self):
        old = "CREATE FUNCTION public.f() RETURNS int AS 'symbol_a' LANGUAGE c;"
        new = "CREATE FUNCTION public.f() RETURNS int AS 'symbol_b' LANGUAGE c;"
        checker = _make_checker(old, new)
        # bodies are None (C) → cannot compare → not a violation
        assert checker.check([Path("db/schema/f.sql")], [], "HEAD~1", "HEAD") == []


class TestViolation:
    def test_body_change_without_migration_is_violation(self):
        checker = _make_checker(OLD, NEW_CHANGED)
        violations = checker.check([Path("db/schema/f.sql")], [], "HEAD~1", "HEAD")
        assert len(violations) == 1
        v = violations[0]
        assert isinstance(v, FunctionBodyViolation)
        assert v.function_key == "public.calc"
        assert v.signature_key == "public.calc(integer)"
        assert v.migration_file is None

    def test_violation_carries_unified_diff(self):
        checker = _make_checker(OLD, NEW_CHANGED)
        v = checker.check([Path("db/schema/f.sql")], [], "HEAD~1", "HEAD")[0]
        assert "-select p_id * 1" in v.unified_diff
        assert "+select p_id * 2" in v.unified_diff

    def test_violation_to_dict_shape(self):
        checker = _make_checker(OLD, NEW_CHANGED)
        v = checker.check([Path("db/schema/f.sql")], [], "HEAD~1", "HEAD")[0]
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
        checker = _make_checker(OLD, NEW_CHANGED)
        violations = checker.check([Path("db/schema/f.sql")], [mig], "HEAD~1", "HEAD")
        assert len(violations) == 1
