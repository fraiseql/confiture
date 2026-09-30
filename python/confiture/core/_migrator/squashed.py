"""A pending squashed baseline, on a database that applied what it squashed.

``migrate squash`` replaces migrations 1..V with one baseline whose header is
``-- confiture:squashed-baseline through=V versions=N digest=D``. Each database
then meets that baseline as a pending migration, and its ledger decides:

- no live row at all (a fresh database): the baseline applies like any migration;
- exactly N live rows up to V, whose ``(version, checksum)`` pairs hash to ``D``:
  the database already holds that schema, so the baseline is recorded without
  running and those rows are marked ``archived_into``, in one transaction. Each
  keeps its ``applied_at``, checksum and role;
- anything else (some squashed versions missing, a file edited after it was
  applied, later versions without earlier ones): ``VALID_008``, before any change.

The archived files are never read: the ledger's own checksums are what the digest
is compared with.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from psycopg import sql as pgsql

from confiture.core.checksum import compute_checksum
from confiture.core.ledger import LIVE_ROWS, LedgerRow, record_migration
from confiture.core.sql_lexer import directives
from confiture.exceptions import ValidationError

if TYPE_CHECKING:
    from confiture.core._migrator.ports import EngineHost

#: The directive naming a squashed baseline.
DIRECTIVE = "squashed-baseline"


def archived_digest(rows: Iterable[tuple[str, str | None]]) -> str:
    """One hash of ``(version, checksum)`` pairs, whatever their order.

    A missing checksum is part of the digest, spelt apart from any checksum.
    """
    lines = sorted(
        f"{version}\t{checksum if checksum is not None else '-'}" for version, checksum in rows
    )
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


@dataclass(frozen=True)
class SquashedBaseline:
    """A baseline migration file and what its header says it replaced."""

    path: Path
    version: str
    name: str
    through: str
    versions: int
    digest: str


def squashed_baseline(path: Path, version: str, name: str) -> SquashedBaseline | None:
    """The baseline ``path`` is, or ``None`` when it is an ordinary migration."""
    if not path.name.endswith(".up.sql"):
        return None
    for directive in directives(path.read_text(encoding="utf-8")):
        if directive.name != DIRECTIVE or directive.argument is None:
            continue
        fields = dict(part.partition("=")[::2] for part in directive.argument.split())
        if {"through", "versions", "digest"} <= fields.keys() and fields["versions"].isdigit():
            return SquashedBaseline(
                path, version, name, fields["through"], int(fields["versions"]), fields["digest"]
            )
    return None


def record_squashed(
    migrator: EngineHost, pending: Iterable[tuple[Path, str, str]], *, dry_run: bool = False
) -> list[str]:
    """Record each pending baseline this ledger already holds the history of.

    Args:
        migrator: The engine, its ledger initialised.
        pending: ``(path, version, name)`` of each pending migration, in order.
        dry_run: Decide, and change nothing.

    Returns:
        The baselines recorded (or, under ``dry_run``, that would be).

    Raises:
        ValidationError: ``VALID_008`` when the ledger holds part of what a
            baseline squashed, or a checksum the digest was not made from.
    """
    live = _live_rows(migrator)
    recorded: list[str] = []
    for path, version, name in pending:
        baseline = squashed_baseline(path, version, name)
        if baseline is None:
            continue
        squashed = [(v, checksum) for v, checksum in live if v <= baseline.through]
        if not live:
            continue
        if len(squashed) != baseline.versions or archived_digest(squashed) != baseline.digest:
            raise _refusal(baseline, squashed)
        checksum = compute_checksum(path)
        if not dry_run:
            _record(migrator, baseline, [v for v, _ in squashed], checksum)
        recorded.append(version)
        live = [row for row in live if row[0] > baseline.through] + [(version, checksum)]
    return recorded


def _live_rows(migrator: EngineHost) -> list[tuple[str, str | None]]:
    with migrator.connection.cursor() as cursor:
        cursor.execute(
            pgsql.SQL("SELECT version, checksum FROM {} AS ledger WHERE {}").format(
                migrator._table_ident, LIVE_ROWS
            )
        )
        return [(row[0], row[1]) for row in cursor.fetchall()]


def _record(
    migrator: EngineHost, baseline: SquashedBaseline, versions: list[str], checksum: str
) -> None:
    """Archive the squashed rows into the baseline and record it: one transaction."""
    conn = migrator.connection
    with conn.transaction():
        with conn.cursor() as cursor:
            cursor.execute(
                pgsql.SQL("UPDATE {} SET archived_into = %s WHERE version = ANY(%s)").format(
                    migrator._table_ident
                ),
                (baseline.version, versions),
            )
        record_migration(
            conn,
            migrator._table_ident,
            LedgerRow(
                version=baseline.version,
                name=baseline.name,
                checksum=checksum,
                reason="squashed",
            ),
        )
    conn.commit()


def _refusal(baseline: SquashedBaseline, squashed: list[tuple[str, str | None]]) -> ValidationError:
    return ValidationError(
        f"migration {baseline.version} is the baseline of {baseline.versions} squashed "
        f"migration(s) through {baseline.through}, and this database's ledger holds "
        f"{len(squashed)} of them"
        + (" with different checksums" if len(squashed) == baseline.versions else "")
        + ": it neither applied that history nor is it empty",
        error_code="VALID_008",
        resolution_hint=(
            "Bring the database to the squashed version with the archived migrations "
            "first, or restore the squashed files"
        ),
    )
