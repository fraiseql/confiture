"""Unit tests for FunctionSignatureChecker."""

from pathlib import Path

from confiture.core.function_signature_checker import (
    FunctionSignatureChecker,
    FunctionSignatureViolation,
)
from confiture.core.function_signature_drift import declared_routines


def _check(
    old: str | None, new: str | None, migrations: list[Path]
) -> list[FunctionSignatureViolation]:
    """The signature check between two trees, each given as its DDL (``None``: no routine)."""
    return FunctionSignatureChecker().check(
        declared_routines(old or ""), declared_routines(new or ""), migrations
    )


OLD_INTEGER = "CREATE FUNCTION public.get_user(p_id INTEGER) RETURNS void AS $$ $$ LANGUAGE sql;"
NEW_BIGINT = "CREATE FUNCTION public.get_user(p_id BIGINT) RETURNS void AS $$ $$ LANGUAGE sql;"
OLD_SAME = OLD_INTEGER
NEW_SAME = OLD_INTEGER


class TestFunctionSignatureCheckerNoViolation:
    def test_no_violation_when_types_unchanged(self, tmp_path):
        violations = _check(OLD_SAME, NEW_SAME, [])
        assert violations == []

    def test_no_violation_for_new_function(self, tmp_path):
        # Function not in old (None = file didn't exist) — not a violation
        violations = _check(None, NEW_BIGINT, [])
        assert violations == []

    def test_no_violation_when_drop_present(self, tmp_path):
        # param types changed BUT migration has DROP FUNCTION(integer)
        mig = tmp_path / "001_change_sig.up.sql"
        mig.write_text("DROP FUNCTION public.get_user(integer);\n" + NEW_BIGINT)

        violations = _check(OLD_INTEGER, NEW_BIGINT, [mig])
        assert violations == []

    def test_no_violation_when_function_deleted(self):
        # old had function, new doesn't (deletion) — not a violation
        violations = _check(OLD_INTEGER, "-- no functions here", [])
        assert violations == []


class TestFunctionSignatureCheckerViolations:
    def test_violation_when_type_changed_no_drop(self):
        violations = _check(OLD_INTEGER, NEW_BIGINT, [])
        assert len(violations) == 1
        v = violations[0]
        assert v.function_key == "public.get_user"
        assert "integer" in v.old_signature
        assert "bigint" in v.new_signature

    def test_violation_message_includes_old_and_new_signature(self):
        violations = _check(OLD_INTEGER, NEW_BIGINT, [])
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
        violations = _check(old_sql, new_sql, [])
        assert len(violations) == 2
        keys = {v.function_key for v in violations}
        assert keys == {"public.foo", "public.bar"}

    def test_violation_to_dict(self):
        violations = _check(OLD_INTEGER, NEW_BIGINT, [])
        d = violations[0].to_dict()
        assert d["function_key"] == "public.get_user"
        assert "old_signature" in d
        assert "new_signature" in d
        assert "message" in d


class TestFunctionSignatureCheckerEdgeCases:
    def test_a_tree_without_the_routine_is_an_empty_side(self):
        assert FunctionSignatureChecker().check([], declared_routines(NEW_BIGINT), []) == []

    def test_drop_with_schema_qualified_fn_matches(self, tmp_path):
        mig = tmp_path / "001.up.sql"
        mig.write_text("DROP FUNCTION IF EXISTS public.get_user(integer);")
        violations = _check(OLD_INTEGER, NEW_BIGINT, [mig])
        assert violations == []


def _f(arg: str) -> str:
    return f"CREATE FUNCTION public.f(p {arg}) RETURNS void AS $$ $$ LANGUAGE sql;\n"


class TestOverloads:
    def test_an_added_overload_is_not_a_retype(self):
        assert _check(_f("integer"), _f("integer") + _f("text"), []) == []

    def test_a_dropped_overload_beside_a_kept_one_is_the_accompaniment_checks(self):
        assert _check(_f("integer") + _f("text"), _f("text"), []) == []

    def test_each_retyped_overload_is_reported(self):
        violations = _check(_f("integer") + _f("text"), _f("bigint") + _f("varchar"), [])
        assert [(v.old_signature, v.new_signature) for v in violations] == [
            ("public.f(integer)", "public.f(bigint)"),
            ("public.f(text)", "public.f(character varying)"),
        ]

    def test_a_name_that_gained_fewer_pairs_the_rest_with_its_last(self):
        violations = _check(_f("integer") + _f("text"), _f("bigint"), [])
        assert [(v.old_signature, v.new_signature) for v in violations] == [
            ("public.f(integer)", "public.f(bigint)"),
            ("public.f(text)", "public.f(bigint)"),
        ]

    def test_routines_of_two_files_pair_across_them(self):
        old = declared_routines(_f("integer"))
        new = declared_routines("CREATE TABLE t (id int);\n") + declared_routines(_f("bigint"))
        violations = FunctionSignatureChecker().check(old, new, [])
        assert [v.old_signature for v in violations] == ["public.f(integer)"]


class TestBareDrop:
    def test_a_bare_drop_excuses_the_sole_routine_of_its_name(self, tmp_path):
        mig = tmp_path / "001.up.sql"
        mig.write_text("DROP FUNCTION public.f;\n" + _f("bigint"))
        assert _check(_f("integer"), _f("bigint"), [mig]) == []

    def test_a_bare_drop_does_not_excuse_one_of_two_overloads(self, tmp_path):
        # PostgreSQL refuses it: "function name "public.f" is not unique".
        mig = tmp_path / "001.up.sql"
        mig.write_text("DROP FUNCTION public.f;\n" + _f("bigint"))
        violations = _check(_f("integer") + _f("text"), _f("bigint") + _f("text"), [mig])
        assert [v.old_signature for v in violations] == ["public.f(integer)"]
