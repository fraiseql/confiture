"""Unit tests for FunctionSignatureChecker."""

from pathlib import Path
from unittest.mock import MagicMock

from confiture.core.function_signature_checker import (
    FunctionSignatureChecker,
)


def _make_checker(old_content: str | None, new_content: str | None) -> FunctionSignatureChecker:
    """Build a checker whose git_repo returns fixed content at refs."""
    git_repo = MagicMock()

    def show_at_ref(path, ref):
        if ref == "HEAD~1":
            return old_content
        return new_content

    git_repo.show_file_at_ref.side_effect = show_at_ref
    return FunctionSignatureChecker(git_repo)


OLD_INTEGER = "CREATE FUNCTION public.get_user(p_id INTEGER) RETURNS void AS $$ $$ LANGUAGE sql;"
NEW_BIGINT = "CREATE FUNCTION public.get_user(p_id BIGINT) RETURNS void AS $$ $$ LANGUAGE sql;"
OLD_SAME = OLD_INTEGER
NEW_SAME = OLD_INTEGER


class TestFunctionSignatureCheckerNoViolation:
    def test_no_violation_when_types_unchanged(self, tmp_path):
        checker = _make_checker(OLD_SAME, NEW_SAME)
        sql_file = Path("db/schema/functions.sql")
        violations = checker.check([sql_file], [], "HEAD~1", "HEAD")
        assert violations == []

    def test_no_violation_for_new_function(self, tmp_path):
        # Function not in old (None = file didn't exist) — not a violation
        checker = _make_checker(None, NEW_BIGINT)
        sql_file = Path("db/schema/functions.sql")
        violations = checker.check([sql_file], [], "HEAD~1", "HEAD")
        assert violations == []

    def test_no_violation_when_drop_present(self, tmp_path):
        # param types changed BUT migration has DROP FUNCTION(integer)
        mig = tmp_path / "001_change_sig.up.sql"
        mig.write_text("DROP FUNCTION public.get_user(integer);\n" + NEW_BIGINT)

        checker = _make_checker(OLD_INTEGER, NEW_BIGINT)
        violations = checker.check([Path("db/schema/f.sql")], [mig], "HEAD~1", "HEAD")
        assert violations == []

    def test_no_violation_when_function_deleted(self):
        # old had function, new doesn't (deletion) — not a violation
        checker = _make_checker(OLD_INTEGER, "-- no functions here")
        sql_file = Path("db/schema/functions.sql")
        violations = checker.check([sql_file], [], "HEAD~1", "HEAD")
        assert violations == []


class TestFunctionSignatureCheckerViolations:
    def test_violation_when_type_changed_no_drop(self):
        checker = _make_checker(OLD_INTEGER, NEW_BIGINT)
        sql_file = Path("db/schema/functions.sql")
        violations = checker.check([sql_file], [], "HEAD~1", "HEAD")
        assert len(violations) == 1
        v = violations[0]
        assert v.function_key == "public.get_user"
        assert "integer" in v.old_signature
        assert "bigint" in v.new_signature

    def test_violation_message_includes_old_and_new_signature(self):
        checker = _make_checker(OLD_INTEGER, NEW_BIGINT)
        violations = checker.check([Path("db/schema/f.sql")], [], "HEAD~1", "HEAD")
        assert len(violations) == 1
        assert "integer" in violations[0].old_signature
        assert "bigint" in violations[0].new_signature

    def test_multiple_violations_in_one_file(self):
        old_sql = """
        CREATE FUNCTION public.foo(x INTEGER) RETURNS void AS $$ $$ LANGUAGE sql;
        CREATE FUNCTION public.bar(y TEXT) RETURNS void AS $$ $$ LANGUAGE sql;
        """
        new_sql = """
        CREATE FUNCTION public.foo(x BIGINT) RETURNS void AS $$ $$ LANGUAGE sql;
        CREATE FUNCTION public.bar(y UUID) RETURNS void AS $$ $$ LANGUAGE sql;
        """
        checker = _make_checker(old_sql, new_sql)
        violations = checker.check([Path("db/schema/f.sql")], [], "HEAD~1", "HEAD")
        assert len(violations) == 2
        keys = {v.function_key for v in violations}
        assert keys == {"public.foo", "public.bar"}

    def test_violation_to_dict(self):
        checker = _make_checker(OLD_INTEGER, NEW_BIGINT)
        violations = checker.check([Path("db/schema/f.sql")], [], "HEAD~1", "HEAD")
        d = violations[0].to_dict()
        assert d["function_key"] == "public.get_user"
        assert "old_signature" in d
        assert "new_signature" in d
        assert "message" in d


class TestFunctionSignatureCheckerEdgeCases:
    def test_git_error_on_old_treated_as_new_function(self):
        from confiture.exceptions import GitError

        git_repo = MagicMock()
        git_repo.show_file_at_ref.side_effect = GitError("not found")
        checker = FunctionSignatureChecker(git_repo)
        violations = checker.check([Path("db/schema/f.sql")], [], "HEAD~1", "HEAD")
        assert violations == []

    def test_drop_with_schema_qualified_fn_matches(self, tmp_path):
        mig = tmp_path / "001.up.sql"
        mig.write_text("DROP FUNCTION IF EXISTS public.get_user(integer);")
        checker = _make_checker(OLD_INTEGER, NEW_BIGINT)
        violations = checker.check([Path("db/schema/f.sql")], [mig], "HEAD~1", "HEAD")
        assert violations == []
