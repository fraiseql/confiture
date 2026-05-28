"""Unit tests for the function uniqueness lint rule (issue #136).

``func_001`` walks the configured DDL directories, parses each ``.sql``
file with pglast, and flags any fully-qualified function (or procedure)
signature defined in more than one file.

Kind-aware key: ``(kind, schema, name, parameter_types_tuple)`` so a
function and a procedure that share a name don't collide (PostgreSQL
keeps them in separate namespaces), and overloads with different
parameter types are not flagged.

AST-only: when pglast is not installed, the rule emits a single skip
notice and returns no violations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.config.environment import FunctionCoverage
from confiture.core.linting.libraries.functions import Func001FunctionUniqueness
from confiture.core.linting.schema_linter import RuleSeverity

# Mark the entire module as requiring pglast. The skip-when-absent path
# has its own dedicated test file.
pglast = pytest.importorskip("pglast")


def _make_coverage(
    *,
    apply_to: list[str] | None = None,
    ignore: list[str] | None = None,
    enabled: bool = True,
) -> FunctionCoverage:
    return FunctionCoverage(
        enabled=enabled,
        apply_to=apply_to if apply_to is not None else ["*"],
        ignore=ignore or [],
    )


def _write(tmp_path: Path, name: str, sql: str) -> Path:
    p = tmp_path / name
    p.write_text(sql)
    return p


# ---------------------------------------------------------------------------
# AST signature extractor — Cycle 1
# ---------------------------------------------------------------------------


def test_extracts_qualified_signatures_from_create_function(tmp_path: Path) -> None:
    """A single CREATE FUNCTION is parsed into a CallableDefinition."""
    f = _write(
        tmp_path,
        "01_foo.sql",
        "CREATE FUNCTION public.foo(a integer, b text) RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    rule = Func001FunctionUniqueness(coverage=_make_coverage())
    sigs = rule._extract_callable_signatures(f.read_text(), f)
    assert len(sigs) == 1
    sig = sigs[0]
    assert sig.kind == "function"
    assert sig.schema == "public"
    assert sig.name == "foo"
    assert sig.param_types == ("integer", "text")


def test_extracts_qualified_signatures_from_create_procedure(tmp_path: Path) -> None:
    """A single CREATE PROCEDURE is parsed with kind = ``procedure``."""
    f = _write(
        tmp_path,
        "01_bar.sql",
        "CREATE PROCEDURE public.bar(p integer) LANGUAGE plpgsql AS $$ BEGIN END $$;\n",
    )
    rule = Func001FunctionUniqueness(coverage=_make_coverage())
    sigs = rule._extract_callable_signatures(f.read_text(), f)
    assert len(sigs) == 1
    sig = sigs[0]
    assert sig.kind == "procedure"
    assert sig.schema == "public"
    assert sig.name == "bar"
    assert sig.param_types == ("integer",)


def test_unqualified_function_defaults_to_public_schema(tmp_path: Path) -> None:
    """Unqualified names belong to the default ``public`` schema."""
    f = _write(
        tmp_path,
        "01_baz.sql",
        "CREATE OR REPLACE FUNCTION baz() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    rule = Func001FunctionUniqueness(coverage=_make_coverage())
    sigs = rule._extract_callable_signatures(f.read_text(), f)
    assert len(sigs) == 1
    assert sigs[0].schema == "public"
    assert sigs[0].name == "baz"
    assert sigs[0].param_types == ()


# ---------------------------------------------------------------------------
# Duplicate detection across files — Cycle 2
# ---------------------------------------------------------------------------


def test_flags_same_signature_in_two_files(tmp_path: Path) -> None:
    """Two files defining ``public.foo()`` produce one violation pointing to both."""
    _write(
        tmp_path,
        "0397_a.sql",
        "CREATE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    _write(
        tmp_path,
        "0397_b.sql",
        "CREATE OR REPLACE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )

    rule = Func001FunctionUniqueness(coverage=_make_coverage())
    violations = rule.check([tmp_path])
    assert len(violations) == 1
    v = violations[0]
    assert v.rule_id == "func_001"
    assert v.severity == RuleSeverity.ERROR
    assert "public.foo" in v.object_name
    assert "0397_a.sql" in v.message and "0397_b.sql" in v.message


def test_passes_when_each_signature_is_unique(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "01.sql",
        "CREATE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    _write(
        tmp_path,
        "02.sql",
        "CREATE FUNCTION public.bar() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    rule = Func001FunctionUniqueness(coverage=_make_coverage())
    assert rule.check([tmp_path]) == []


# ---------------------------------------------------------------------------
# Overload + kind distinction — Cycle 3
# ---------------------------------------------------------------------------


def test_overloads_not_flagged(tmp_path: Path) -> None:
    """``foo(int)`` and ``foo(text)`` are distinct overloads, not duplicates."""
    _write(
        tmp_path,
        "01_a.sql",
        "CREATE FUNCTION public.foo(a integer) RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    _write(
        tmp_path,
        "02_b.sql",
        "CREATE FUNCTION public.foo(a text) RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    rule = Func001FunctionUniqueness(coverage=_make_coverage())
    assert rule.check([tmp_path]) == []


def test_function_and_procedure_with_same_name_not_flagged(tmp_path: Path) -> None:
    """A function and a procedure live in separate PostgreSQL namespaces."""
    _write(
        tmp_path,
        "01_func.sql",
        "CREATE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    _write(
        tmp_path,
        "02_proc.sql",
        "CREATE PROCEDURE public.foo() LANGUAGE plpgsql AS $$ BEGIN END $$;\n",
    )
    rule = Func001FunctionUniqueness(coverage=_make_coverage())
    assert rule.check([tmp_path]) == []


# ---------------------------------------------------------------------------
# Opt-out directive — Cycle 4
# ---------------------------------------------------------------------------


def test_opt_out_directive_skips_statement(tmp_path: Path) -> None:
    """``-- confiture:func-allow-duplicate`` above a CREATE skips it."""
    _write(
        tmp_path,
        "01_a.sql",
        "CREATE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    _write(
        tmp_path,
        "02_b.sql",
        "-- confiture:func-allow-duplicate\n"
        "CREATE OR REPLACE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    rule = Func001FunctionUniqueness(coverage=_make_coverage())
    assert rule.check([tmp_path]) == []


# ---------------------------------------------------------------------------
# Schema scoping — apply_to
# ---------------------------------------------------------------------------


def test_apply_to_filters_out_unscoped_schemas(tmp_path: Path) -> None:
    """``apply_to=['stat_etl']`` only flags duplicates in stat_etl, not public."""
    _write(
        tmp_path,
        "01_a.sql",
        "CREATE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    _write(
        tmp_path,
        "02_b.sql",
        "CREATE OR REPLACE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    rule = Func001FunctionUniqueness(coverage=_make_coverage(apply_to=["stat_etl"]))
    assert rule.check([tmp_path]) == []


def test_ignore_globs_skip_specific_objects(tmp_path: Path) -> None:
    """An ``ignore`` glob removes a specific qualified name from detection."""
    _write(
        tmp_path,
        "01_a.sql",
        "CREATE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    _write(
        tmp_path,
        "02_b.sql",
        "CREATE OR REPLACE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    rule = Func001FunctionUniqueness(coverage=_make_coverage(ignore=["public.foo"]))
    assert rule.check([tmp_path]) == []


# ---------------------------------------------------------------------------
# Env-config gate — Cycle 5
# ---------------------------------------------------------------------------


def test_rule_skipped_when_function_coverage_disabled(tmp_path: Path) -> None:
    """``enabled=False`` short-circuits the rule to an empty list."""
    _write(
        tmp_path,
        "01_a.sql",
        "CREATE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    _write(
        tmp_path,
        "02_b.sql",
        "CREATE OR REPLACE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n",
    )
    rule = Func001FunctionUniqueness(coverage=_make_coverage(enabled=False))
    assert rule.check([tmp_path]) == []


# ---------------------------------------------------------------------------
# Realistic example from issue #136
# ---------------------------------------------------------------------------


def test_real_world_failure_mode_from_issue(tmp_path: Path) -> None:
    """Mirrors the exact failure example in the issue body."""
    a = tmp_path / "03970_sync_tv_dimensions.sql"
    b = tmp_path / "039700_sync_tv_dimensions.sql"
    body = (
        "CREATE OR REPLACE FUNCTION stat_etl.sync_tv_dimensions(p_run_id bigint) "
        "RETURNS integer AS $$ BEGIN RETURN 0; END $$ LANGUAGE plpgsql;\n"
    )
    a.write_text(body)
    b.write_text(body)

    rule = Func001FunctionUniqueness(coverage=_make_coverage())
    violations = rule.check([tmp_path])
    assert len(violations) == 1
    assert "stat_etl.sync_tv_dimensions" in violations[0].object_name
