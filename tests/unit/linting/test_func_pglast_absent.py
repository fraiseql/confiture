"""Skip-when-pglast-absent path for ``func_001`` (issue #136).

The rule is AST-only — when pglast is not importable, it emits a single
skip notice to stderr and returns an empty violation list (true no-op,
never false-negative).
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from confiture.config.environment import FunctionCoverage


@pytest.fixture(autouse=True)
def _reset_ast_required_state() -> Iterator[None]:
    """Reset module-level cache + warned flag around every test."""
    from confiture.core.linting import _ast_required

    _ast_required.is_pglast_available.cache_clear()
    _ast_required._skip_warned = False
    yield
    _ast_required.is_pglast_available.cache_clear()
    _ast_required._skip_warned = False
    _ast_required._force_unavailable = False


def test_func_001_skips_when_pglast_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When pglast cannot be imported, the rule returns [] and logs once."""
    (tmp_path / "01_a.sql").write_text(
        "CREATE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n"
    )
    (tmp_path / "02_b.sql").write_text(
        "CREATE OR REPLACE FUNCTION public.foo() RETURNS void AS $$ BEGIN END $$ LANGUAGE plpgsql;\n"
    )

    from confiture.core.linting import _ast_required

    monkeypatch.setattr(_ast_required, "_force_unavailable", True, raising=False)
    monkeypatch.setitem(sys.modules, "pglast", None)

    from confiture.core.linting.libraries.functions import Func001FunctionUniqueness

    coverage = FunctionCoverage(enabled=True, apply_to=["*"])
    rule = Func001FunctionUniqueness(coverage=coverage)
    assert rule.check([tmp_path]) == []

    captured = capsys.readouterr()
    assert "func_001" in captured.err
    assert "[ast]" in captured.err
