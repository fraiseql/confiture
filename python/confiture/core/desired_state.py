"""Where ``migrate diff`` reads its desired state from (issue #196).

The target of a diff used to be one hand-authored SQL file. The canonical
desired-state artifact is what ``fraiseql compile --emit-ddl <dir>`` writes: a
directory of DDL files, one per type. A pipeline hands the same text over on
stdin. Each source yields DDL text; the differ parses it exactly as before and
never learns what an artifact is. ``describe()`` is what ``--format json``
reports as ``source``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol

from confiture.exceptions import SchemaError

STDIN = "-"


class DesiredStateSource(Protocol):
    """A desired state the differ can compare against."""

    def read(self) -> str:
        """The DDL text."""

    def describe(self) -> dict[str, str]:
        """``{"kind": …, "path": …}`` for the JSON payload."""


@dataclass(frozen=True)
class SqlFileSource:
    """DDL from a file, a directory of ``.sql`` files (read in name order) or stdin (``-``)."""

    target: str
    kind: ClassVar[str] = "sql"

    def describe(self) -> dict[str, str]:
        return {"kind": self.kind, "path": self.target}

    def read(self) -> str:
        if self.target == STDIN:
            return sys.stdin.read()
        path = Path(self.target)
        if path.is_dir():
            files = sorted(path.glob("*.sql"))
            if not files:
                raise SchemaError(
                    f"No .sql files in desired-state directory {path}",
                    error_code="SCHEMA_201",
                    resolution_hint="Point --to at a directory of DDL files "
                    "(e.g. the output of `fraiseql compile --emit-ddl`) or at one SQL file.",
                )
            return "".join(_with_newline(f.read_text()) for f in files)
        if not path.exists():
            raise SchemaError(
                f"Desired-state file not found: {path}",
                error_code="SCHEMA_201",
                resolution_hint="Check the path passed to --to / --from.",
            )
        return path.read_text()


def _with_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def load_desired_state(spec: str) -> DesiredStateSource:
    """The source for a ``--to`` / ``--from`` value: ``-`` (stdin), a directory or a file."""
    return SqlFileSource(spec)
