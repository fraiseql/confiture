"""No module defers its annotations (#598).

Python 3.14 evaluates an annotation when something reads it (PEP 649), so
``from __future__ import annotations`` buys nothing but strings where a reader
expects values: ``dataclasses.fields(…).type``, ``inspect.signature``, typer and
pydantic all see the source text instead of the type. A reader that wants the
text asks for it — ``annotationlib.Format.STRING`` — and gets the same text the
import used to produce.

The guard fails on the import in any tracked Python file. The allow-list is empty.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ALLOWED: dict[str, str] = {}


def _tracked_python_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    return [ROOT / name for name in listed if (ROOT / name).is_file()]


#: The statement at module level; a line, not a parse, since some fixtures are
#: deliberately not Python (a migration that must fail to import).
_FUTURE_IMPORT = re.compile(r"^from\s+__future__\s+import\s+[^#\n]*\bannotations\b", re.MULTILINE)


def _defers_annotations(path: Path) -> bool:
    return _FUTURE_IMPORT.search(path.read_text(encoding="utf-8")) is not None


def test_no_module_defers_its_annotations() -> None:
    deferring = sorted(
        path.relative_to(ROOT).as_posix()
        for path in _tracked_python_files()
        if _defers_annotations(path)
    )
    assert [p for p in deferring if p not in ALLOWED] == [], (
        "Python 3.14 defers annotations by itself; drop `from __future__ import "
        f"annotations` and read text with annotationlib.Format.STRING: {deferring}"
    )


def test_every_allowed_module_still_defers() -> None:
    stale = [name for name in ALLOWED if not _defers_annotations(ROOT / name)]
    assert stale == [], f"remove these allow-list entries, they match nothing: {stale}"
