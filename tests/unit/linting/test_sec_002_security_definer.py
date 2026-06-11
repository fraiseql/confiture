"""Unit tests for the sec_002 security-definer/search_path lint rule (issue #161)."""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.core.linting.libraries.security_definer import Sec002SecurityDefinerSearchPath
from confiture.core.linting.schema_linter import RuleSeverity

pglast = pytest.importorskip("pglast")


def _make_rule(
    *,
    apply_to: list[str] | None = None,
    ignore: list[str] | None = None,
    severity: RuleSeverity = RuleSeverity.WARNING,
) -> Sec002SecurityDefinerSearchPath:
    return Sec002SecurityDefinerSearchPath(
        apply_to=apply_to,
        ignore=ignore,
        severity=severity,
    )


def _write(tmp_path: Path, name: str, sql: str) -> Path:
    p = tmp_path / name
    p.write_text(sql)
    return p


# ---------------------------------------------------------------------------
# Cycle 1: "pinned" predicate
# ---------------------------------------------------------------------------


def test_unpinned_definer_flagged(tmp_path: Path) -> None:
    """SECURITY DEFINER without SET search_path → violation."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION public.risky() RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$ BEGIN END $$;\n",
    )
    rule = _make_rule()
    violations = rule.check([f])
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_id == "sec_002"
    assert v.object_name == "public.risky"
    assert v.severity == RuleSeverity.WARNING


def test_pinned_set_value_not_flagged(tmp_path: Path) -> None:
    """SET search_path = pg_catalog, public → pinned, no violation."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION public.safe1() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER SET search_path = pg_catalog, public AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([f])
    assert violations == []


def test_pinned_from_current_not_flagged(tmp_path: Path) -> None:
    """SET search_path FROM CURRENT → pinned (VAR_SET_CURRENT=2), no violation."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION public.safe2() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER SET search_path FROM CURRENT AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([f])
    assert violations == []


def test_reset_search_path_not_pinned(tmp_path: Path) -> None:
    """RESET search_path does NOT pin → violation."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION public.bad_reset() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER RESET search_path AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([f])
    assert len(violations) == 1


def test_invoker_not_flagged(tmp_path: Path) -> None:
    """SECURITY INVOKER → never flagged."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION public.invoker_fn() RETURNS void LANGUAGE plpgsql "
        "SECURITY INVOKER AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([f])
    assert violations == []


def test_no_security_clause_not_flagged(tmp_path: Path) -> None:
    """No security clause → defaults to INVOKER, never flagged."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION public.normal_fn() RETURNS void LANGUAGE plpgsql AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([f])
    assert violations == []


def test_mixed_set_options_with_search_path_not_flagged(tmp_path: Path) -> None:
    """Multiple SET options including search_path → pinned, no violation."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION public.mixed() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER "
        "SET search_path = public, pg_catalog "
        "AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([f])
    assert violations == []


def test_pinned_definer_not_flagged(tmp_path: Path) -> None:
    """Properly pinned SECURITY DEFINER → clean."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE OR REPLACE FUNCTION public.clean_fn() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER SET search_path = '' AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([f])
    assert violations == []


# ---------------------------------------------------------------------------
# Cycle 2: statement extraction — procedure, OR REPLACE, line numbers
# ---------------------------------------------------------------------------


