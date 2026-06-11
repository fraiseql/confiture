"""Skip-when-pglast-absent path for ``sec_002`` (issue #161)."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_ast_required_state() -> Iterator[None]:
    from confiture.core.linting import _ast_required

    _ast_required.is_pglast_available.cache_clear()
    _ast_required._skip_warned = False
    yield
    _ast_required.is_pglast_available.cache_clear()
    _ast_required._skip_warned = False
    _ast_required._force_unavailable = False


def test_sec_002_skips_when_pglast_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When pglast cannot be imported, sec_002 returns [] and logs once to stderr."""
    (tmp_path / "a.sql").write_text(
        "CREATE FUNCTION public.risky() RETURNS void LANGUAGE plpgsql "
        "SECURITY DEFINER AS $$ BEGIN END $$;\n"
    )

    from confiture.core.linting import _ast_required

    monkeypatch.setattr(_ast_required, "_force_unavailable", True, raising=False)
    monkeypatch.setitem(sys.modules, "pglast", None)

    from confiture.core.linting.libraries.security_definer import (
        Sec002SecurityDefinerSearchPath,
    )

    rule = Sec002SecurityDefinerSearchPath()
    assert rule.check([tmp_path]) == []

    captured = capsys.readouterr()
    assert "sec_002" in captured.err
    assert "[ast]" in captured.err
