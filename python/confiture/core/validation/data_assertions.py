"""``migrate validate --check-data-assertions``: a data assertion inside ``up()``.

``migrate preflight`` replays pending ``up()`` bodies against a schema-only
database, where every table is empty, so a ``RAISE EXCEPTION`` guarded on a row
count aborts it every time — whatever the migration's actual work does. The
assertion belongs in a ``.verify.sql`` sidecar, which ``migrate verify`` runs
separately against the database that has the rows.

The detector (``core/data_assertions``) is a heuristic, so every finding here
is a **warning**: the outcome reports ``passed=True`` and the command still
exits 0. Confiture owns ``preflight``, so it owns telling the author about the
contract; it does not own deciding their migration is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from confiture.core.data_assertions import DataAssertion, scan_migration

#: Migration file suffixes worth scanning. ``.down.sql`` is included — a
#: rollback runs under the same preflight replay when one is exercised.
_MIGRATION_GLOBS = ("*.py", "*.up.sql", "*.down.sql")


@dataclass
class DataAssertionReport:
    """What the check found across a migrations directory.

    Attributes:
        assertions: Every data assertion found, in file then line order.
        unanalysed: Files that were meant to be read and were not — a body the
            compiler rejected, or a ``self.execute(...)`` the static evaluator
            refused. Reported rather than folded into "clean".
        scanned: How many migration files were read.
    """

    assertions: list[DataAssertion] = field(default_factory=list)
    unanalysed: list[Path] = field(default_factory=list)
    scanned: int = 0

    @property
    def has_findings(self) -> bool:
        """Whether anything at all is worth printing."""
        return bool(self.assertions or self.unanalysed)


def check_data_assertions(migrations_dir: Path) -> DataAssertionReport:
    """Scan every migration file for a data assertion inside ``up()``.

    Static: it reads files and never connects. ``.py`` migrations resolve
    through the static evaluator, which is the one module that answers what
    text a ``self.execute(...)`` hands over (#213).
    """
    report = DataAssertionReport()
    if not migrations_dir.is_dir():
        return report

    seen: set[Path] = set()
    for pattern in _MIGRATION_GLOBS:
        for path in sorted(migrations_dir.glob(pattern)):
            if path in seen:
                continue
            seen.add(path)
            report.scanned += 1
            scan = scan_migration(path)
            report.assertions.extend(scan.assertions)
            if scan.unparseable:
                report.unanalysed.append(path)

    report.assertions.sort(key=lambda a: (str(a.file), a.line))
    return report
