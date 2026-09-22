"""Unit tests for the function uniqueness lint rule (issue #136).

``func_001`` walks the configured DDL directories, parses each ``.sql``
file with pglast, and flags any fully-qualified function (or procedure)
signature defined in more than one file.

Kind-aware key: ``(kind, schema, name, parameter_types_tuple)`` so a
function and a procedure that share a name don't collide (PostgreSQL
keeps them in separate namespaces), and overloads with different
parameter types are not flagged.

AST-only, and pglast is a dependency (D13) — the rule always runs. There
is no skip notice, and a file pglast rejects is reported rather than passed
over.
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
# AST signature extractor
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
    # The key is `(schema, canonical name)` per argument — a type's schema is
    # `None` unless written, which is what lets a bare one match a qualified one.
    assert sig.param_types == ((None, "integer"), (None, "text"))
    assert sig.param_text == ("integer", "text")


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
    assert sig.param_types == ((None, "integer"),)
    assert sig.param_text == ("integer",)


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
# Duplicate detection across files
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
# Overload + kind distinction
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
# Opt-out directive
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
# Env-config gate
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


class TestTwoSpellingsAreOneSignature:
    """``int8`` and ``bigint`` are one type, so they are one signature (#275).

    `func_001` carried its own `_PG_CATALOG_ALIASES`, pasted from — not shared
    with — `sec_002`'s copy under a comment saying it was shared. It mapped
    `pg_catalog.int4` back to `integer`, which handles a pair written `int`
    against `integer`, and did nothing for `int8` against `bigint`: a bare
    internal name never reached the table.
    """

    def test_two_spellings_are_one_signature(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "010_a.sql",
            "CREATE FUNCTION app.g(p INT8) RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;\n",
        )
        _write(
            tmp_path,
            "020_b.sql",
            "CREATE FUNCTION app.g(p BIGINT) RETURNS int AS $$ SELECT 2 $$ LANGUAGE sql;\n",
        )

        violations = Func001FunctionUniqueness(coverage=_make_coverage()).check([tmp_path])

        assert [v.rule_id for v in violations] == ["func_001"]
        assert "app.g" in violations[0].object_name

    def test_timestamptz_and_the_keyword_form_are_one_signature(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "010_a.sql",
            "CREATE FUNCTION app.f(p TIMESTAMPTZ) RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;\n",
        )
        _write(
            tmp_path,
            "020_b.sql",
            "CREATE FUNCTION app.f(p TIMESTAMP WITH TIME ZONE) RETURNS int"
            " AS $$ SELECT 2 $$ LANGUAGE sql;\n",
        )

        violations = Func001FunctionUniqueness(coverage=_make_coverage()).check([tmp_path])

        assert [v.rule_id for v in violations] == ["func_001"]

    def test_an_array_is_still_a_different_overload(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "010_a.sql",
            "CREATE FUNCTION app.k(p INT[]) RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;\n",
        )
        _write(
            tmp_path,
            "020_b.sql",
            "CREATE FUNCTION app.k(p INT) RETURNS int AS $$ SELECT 2 $$ LANGUAGE sql;\n",
        )

        assert Func001FunctionUniqueness(coverage=_make_coverage()).check([tmp_path]) == []

    def test_the_message_prints_the_type_as_written(self, tmp_path: Path) -> None:
        """The key is canonical; what the operator reads is what they typed."""
        _write(
            tmp_path,
            "010_a.sql",
            "CREATE FUNCTION app.h(p INT) RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;\n",
        )
        _write(
            tmp_path,
            "020_b.sql",
            "CREATE FUNCTION app.h(p INT) RETURNS int AS $$ SELECT 2 $$ LANGUAGE sql;\n",
        )

        violations = Func001FunctionUniqueness(coverage=_make_coverage()).check([tmp_path])

        assert "app.h(integer)" in violations[0].message


class TestABareTypeMatchesAnySchema:
    """A type schema on one definition and not the other is still one signature (D9).

    The same rule the inventory applies to `doc_002` and `build_001`: a missing
    schema matches any schema, because PostgreSQL resolves the bare spelling
    through `search_path`. Both modules read it from
    `inventory.group_by_signature`, so they agree by construction.
    """

    def test_a_qualified_and_a_bare_spelling_are_one_signature(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "010_a.sql",
            "CREATE FUNCTION app.f(p app.custom_t) RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;\n",
        )
        _write(
            tmp_path,
            "020_b.sql",
            "CREATE FUNCTION app.f(p custom_t) RETURNS int AS $$ SELECT 2 $$ LANGUAGE sql;\n",
        )

        violations = Func001FunctionUniqueness(coverage=_make_coverage()).check([tmp_path])

        assert [v.rule_id for v in violations] == ["func_001"]
        assert "app.f" in violations[0].object_name

    def test_two_present_schemas_stay_two_signatures(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "010_a.sql",
            "CREATE FUNCTION app.f(p app.custom_t) RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;\n",
        )
        _write(
            tmp_path,
            "020_b.sql",
            "CREATE FUNCTION app.f(p other.custom_t) RETURNS int AS $$ SELECT 2 $$ LANGUAGE sql;\n",
        )

        assert Func001FunctionUniqueness(coverage=_make_coverage()).check([tmp_path]) == []

    def test_a_bare_spelling_does_not_chain_two_qualified_ones(self, tmp_path: Path) -> None:
        """Three definitions, two signatures — and the finding names the right two files."""
        _write(
            tmp_path,
            "010_a.sql",
            "CREATE FUNCTION app.f(p app.custom_t) RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;\n",
        )
        _write(
            tmp_path,
            "020_b.sql",
            "CREATE FUNCTION app.f(p custom_t) RETURNS int AS $$ SELECT 2 $$ LANGUAGE sql;\n",
        )
        _write(
            tmp_path,
            "030_c.sql",
            "CREATE FUNCTION app.f(p other.custom_t) RETURNS int AS $$ SELECT 3 $$ LANGUAGE sql;\n",
        )

        violations = Func001FunctionUniqueness(coverage=_make_coverage()).check([tmp_path])

        assert [v.rule_id for v in violations] == ["func_001"]
        assert "defined in 2 files" in violations[0].message
        assert "010_a.sql" in violations[0].message
        assert "020_b.sql" in violations[0].message
        assert "030_c.sql" not in violations[0].message
