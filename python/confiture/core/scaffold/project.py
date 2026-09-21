"""The project ``confiture init`` scaffolds: the directories, and the template files under them.

The files live in ``templates/`` beside this module and are copied as they are,
so what a new project gets is reviewable as files rather than as string literals
inside a command.
"""

from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

#: Directories a new project has, whether or not a template lands in them.
DIRECTORIES = (
    "schema/00_common",
    "schema/10_tables",
    "seeds/common",
    "seeds/development",
    "seeds/test",
    "migrations",
    "environments",
)


def _templates(
    root: Traversable, prefix: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], str]]:
    found: list[tuple[tuple[str, ...], str]] = []
    for entry in sorted(root.iterdir(), key=lambda e: e.name):
        if entry.is_dir():
            found += _templates(entry, (*prefix, entry.name))
        elif not entry.name.startswith(("__", ".")):
            found.append(((*prefix, entry.name), entry.read_text(encoding="utf-8")))
    return found


def scaffold(db_dir: Path) -> list[Path]:
    """Create the project's directories under *db_dir* and write every template; return the files.

    An existing file is overwritten: the caller asks first.
    """
    for directory in DIRECTORIES:
        (db_dir / directory).mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for parts, text in _templates(files("confiture.core.scaffold") / "templates"):
        target = db_dir.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written.append(target)
    return written
