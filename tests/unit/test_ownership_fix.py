"""Unit tests for the ownership auto-fixer (issue #124, Phase 04).

Mirrors :mod:`confiture.core.idempotency.fixer` on the ownership axis.
The fixer reuses :class:`Own001OwnershipCoverage` to find violations,
then emits ``ALTER … OWNER TO`` immediately after each offending CREATE.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.config.environment import OwnershipApplyTo, OwnershipExpectation

pytest.importorskip("pglast")

from confiture.core.ownership_fixer import OwnershipFixer  # noqa: E402


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
# Detection (delegates to Own001OwnershipCoverage)
# ---------------------------------------------------------------------------


def test_detect_missing_alter_owner(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )
    fixer = OwnershipFixer(expectation=_make_expectation())
    candidates = list(fixer.iter_candidates(tmp_path))
    assert len(candidates) == 1
    assert candidates[0].qualified_name == "public.foo"
    assert candidates[0].kind == "TABLE"


def test_detect_skips_already_fixed_relations(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\nALTER TABLE public.foo OWNER TO migrator;\n",
    )
    fixer = OwnershipFixer(expectation=_make_expectation())
    assert list(fixer.iter_candidates(tmp_path)) == []


# ---------------------------------------------------------------------------
# Fix emission
# ---------------------------------------------------------------------------


def test_emit_alter_owner_after_create(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int primary key);\nINSERT INTO public.seed VALUES (1);\n",
    )
    fixer = OwnershipFixer(expectation=_make_expectation())
    fixed = fixer.fix_text(path.read_text())
    expected = (
        "CREATE TABLE public.foo (id int primary key);\n"
        "ALTER TABLE public.foo OWNER TO migrator;\n"
        "INSERT INTO public.seed VALUES (1);\n"
    )
    assert fixed == expected


def test_emit_alter_owner_for_sequence(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "20260527090000_seq.up.sql",
        "CREATE SEQUENCE public.s;\n",
    )
    fixer = OwnershipFixer(expectation=_make_expectation())
    fixed = fixer.fix_text(path.read_text())
    assert "ALTER SEQUENCE public.s OWNER TO migrator;" in fixed


def test_emit_alter_owner_for_view(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "20260527090000_view.up.sql",
        "CREATE TABLE public.t (id int);\n"
        "ALTER TABLE public.t OWNER TO migrator;\n"
        "CREATE VIEW public.v AS SELECT id FROM public.t;\n",
    )
    fixer = OwnershipFixer(expectation=_make_expectation())
    fixed = fixer.fix_text(path.read_text())
    assert "ALTER VIEW public.v OWNER TO migrator;" in fixed


def test_emit_alter_owner_for_materialized_view(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "20260527090000_mv.up.sql",
        "CREATE TABLE public.t (id int);\n"
        "ALTER TABLE public.t OWNER TO migrator;\n"
        "CREATE MATERIALIZED VIEW public.mv AS SELECT id FROM public.t;\n",
    )
    fixer = OwnershipFixer(expectation=_make_expectation())
    fixed = fixer.fix_text(path.read_text())
    assert "ALTER MATERIALIZED VIEW public.mv OWNER TO migrator;" in fixed


# ---------------------------------------------------------------------------
# Idempotence guarantee
# ---------------------------------------------------------------------------


def test_fix_is_idempotent(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )
    fixer = OwnershipFixer(expectation=_make_expectation())

    once = fixer.fix_text(path.read_text())
    twice = fixer.fix_text(once)
    assert once == twice


def test_fix_text_returns_input_when_already_covered(tmp_path: Path) -> None:
    sql = "CREATE TABLE public.foo (id int);\nALTER TABLE public.foo OWNER TO migrator;\n"
    fixer = OwnershipFixer(expectation=_make_expectation())
    assert fixer.fix_text(sql) == sql


# ---------------------------------------------------------------------------
# Scope respected
# ---------------------------------------------------------------------------


def test_fix_skips_relations_outside_apply_to(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "20260527090000_other.up.sql",
        "CREATE TABLE other.foo (id int);\n",
    )
    fixer = OwnershipFixer(expectation=_make_expectation())
    assert fixer.fix_text(path.read_text()) == path.read_text()


def test_fix_respects_ignore_list(tmp_path: Path) -> None:
    sql = "CREATE TABLE public.legacy (id int);\n"
    fixer = OwnershipFixer(
        expectation=OwnershipExpectation(
            expected_owner="migrator",
            apply_to=[OwnershipApplyTo(schema="public", relkinds=["r"])],
            ignore=["public.legacy"],
        ),
    )
    assert fixer.fix_text(sql) == sql


def test_fix_respects_owner_skip_directive(tmp_path: Path) -> None:
    sql = "-- confiture:owner-skip\nCREATE TABLE public.ext (id int);\n"
    fixer = OwnershipFixer(expectation=_make_expectation())
    assert fixer.fix_text(sql) == sql


# ---------------------------------------------------------------------------
# Apply to files
# ---------------------------------------------------------------------------


def test_apply_writes_files_in_place(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )
    fixer = OwnershipFixer(expectation=_make_expectation())
    changed = fixer.apply(tmp_path)
    assert path in changed
    assert "ALTER TABLE public.foo OWNER TO migrator;" in path.read_text()


def test_dry_run_reports_changes_without_writing(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "20260527090000_add_foo.up.sql",
        "CREATE TABLE public.foo (id int);\n",
    )
    original = path.read_text()
    fixer = OwnershipFixer(expectation=_make_expectation())
    changes = fixer.preview(tmp_path)
    assert len(changes) == 1
    assert changes[0].file == path
    assert "ALTER TABLE public.foo OWNER TO migrator" in changes[0].after
    assert path.read_text() == original  # unchanged on disk
