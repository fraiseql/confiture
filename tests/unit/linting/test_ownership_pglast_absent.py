"""Skip-when-pglast-absent path for ``own_001`` (issue #124).

The lint rule is AST-only — when pglast is not importable, it emits a
single skip notice to stderr and returns an empty violation list (true
no-op, never false-negative).
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from confiture.config.environment import OwnershipApplyTo, OwnershipExpectation


@pytest.fixture(autouse=True)
def _reset_ast_required_state() -> Iterator[None]:
    """Reset the module-level cache + warned flag around every test.

    The skip notice and pglast-availability check are deliberately
    process-level singletons, so tests must restore both sides of the
    state to avoid leaking ``_force_unavailable=True`` or
    ``_skip_warned=True`` into unrelated tests in the same process.
    """
    from confiture.core.linting import _ast_required

    _ast_required.is_pglast_available.cache_clear()
    _ast_required._skip_warned = False
    yield
    _ast_required.is_pglast_available.cache_clear()
    _ast_required._skip_warned = False
    # Also defensively reset the force-unavailable flag in case a test
    # monkey-patch didn't undo it (monkeypatch normally does, but belt
    # and braces given that we share the module globally).
    _ast_required._force_unavailable = False


def test_own_001_skips_when_pglast_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When pglast cannot be imported, the rule returns [] and logs once."""
    # Migration that WOULD violate under AST mode (CREATE TABLE without ALTER OWNER).
    (tmp_path / "20260527090000_no_owner.up.sql").write_text(
        "CREATE TABLE public.foo (id int);\n"
    )

    from confiture.core.linting import _ast_required

    monkeypatch.setattr(_ast_required, "_force_unavailable", True, raising=False)

    # Drop pglast from the import cache so the rule's own importlib check fails.
    monkeypatch.setitem(sys.modules, "pglast", None)

    from confiture.core.linting.libraries.ownership import Own001OwnershipCoverage

    expectation = OwnershipExpectation(
        expected_owner="migrator",
        apply_to=[OwnershipApplyTo(schema="public")],
    )
    rule = Own001OwnershipCoverage(expectation=expectation)
    violations = rule.check(tmp_path)
    assert violations == []

    captured = capsys.readouterr()
    assert "own_001" in captured.err
    assert "[ast]" in captured.err


def test_own_001_skip_notice_emitted_once_per_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "20260527090000_a.up.sql").write_text("CREATE TABLE public.a (id int);\n")
    (tmp_path / "20260527090001_b.up.sql").write_text("CREATE TABLE public.b (id int);\n")

    from confiture.core.linting import _ast_required

    monkeypatch.setattr(_ast_required, "_force_unavailable", True, raising=False)
    monkeypatch.setitem(sys.modules, "pglast", None)

    from confiture.core.linting.libraries.ownership import Own001OwnershipCoverage

    expectation = OwnershipExpectation(
        expected_owner="migrator",
        apply_to=[OwnershipApplyTo(schema="public")],
    )
    rule = Own001OwnershipCoverage(expectation=expectation)

    rule.check(tmp_path)
    rule.check(tmp_path)

    captured = capsys.readouterr()
    # Notice fires once across the whole process, not once per check().
    assert captured.err.count("own_001 requires the [ast] extra") == 1
