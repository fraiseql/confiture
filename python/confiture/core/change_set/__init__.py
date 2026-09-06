"""The preflight change set: what a migration set changes, and how risky it is (#197).

`migrate preflight --format json` carries a `change_set` object beside the
`window_safe` boolean. Each entry names one change and — when confiture can say
so honestly — its :class:`~confiture.core.risk_tier.RiskTier`. The wire shape,
the tier boundaries and the version rule are the ratified cross-repo contract
(fraisier-core#44, ``docs/proposals/migration-risk-contract.md``).

Three rules shape the code:

1. **Never drop a statement.** A statement this module cannot classify still
   produces an entry, with no ``tier``. Dropping it would shrink the set, and a
   shorter list of fully-classified changes reads as a *cleaner* plan than the
   truth — the one failure direction the contract exists to prevent.
2. **Never guess a tier.** ``ALTER COLUMN … TYPE`` is reversible when widening
   and irreversible when narrowing; preflight runs without a database and cannot
   tell, so it emits no tier rather than a confident wrong answer.
3. **This is not the replica classifier.** ``core/replica/classifier.py`` feeds
   the pinned ``window_safe`` verdict (#154) and reports only the operations in
   its safety matrix — an operation outside that matrix degrades to ``depends``
   there, which flips ``window_safe`` to false. Widening *it* to cover the
   change-set vocabulary would move that pinned field, so this module walks the
   statements itself. The cost is a second parse of files preflight has already
   read; the alternative was a false verdict on a cross-repo contract.

pglast is the one parser (D13); a statement it rejects yields an unclassified entry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pglast.parser

from confiture.core.schema_facts import SchemaFacts

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
from confiture.core.change_set.models import (
    _DEFAULT_SCHEMA,
    CONTRACT_VERSION,
    ChangeEntry,
    ChangeSet,
)
from confiture.core.change_set.naming import _Context
from confiture.core.change_set.walker import _ast_entries

__all__ = [
    "CONTRACT_VERSION",
    "ChangeEntry",
    "ChangeSet",
    "build_change_set",
    "classify_statements",
]


def build_change_set(
    migrations_dir: Path,
    *,
    versions: list[str] | None = None,
    default_schema: str = _DEFAULT_SCHEMA,
    facts: SchemaFacts | None = None,
) -> ChangeSet:
    """Classify every change in ``migrations_dir``.

    Mirrors ``run_preflight``'s discovery — ``*.up.sql`` then ``*.py`` (skipping
    ``__init__.py`` and ``_``-prefixed helpers) — so the change set covers exactly
    the migrations preflight reports on. A missing directory classifies to an
    empty set; preflight already reports that condition on its own.
    """
    from confiture.core._migrator.discovery import _version_from_migration_filename

    if not migrations_dir.exists():
        return ChangeSet()

    entries: list[ChangeEntry] = []

    for up_file in sorted(migrations_dir.glob("*.up.sql"), key=lambda f: f.name):
        version = _version_from_migration_filename(up_file.name)
        if versions is not None and version not in versions:
            continue
        entries.extend(
            classify_statements(
                _read_sql(up_file),
                migration=version,
                source=up_file.name,
                default_schema=default_schema,
                facts=facts,
            )
        )

    for py_file in sorted(_python_migrations(migrations_dir), key=lambda f: f.name):
        version = _version_from_migration_filename(py_file.name)
        if versions is not None and version not in versions:
            continue
        entries.append(
            ChangeEntry(
                kind="python_migration",
                object=py_file.name,
                migration=version,
                tier=None,
                detail=(
                    "non-SQL migration: confiture cannot read its DDL, so its "
                    "changes are unclassified — review by hand"
                ),
            )
        )

    return ChangeSet(changes=tuple(entries))


def classify_statements(
    sql: str,
    *,
    migration: str | None = None,
    source: str | None = None,
    default_schema: str = _DEFAULT_SCHEMA,
    facts: SchemaFacts | None = None,
) -> list[ChangeEntry]:
    """Classify every statement in ``sql``.

    ``source`` names the file and is the ``object`` for statements whose target
    cannot be determined. SQL the parser rejects yields an unclassified entry
    rather than an empty list, so a broken migration denies instead of reading as
    "nothing changes".
    """
    ctx = _Context(migration=migration, source=source, default_schema=default_schema, facts=facts)
    try:
        return _ast_entries(sql, ctx)
    except pglast.parser.ParseError as exc:
        return [ctx.unclassified("unparseable", None, f"pglast could not parse {source}: {exc}")]


def _python_migrations(migrations_dir: Path) -> Iterator[Path]:
    """`.py` migrations, filtered exactly as ``run_preflight`` filters them."""
    return (
        f
        for f in migrations_dir.glob("*.py")
        if f.name != "__init__.py" and not f.name.startswith("_")
    )


def _read_sql(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