def test_procedure_flagged(tmp_path: Path) -> None:
    """CREATE PROCEDURE with SECURITY DEFINER and no search_path → violation."""
    f = _write(
        tmp_path,
        "p.sql",
        "CREATE PROCEDURE public.risky_proc() LANGUAGE plpgsql SECURITY DEFINER AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([f])
    assert len(violations) == 1
    v = violations[0]
    assert v.object_type == "procedure"
    assert v.object_name == "public.risky_proc"


def test_or_replace_flagged(tmp_path: Path) -> None:
    """CREATE OR REPLACE FUNCTION with SECURITY DEFINER → flagged."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE OR REPLACE FUNCTION public.replaced() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([f])
    assert len(violations) == 1


def test_qualified_schema_in_violation(tmp_path: Path) -> None:
    """Qualified schema.name appears in object_name."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION myschema.dangerous() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([f])
    assert len(violations) == 1
    assert violations[0].object_name == "myschema.dangerous"


def test_unqualified_name_defaults_to_public(tmp_path: Path) -> None:
    """Unqualified function name → schema defaults to public."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION bare_definer() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([f])
    assert len(violations) == 1
    assert violations[0].object_name == "public.bare_definer"


def test_line_number_in_violation(tmp_path: Path) -> None:
    """line_number is accurate."""
    sql = (
        "-- comment line 1\n"
        "-- comment line 2\n"
        "CREATE FUNCTION public.risky() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n"
    )
    f = _write(tmp_path, "f.sql", sql)
    violations = _make_rule().check([f])
    assert len(violations) == 1
    assert violations[0].line_number == 3


def test_severity_error_propagated(tmp_path: Path) -> None:
    """Injected severity=ERROR appears on the violation."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION public.risky() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule(severity=RuleSeverity.ERROR).check([f])
    assert violations[0].severity == RuleSeverity.ERROR


def test_file_path_in_violation(tmp_path: Path) -> None:
    """file_path on the violation matches the scanned file."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION public.risky() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([f])
    assert violations[0].file_path == str(f)


# ---------------------------------------------------------------------------
# Cycle 3: scoping, directives, robustness
# ---------------------------------------------------------------------------


def test_ignore_pattern_excludes(tmp_path: Path) -> None:
    """Ignored glob suppresses violation."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION public.risky() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule(ignore=["public.risky"]).check([f])
    assert violations == []


def test_ignore_wildcard_excludes(tmp_path: Path) -> None:
    """Wildcard ignore glob suppresses all functions in that schema."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION legacy.fn() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule(ignore=["legacy.*"]).check([f])
    assert violations == []


def test_apply_to_limits_schemas(tmp_path: Path) -> None:
    """apply_to pattern excludes schemas that don't match."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION other.fn() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule(apply_to=["public"]).check([f])
    assert violations == []


def test_pg_catalog_always_skipped(tmp_path: Path) -> None:
    """pg_catalog schema is always skipped regardless of apply_to."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION pg_catalog.fn() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule(apply_to=["*"]).check([f])
    assert violations == []


def test_information_schema_always_skipped(tmp_path: Path) -> None:
    """information_schema is always skipped."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION information_schema.fn() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule(apply_to=["*"]).check([f])
    assert violations == []


def test_directive_suppresses_violation(tmp_path: Path) -> None:
    """-- confiture:secdef-allow-unpinned above CREATE suppresses that function."""
    sql = (
        "-- confiture:secdef-allow-unpinned\n"
        "CREATE FUNCTION public.known_ok() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n"
    )
    f = _write(tmp_path, "f.sql", sql)
    violations = _make_rule().check([f])
    assert violations == []


def test_directive_only_suppresses_next_function(tmp_path: Path) -> None:
    """Directive attached to one CREATE does not suppress a later CREATE."""
    sql = (
        "-- confiture:secdef-allow-unpinned\n"
        "CREATE FUNCTION public.allowed() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n"
        "\n"
        "CREATE FUNCTION public.not_allowed() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n"
    )
    f = _write(tmp_path, "f.sql", sql)
    violations = _make_rule().check([f])
    assert len(violations) == 1
    assert violations[0].object_name == "public.not_allowed"


def test_unparseable_file_skipped_gracefully(tmp_path: Path) -> None:
    """Unparseable SQL yields no violations (no crash)."""
    f = _write(tmp_path, "bad.sql", "THIS IS NOT SQL $$$$$$$$;\n")
    violations = _make_rule().check([f])
    assert violations == []


def test_missing_path_returns_empty() -> None:
    """A non-existent path is silently ignored."""
    violations = _make_rule().check([Path("/no/such/path")])
    assert violations == []


def test_directory_scan_finds_nested_files(tmp_path: Path) -> None:
    """Directories are scanned recursively."""
    sub = tmp_path / "sub"
    sub.mkdir()
    _write(
        sub,
        "nested.sql",
        "CREATE FUNCTION public.nested() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([tmp_path])
    assert len(violations) == 1


def test_multiple_violations_from_one_file(tmp_path: Path) -> None:
    """Multiple unpinned SECURITY DEFINER functions in one file → multiple violations."""
    sql = (
        "CREATE FUNCTION public.fn1() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n"
        "CREATE FUNCTION public.fn2() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n"
        "CREATE FUNCTION public.fn3() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER SET search_path = public AS $$ BEGIN END $$;\n"
    )
    f = _write(tmp_path, "multi.sql", sql)
    violations = _make_rule().check([f])
    assert len(violations) == 2
    names = {v.object_name for v in violations}
    assert names == {"public.fn1", "public.fn2"}


def test_message_references_cve(tmp_path: Path) -> None:
    """Violation message references CVE-2018-1058."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION public.risky() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([f])
    assert "CVE-2018-1058" in violations[0].message


# ---------------------------------------------------------------------------
# Cycle 8: suggested_fix and emit_remediation
# ---------------------------------------------------------------------------


def test_suggested_fix_populated_for_no_args(tmp_path: Path) -> None:
    """Unpinned zero-arg function has a suggested ALTER FUNCTION fix."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION public.risky() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([f])
    assert len(violations) == 1
    fix = violations[0].suggested_fix
    assert fix is not None
    assert "ALTER FUNCTION" in fix
    assert "search_path" in fix
    assert "public.risky()" in fix


def test_suggested_fix_includes_param_types(tmp_path: Path) -> None:
    """Suggested fix reproduces the parameter type list."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION public.risky(x integer, y text) RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([f])
    assert len(violations) == 1
    fix = violations[0].suggested_fix
    assert fix is not None
    assert "integer" in fix
    assert "text" in fix


def test_pinned_function_has_no_suggested_fix(tmp_path: Path) -> None:
    """Pinned function produces no violation → no fix."""
    f = _write(
        tmp_path,
        "f.sql",
        "CREATE FUNCTION public.safe() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER SET search_path = '' AS $$ BEGIN END $$;\n",
    )
    violations = _make_rule().check([f])
    assert violations == []


def test_emit_remediation_writes_sql(tmp_path: Path) -> None:
    """emit_remediation writes one statement per violation."""
    from confiture.core.linting.schema_linter import LintViolation
    from confiture.core.validation.security_definer import (
        SecurityDefinerReport,
        emit_remediation,
    )

    v1 = LintViolation(
        rule_id="sec_002",
        rule_name="sec_002_security_definer_search_path",
        severity=RuleSeverity.WARNING,
        object_type="function",
        object_name="public.risky",
        message="msg",
        suggested_fix="ALTER FUNCTION public.risky() SET search_path = pg_catalog, public;",
    )
    v2 = LintViolation(
        rule_id="sec_002",
        rule_name="sec_002_security_definer_search_path",
        severity=RuleSeverity.WARNING,
        object_type="function",
        object_name="auth.other",
        message="msg",
        suggested_fix="ALTER FUNCTION auth.other(integer) SET search_path = pg_catalog, public;",
    )
    report = SecurityDefinerReport(violations=[v1, v2])
    out = tmp_path / "remediation.sql"
    count = emit_remediation(report, out)
    assert count == 2
    content = out.read_text()
    assert "ALTER FUNCTION public.risky()" in content
    assert "ALTER FUNCTION auth.other(integer)" in content


def test_emit_remediation_skips_no_fix(tmp_path: Path) -> None:
    """Violations without suggested_fix are skipped silently."""
    from confiture.core.linting.schema_linter import LintViolation
    from confiture.core.validation.security_definer import (
        SecurityDefinerReport,
        emit_remediation,
    )

    v = LintViolation(
        rule_id="sec_002",
        rule_name="sec_002_security_definer_search_path",
        severity=RuleSeverity.WARNING,
        object_type="function",
        object_name="public.risky",
        message="msg",
        suggested_fix=None,
    )
    report = SecurityDefinerReport(violations=[v])
    out = tmp_path / "remediation.sql"
    count = emit_remediation(report, out)
    assert count == 0
    assert out.read_text() == ""


def test_emit_remediation_empty_report(tmp_path: Path) -> None:
    """Empty report writes an empty file and returns 0."""
    from confiture.core.validation.security_definer import (
        SecurityDefinerReport,
        emit_remediation,
    )

    report = SecurityDefinerReport(violations=[])
    out = tmp_path / "remediation.sql"
    count = emit_remediation(report, out)
    assert count == 0
    assert out.read_text() == ""
