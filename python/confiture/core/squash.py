"""Retire old migrations into one baseline: the schema they build, as one migration.

``migrate squash --through V`` replaces migrations 1..V with a single migration
whose SQL is the schema those migrations leave. Two sources for that SQL:

- **replay** (the default): apply 1..V to a scratch database and dump its schema,
  without confiture's own tables (the ledger, its steps, the lock holder);
- **build** (``--from-build``): the tree ``confiture build`` produces. The tree
  may have moved on since V, so it is used only once a drift check between it and
  the replayed database comes back empty (``VALID_006`` otherwise).

The SQL is embedded in the baseline; it never reads a schema file by path, so
nothing it installs changes after it is written. Its header is a
``-- confiture:squashed-baseline through=V versions=N digest=D`` directive. ``D``
is :func:`archived_digest` of the archived versions and their checksums. An
environment's ledger records the same checksums, so the ledger step compares
digests and never needs the archived files.

The baseline takes the version right after V (:func:`baseline_version`): V + 1
second for a timestamp, V + 1 for a number. It must sort before every later
migration; when it cannot, the caller gives one (``--version``) and
:func:`usable_version` checks it (``VALID_007`` otherwise).
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

import psycopg
from psycopg import sql as pgsql

from confiture.config.environment import Environment
from confiture.config.project import SquashConfig, load_project_config
from confiture.core import live_catalog
from confiture.core._migrator.discovery import (
    discover_migration_files,
    parse_migration_filename,
)
from confiture.core._migrator.squashed import DIRECTIVE, archived_digest
from confiture.core.checksum import compute_checksum
from confiture.core.drift import SchemaDriftDetector
from confiture.core.expected_db import ExpectedSchemaDB
from confiture.core.ledger import LIVE_ROWS, ledger_exists, table_identifier
from confiture.core.linting.inventory import build_model
from confiture.core.migrator import replay_migrations
from confiture.core.sql_lexer import name_parts
from confiture.core.step_runner import DONE, CheckpointStore, steps_table
from confiture.core.temp_database import clean_pg_dump_output, pg_dump_schema
from confiture.exceptions import ConfigurationError, MigrationError, ValidationError
from confiture.url_redaction import redact_credentials_in

_TIMESTAMP = "%Y%m%d%H%M%S"
_TIMESTAMP_DIGITS = 14
_DEFAULT_TABLE = "tb_confiture"
#: Every file a migration version is made of.
_SUFFIXES = (".py", ".up.sql", ".down.sql", ".verify.sql")
#: Where the squashed files go, inside the migrations directory: discovery lists
#: the directory flat, so nothing in it is a migration any more.
ARCHIVE = "archive"
#: A baseline's down: the history before it is gone, so there is nothing to go back to.
BASELINE_DOWN = """DO $$
BEGIN
    RAISE EXCEPTION 'a squashed baseline cannot be rolled back: the migrations it replaced are archived';
END
$$;
"""


@dataclass(frozen=True)
class SquashPlan:
    """What a squash through ``through`` archives and writes.

    Attributes:
        through: The last version squashed.
        versions: Every version squashed, in order.
        archived: Every file those versions are made of.
        version: The baseline's version.
        digest: :func:`archived_digest` of the squashed versions and checksums.
        sql: The baseline's SQL, header included.
        source: ``"replay"`` or ``"build"``.
    """

    through: str
    versions: tuple[str, ...]
    archived: tuple[Path, ...]
    version: str
    digest: str
    sql: str
    source: str

    @property
    def baseline_name(self) -> str:
        """The baseline's filename."""
        return f"{self.version}_squashed_baseline.up.sql"


@dataclass(frozen=True)
class SquashResult:
    """What :func:`execute_squash` wrote and moved.

    Attributes:
        baseline: The baseline's ``.up.sql``.
        down: Its ``.down.sql``, which refuses.
        moved: ``(old, new)`` for each archived file; ``new`` is ``None`` when deleted.
    """

    baseline: Path
    down: Path
    moved: tuple[tuple[Path, Path | None], ...]


def execute_squash(plan: SquashPlan, migrations_dir: Path, *, delete: bool = False) -> SquashResult:
    """Write the baseline and archive (or delete) what it replaced.

    Raises:
        ValidationError: ``VALID_007`` when the baseline's file, or an archived
            file's destination, already exists. Nothing is written then.
    """
    baseline = migrations_dir / plan.baseline_name
    down = baseline.with_name(plan.baseline_name.replace(".up.sql", ".down.sql"))
    archive = migrations_dir / ARCHIVE
    targets = [None if delete else archive / path.name for path in plan.archived]
    taken = [p for p in (baseline, down, *targets) if p is not None and p.exists()]
    if taken:
        raise ValidationError(
            "squash refused: " + ", ".join(str(p) for p in taken) + " already exists",
            error_code="VALID_007",
            resolution_hint="Pass --version with another version, or clear the archive",
        )
    baseline.write_text(plan.sql, encoding="utf-8")
    down.write_text(BASELINE_DOWN, encoding="utf-8")
    moved: list[tuple[Path, Path | None]] = []
    for path, target in zip(plan.archived, targets, strict=True):
        if target is None:
            path.unlink()
        else:
            archive.mkdir(exist_ok=True)
            shutil.move(path, target)
        moved.append((path, target))
    return SquashResult(baseline=baseline, down=down, moved=tuple(moved))


