"""The type checker is ty; ``# type: ignore[<mypy code>]`` comments are archaeology.

A ``type: ignore[no-any-return]`` names a mypy error class ty never emits, so it
silences nothing today and hides the reason the line was suspect. A line ty really
cannot type gets ``# ty: ignore[<ty code>]`` with the code ty prints; the rest get
a real fix.
"""

from __future__ import annotations

import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "python" / "confiture"
MYPY_STYLE = re.compile(r"#\s*type:\s*ignore\[")
BARE = re.compile(r"#\s*type:\s*ignore(?!\[)")


def _offenders(pattern: re.Pattern[str]) -> list[str]:
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                found.append(
                    f"{path.relative_to(PACKAGE.parent.parent)}:{lineno}: {line.strip()[:90]}"
                )
    return found


def test_no_mypy_style_ignore_codes() -> None:
    assert _offenders(MYPY_STYLE) == [], "mypy-style ignore codes:\n" + "\n".join(
        _offenders(MYPY_STYLE)
    )


def test_no_bare_type_ignore() -> None:
    assert _offenders(BARE) == [], "bare `# type: ignore` (say why, with ty's code):\n" + "\n".join(
        _offenders(BARE)
    )