def baseline_version(through: str, later: Sequence[str]) -> str | None:
    """The version right after ``through``, when it sorts before every later one."""
    if not through.isdigit():
        return None
    if len(through) == _TIMESTAMP_DIGITS:
        after = datetime.strptime(through, _TIMESTAMP) + timedelta(seconds=1)
        candidate = after.strftime(_TIMESTAMP)
    else:
        candidate = str(int(through) + 1).zfill(len(through))
    return candidate if usable_version(candidate, through, later) else None


def usable_version(version: str, through: str, later: Sequence[str]) -> bool:
    """Whether ``version`` sorts after ``through`` and before every later version."""
    return through < version and all(version < other for other in later)


@dataclass(frozen=True)
class EnvironmentCheck:
    """One environment :func:`check_environments` asked, or skipped."""

    name: str
    skipped: bool


def check_environments(
    project_dir: Path, versions: Sequence[str], through: str, *, now: datetime | None = None
) -> list[EnvironmentCheck]:
    """Ask every ``db/environments/*.yaml`` whether a squash through ``through`` is safe there.

    An environment passes when its ledger records every squashed version, recorded
    ``through`` at least ``squash.min_age_days`` ago, and has no online migration
    up to the cut unfinished. Those listed in ``squash.skip_environments`` are not
    asked. With none asked, a timestamp version's own date is its age.

    Raises:
        ValidationError: ``VALID_009``, naming each environment that fails and why.
    """
    settings = load_project_config(project_dir).squash or SquashConfig()
    min_age = timedelta(days=settings.min_age_days)
    moment = now or datetime.now(UTC)
    checked: list[EnvironmentCheck] = []
    problems: list[str] = []
    for path in sorted((project_dir / "db" / "environments").glob("*.yaml")):
        name = path.stem
        skipped = name in settings.skip_environments
        checked.append(EnvironmentCheck(name, skipped))
        if not skipped:
            problems.extend(
                f"{name}: {problem}"
                for problem in _environment_problems(
                    project_dir, name, versions, through, moment - min_age
                )
            )
    if not any(not check.skipped for check in checked):
        problems.extend(_undated_problems(through, moment - min_age, settings.min_age_days))
    if problems:
        raise ValidationError(
            "squash refused:\n  " + "\n  ".join(problems),
            error_code="VALID_009",
            resolution_hint=(
                "Deploy the squashed migrations there first, cut at an older version, or list "
                "an environment that cannot be reached in db/project.yaml squash.skip_environments"
            ),
        )
    return checked


def _environment_problems(
    project_dir: Path, name: str, versions: Sequence[str], through: str, latest: datetime
) -> list[str]:
    try:
        environment = Environment.load(name, project_dir=project_dir)
        with psycopg.connect(environment.database_url, connect_timeout=10) as conn:
            return _ledger_problems(
                conn, environment.migration.tracking_table, versions, through, latest
            )
    except (psycopg.Error, ConfigurationError) as exc:
        return [f"cannot be asked ({redact_credentials_in(str(exc))})"]


def _ledger_problems(
    conn: psycopg.Connection, table: str, versions: Sequence[str], through: str, latest: datetime
) -> list[str]:
    if not ledger_exists(conn, table):
        return [f"has no ledger ({table}): every squashed migration is pending"]
    rows = dict(
        conn.execute(
            pgsql.SQL("SELECT version, applied_at FROM {} AS ledger WHERE {}").format(
                table_identifier(table), LIVE_ROWS
            )
        ).fetchall()
    )
    problems: list[str] = []
    pending = [version for version in versions if version not in rows]
    if pending:
        problems.append("has " + ", ".join(pending) + " pending")
    applied = rows.get(through)
    if applied is not None and applied > latest:
        days = (datetime.now(UTC) - latest).days
        problems.append(f"applied {through} on {applied:%Y-%m-%d}, less than {days} days ago")
    steps = steps_table(table)
    if ledger_exists(conn, steps):
        unfinished = sorted(
            {r.migration for r in CheckpointStore(conn, steps).records() if r.state != DONE}
            & set(versions)
        )
        if unfinished:
            problems.append("has an online migration unfinished: " + ", ".join(unfinished))
    return problems


def _undated_problems(through: str, latest: datetime, min_age_days: int) -> list[str]:
    """With no environment asked, a timestamp version's own date is its age."""
    if min_age_days == 0:
        return []
    if len(through) == _TIMESTAMP_DIGITS and through.isdigit():
        written = datetime.strptime(through, _TIMESTAMP).replace(tzinfo=UTC)
        if written <= latest:
            return []
        return [f"{through} is less than {min_age_days} days old, and no environment was asked"]
    return [
        f"no environment was asked, and {through} carries no date: its age cannot be "
        "established (set squash.min_age_days to 0 to cut without one)"
    ]


def squashed_versions(migrations_dir: Path, through: str) -> tuple[str, ...]:
    """Every migration version up to and including ``through``, in order.

    Raises:
        MigrationError: ``through`` is not a migration in the directory.
    """
    ordered = [
        parse_migration_filename(f.name)[0] for f in discover_migration_files(migrations_dir)
    ]
    if through not in ordered:
        raise MigrationError(
            f"Migration version '{through}' not found in {migrations_dir}",
            through,
            resolution_hint="Run 'confiture migrate status' to list the versions on disk",
        )
    return tuple(ordered[: ordered.index(through) + 1])


def plan_squash(
    migrations_dir: Path,
    through: str,
    *,
    server_url: str,
    version: str | None = None,
    build_sql: str | None = None,
    migration_table: str | None = None,
) -> SquashPlan:
    """Plan a squash of every migration up to ``through``; write nothing.

    Args:
        migrations_dir: The migrations directory.
        through: The last version to squash.
        server_url: A writable server for the scratch database.
        version: The baseline's version, when :func:`baseline_version` has none.
        build_sql: The tree's DDL, to use instead of a dump once proven equal.
        migration_table: The ledger, left out of the dump.

    Raises:
        MigrationError: ``through`` is not a migration in the directory.
        ValidationError: ``VALID_007`` when the baseline has no usable version,
            ``VALID_006`` when ``build_sql`` is not the schema as of ``through``.
        SchemaError: A migration failed to replay, or ``pg_dump`` failed.
    """
    files = discover_migration_files(migrations_dir)
    versions = squashed_versions(migrations_dir, through)
    later = [parse_migration_filename(f.name)[0] for f in files[len(versions) :]]
    chosen = _chosen_version(through, later, version)
    digest = archived_digest(
        (v, compute_checksum(f)) for v, f in zip(versions, files, strict=False)
    )
    body, source = _snapshot(migrations_dir, through, server_url, build_sql, migration_table)
    header = (
        f"-- confiture:{DIRECTIVE} through={through} versions={len(versions)} digest={digest}\n"
    )
    return SquashPlan(
        through=through,
        versions=versions,
        archived=tuple(_files_of(migrations_dir, versions)),
        version=chosen,
        digest=digest,
        sql=header + body,
        source=source,
    )


def _chosen_version(through: str, later: Sequence[str], given: str | None) -> str:
    chosen = given if given is not None else baseline_version(through, later)
    if chosen is None or not usable_version(chosen, through, later):
        following = f" and before {later[0]}" if later else ""
        raise ValidationError(
            f"squash refused: the baseline needs a version after {through}{following}, "
            f"and {chosen or 'the next one'} is not free",
            error_code="VALID_007",
            resolution_hint=f"Pass --version with a version that sorts after {through}{following}",
        )
    return chosen


def _files_of(migrations_dir: Path, versions: Sequence[str]) -> list[Path]:
    wanted = set(versions)
    return sorted(
        path
        for suffix in _SUFFIXES
        for path in migrations_dir.glob(f"*{suffix}")
        if not path.name.startswith("_") and parse_migration_filename(path.name)[0] in wanted
    )


def _snapshot(
    migrations_dir: Path,
    through: str,
    server_url: str,
    build_sql: str | None,
    migration_table: str | None,
) -> tuple[str, str]:
    """``(sql, source)``: the dumped replay, or the tree once a drift check says it is the same."""
    table = migration_table or _DEFAULT_TABLE
    scratch = ExpectedSchemaDB(
        server_url, migrations_dir=migrations_dir, migration_table=migration_table
    ).from_base_plus_migrations(replay=partial(replay_migrations, target=through))
    with scratch as conn:
        if build_sql is None:
            own = {*SchemaDriftDetector.SYSTEM_TABLES, _bare(table), _bare(steps_table(table))}
            raw = pg_dump_schema(scratch.url, exclude_tables=sorted(own))
            return clean_pg_dump_output(raw, keep_extensions=True), "replay"
        replayed = live_catalog.read(
            conn,
            schemas=live_catalog.user_schemas(conn),
            routines=True,
            views=True,
            triggers=True,
        )
        report = SchemaDriftDetector(conn, ignore_tables=[table]).compare_schemas(
            build_model(build_sql), replayed, objects=True
        )
    if report.drift_items:
        listed = "\n  ".join(item.message for item in report.drift_items)
        raise ValidationError(
            f"squash refused: the tree is not the schema migrations 1..{through} build:\n  {listed}",
            error_code="VALID_006",
            resolution_hint="Squash from the replay (drop --from-build), or cut where the tree is",
        )
    return build_sql, "build"


def _bare(table: str) -> str:
    """The table part of a ledger name; ``pg_dump`` matches a bare name in every schema."""
    parts = name_parts(table)
    return parts[-1] if parts else table
