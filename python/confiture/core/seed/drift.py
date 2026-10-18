"""``confiture seed drift``: the seeded rows of a seed-built database against a live one (#743).

A rebuilt environment (dev, test, CI) gets its reference rows from the seed tree;
a migrate-only one (staging, production) gets only the rows a migration inserts.
A seed change with no migration reaches the first kind alone, and nothing fails
until a reference row is missing in production. This module compares the two:
:mod:`.drift_scope` decides what is compared, from the tree; this module lists the
tree's seed files and reads the rows.
"""

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from string.templatelib import Template
from typing import Any, Literal

import psycopg
from psycopg import sql as pgsql

from confiture.config.environment import Environment, SeedDriftSettings
from confiture.core import live_catalog
from confiture.core.builder import SchemaBuilder
from confiture.core.connection import open_connection
from confiture.core.linting.inventory import label_for
from confiture.core.schema_model import RelationName
from confiture.core.schema_read import SchemaRead
from confiture.core.schema_sources import read_schema
from confiture.core.seed.applier import SeedApplier
from confiture.core.seed.drift_scope import (
    Field,
    NotCompared,
    ScopedTable,
    SeedScope,
    config_identity,
    seed_scope,
)
from confiture.core.seed.seeded_database import seeded_database
from confiture.core.seed.validation.prep_seed.level_5_execution import Level5ExecutionValidator
from confiture.core.seed.validation.prep_seed.resolvers import read_resolution
from confiture.exceptions import ConfigurationError, SchemaError, SeedError
from confiture.url_redaction import redact_url

#: A row's key: each key field as PostgreSQL renders it as text.
Key = tuple[str | None, ...]

#: Every setting that changes how a value renders as text, pinned on both sides:
#: two servers with different defaults would otherwise disagree about equal values.
RENDERING: tuple[tuple[str, str], ...] = (
    ("TimeZone", "UTC"),
    ("DateStyle", "ISO, YMD"),
    ("IntervalStyle", "postgres"),
    ("extra_float_digits", "3"),
    ("bytea_output", "hex"),
)


def seed_files(
    env: str, project_dir: Path | None = None, *, seeds_dir: Path | None = None
) -> list[Path]:
    """The seed files a rebuilt *env* applies, in the order it applies them.

    The seed files in the environment's ``include_dirs`` (``confiture build``'s
    seeds, by its path rule), then, with *seeds_dir*, the files ``confiture seed
    apply`` applies from it: a rebuilt environment runs the one, then the other.
    """
    _schema, seeds = SchemaBuilder(env=env, project_dir=project_dir).categorize_sql_files()
    if seeds_dir is None:
        return seeds
    return [*seeds, *SeedApplier(seeds_dir=seeds_dir, env=env).find_seed_files()]


def scope_for(
    env: str,
    project_dir: Path | None = None,
    *,
    seeds_dir: Path | None = None,
    build: bool = False,
) -> SeedDriftReport:
    """What a seed-drift run of *env* would compare, compared with nothing (``--list-scope``)."""
    root = project_dir or Path.cwd()
    files = seed_files(env, project_dir, seeds_dir=seeds_dir)
    scope = seed_scope(
        [(label_for(path, root), path.read_text(encoding="utf-8")) for path in files],
        read_schema(env=env, project_dir=project_dir),
        Environment.load(env, project_dir=project_dir).seed_drift,
    )
    return SeedDriftReport(
        seed_side="built" if build else "database",
        against=None,
        scope=scope,
        not_compared=scope.not_compared,
        unused=scope.unused,
        compared=False,
    )


@dataclass(frozen=True)
class ChangedRow:
    """A row both databases hold under one key, with different values: each column that differs."""

    key: Key
    columns: tuple[tuple[str, str | None, str | None], ...]


@dataclass(frozen=True)
class TableDrift:
    """What differs in one table between the seed side and the live side."""

    table: str
    key: tuple[str, ...]
    key_basis: str
    mode: str
    seed_rows: int
    live_rows: int
    seed_only: tuple[Key, ...] = ()
    live_only: tuple[Key, ...] = ()
    changed: tuple[ChangedRow, ...] = ()
    accepted: tuple[Key, ...] = ()

    @property
    def drifted(self) -> bool:
        return bool(self.seed_only or self.live_only or self.changed)


@dataclass(frozen=True)
class SeedDriftReport:
    """A seed-drift run: every table compared, and everything that could not be."""

    seed_side: Literal["database", "built"]
    against: str | None
    scope: SeedScope
    tables: tuple[TableDrift, ...] = ()
    not_compared: tuple[NotCompared, ...] = ()
    unused: tuple[str, ...] = ()
    #: ``False`` for ``--list-scope``: what would be compared, and no comparison.
    compared: bool = True

    @property
    def skipped(self) -> tuple[tuple[str, str], ...]:
        return self.scope.skipped

    @property
    def has_drift(self) -> bool:
        """A difference no setting explains, or a setting that explains nothing."""
        return any(t.drifted for t in self.tables) or bool(self.unused)

    @property
    def complete(self) -> bool:
        """Every table in scope was compared."""
        return not self.not_compared

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed_side": {"source": self.seed_side},
            "against": self.against,
            "compared": self.compared,
            "has_drift": self.has_drift,
            "complete": self.complete,
            "scope": [
                {
                    "table": t.relation.qualified,
                    "staging": t.staging.qualified if t.staging else None,
                    "key": [field_name(f) for f in t.key],
                    "key_basis": t.key_basis,
                    "mode": t.mode,
                    "columns": [field_name(f) for f in t.columns],
                    "uncompared": [{"column": c, "reason": why} for c, why in t.uncompared],
                    "written_at": list(t.written_at),
                }
                for t in self.scope.tables
            ],
            "tables": [
                {
                    "table": t.table,
                    "key": list(t.key),
                    "key_basis": t.key_basis,
                    "mode": t.mode,
                    "seed_rows": t.seed_rows,
                    "live_rows": t.live_rows,
                    "seed_only": [list(k) for k in t.seed_only],
                    "live_only": [list(k) for k in t.live_only],
                    "changed": [
                        {
                            "key": list(c.key),
                            "columns": [
                                {"column": name, "seed": seed, "live": live}
                                for name, seed, live in c.columns
                            ],
                        }
                        for c in t.changed
                    ],
                    "accepted": [list(k) for k in t.accepted],
                }
                for t in self.tables
            ],
            "not_compared": [
                {"table": n.table, "reason": n.reason, "where": n.where} for n in self.not_compared
            ],
            "skipped": [{"table": name, "reason": why} for name, why in self.skipped],
            "unused": list(self.unused),
        }


def field_name(field: Field) -> str:
    """How a report names a compared value: ``fk_unit -> catalog.tb_unit.id`` for a dereference."""
    if field.via is None:
        return field.column
    return f"{field.column} -> {field.via.parent.qualified}.{', '.join(field.via.parent_key)}"


def _relation(name: RelationName) -> Template:
    return t"{name.schema:i}.{name.name:i}" if name.schema else t"{name.name:i}"


def _expression(field: Field) -> Template:
    """*field* as text: a column, or the parent row's stable key a foreign key points at."""
    if field.via is None:
        return t"t.{field.column:i}::text"
    via = field.via
    if len(via.parent_key) == 1:
        (key,) = via.parent_key
        value = t"p.{key:i}::text"
    else:
        value = t"ROW({pgsql.SQL(', ').join(t'p.{k:i}' for k in via.parent_key):q})::text"
    return (
        t"(SELECT {value:q} FROM {_relation(via.parent):q} p "
        t"WHERE p.{via.parent_column:i} = t.{field.column:i})"
    )


def _missing(conn: Any, table: ScopedTable) -> str | None:
    """Why *table* cannot be read on *conn*: a relation or a column that is not there."""
    needed: dict[tuple[str, str], set[str]] = {}
    for field in (*table.key, *table.columns):
        needed.setdefault(table.relation.identity, set()).add(field.column)
        if field.via is not None:
            parent = needed.setdefault(field.via.parent.identity, set())
            parent.update({field.via.parent_column, *field.via.parent_key})
    for (schema, name), wanted in needed.items():
        held = {c.folded for c in live_catalog.columns(conn, schema, name)}
        if not held:
            return f'relation "{schema}.{name}" does not exist'
        absent = sorted(wanted - held)
        if absent:
            return f"{schema}.{name} has no column {', '.join(absent)}"
    return None


def _rows(conn: Any, table: ScopedTable, keys: Sequence[Key] | None = None) -> dict[Key, Key]:
    """``{key: values}`` of *table*, every row or, with *keys*, only the rows under those keys."""
    keyed = [_expression(f) for f in table.key]
    selected = pgsql.SQL(", ").join([*keyed, *(_expression(f) for f in table.columns)])
    query = t"SELECT {selected:q} FROM {_relation(table.relation):q} t"
    if keys is not None:
        if not keys:
            return {}
        arrays = pgsql.SQL(", ").join(
            t"{[k[i] for k in keys]}::text[]" for i in range(len(table.key))
        )
        row = pgsql.SQL(", ").join(keyed)
        query = t"{query:q} WHERE ({row:q}) IN (SELECT * FROM unnest({arrays:q}))"
    width = len(table.key)
    return {tuple(r[:width]): tuple(r[width:]) for r in conn.execute(query).fetchall()}


@contextmanager
def read_only(conn: Any, timeout: str) -> Generator[Any]:
    """*conn* in one read-only transaction, rolled back, with the rendering settings pinned."""
    with conn.transaction(force_rollback=True):
        conn.execute(t"SET TRANSACTION READ ONLY")
        for name, value in (*RENDERING, ("statement_timeout", timeout), ("lock_timeout", timeout)):
            conn.execute(t"SELECT set_config({name}, {value}, true)")
        yield conn


def _diff(table: ScopedTable, seed: dict[Key, Key], live: dict[Key, Key]) -> TableDrift:
    names = [field_name(f) for f in table.columns]
    changed = tuple(
        ChangedRow(
            key,
            tuple(
                (name, a, b) for name, a, b in zip(names, values, live[key], strict=True) if a != b
            ),
        )
        for key, values in seed.items()
        if key in live and live[key] != values
    )
    return TableDrift(
        table=table.relation.qualified,
        key=tuple(field_name(f) for f in table.key),
        key_basis=table.key_basis,
        mode=table.mode,
        seed_rows=len(seed),
        live_rows=len(live),
        seed_only=tuple(k for k in seed if k not in live),
        live_only=() if table.mode == "subset" else tuple(k for k in live if k not in seed),
        changed=changed,
    )


def _accept(drift: TableDrift, accepted: set[Key]) -> TableDrift:
    """*drift* with the differences an ``accepted`` entry names moved out of the findings."""
    found = {*drift.seed_only, *drift.live_only, *(c.key for c in drift.changed)} & accepted
    if not found:
        return drift
    return TableDrift(
        table=drift.table,
        key=drift.key,
        key_basis=drift.key_basis,
        mode=drift.mode,
        seed_rows=drift.seed_rows,
        live_rows=drift.live_rows,
        seed_only=tuple(k for k in drift.seed_only if k not in found),
        live_only=tuple(k for k in drift.live_only if k not in found),
        changed=tuple(c for c in drift.changed if c.key not in found),
        accepted=tuple(sorted(found, key=str)),
    )


def _compare_table(
    table: ScopedTable, seed_conn: Any, live_conn: Any, settings: SeedDriftSettings
) -> TableDrift | NotCompared:
    """One table on both sides, each read under a savepoint so a failure costs that table only."""
    for side, conn in (("seed", seed_conn), ("live", live_conn)):
        missing = _missing(conn, table)
        if missing is not None:
            return NotCompared(table.relation.qualified, f"{missing} on the {side} side")
    if table.mode == "full":
        schema, name = table.relation.identity
        estimate = live_catalog.estimated_rows(live_conn, schema, name)
        if estimate is not None and estimate > settings.max_rows:
            return NotCompared(
                table.relation.qualified,
                f"the live side holds about {estimate} rows, more than seed_drift.max_rows "
                f"({settings.max_rows}); compare it with mode: subset, which reads the seed's keys only",
            )
    try:
        with seed_conn.transaction():
            seed = _rows(seed_conn, table)
        with live_conn.transaction():
            live = _rows(live_conn, table, list(seed) if table.mode == "subset" else None)
    except psycopg.Error as exc:
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        return NotCompared(table.relation.qualified, f"reading it failed: {first}")
    return _diff(table, seed, live)


def compare(
    scope: SeedScope,
    seed_conn: Any,
    live_conn: Any,
    settings: SeedDriftSettings,
    *,
    seed_side: Literal["database", "built"],
    against: str,
    against_env: str | None = None,
) -> SeedDriftReport:
    """Each table in *scope* on both connections; the caller owns them and their transactions.

    *against_env* is the ``--against`` environment's name, which keys
    ``seed_drift.accepted``; a URL has no accepted differences.
    """
    accepted = settings.accepted.get(against_env or "", []) if against_env else []
    by_table: dict[tuple[str, str], set[Key]] = {}
    for entry in accepted:
        identity = config_identity(entry.table)
        if identity is not None:
            by_table.setdefault(identity, set()).add(tuple(entry.key))
    tables: list[TableDrift] = []
    not_compared = list(scope.not_compared)
    used: set[tuple[tuple[str, str], Key]] = set()
    with (
        read_only(seed_conn, settings.statement_timeout),
        read_only(live_conn, settings.statement_timeout),
    ):
        for table in scope.tables:
            result = _compare_table(table, seed_conn, live_conn, settings)
            if isinstance(result, NotCompared):
                not_compared.append(result)
                continue
            keys = by_table.get(table.relation.identity, set())
            result = _accept(result, keys)
            used.update((table.relation.identity, k) for k in result.accepted)
            tables.append(result)
    unused = [
        *scope.unused,
        *(
            f"seed_drift.accepted.{against_env}: {entry.table} {list(entry.key)} matches no difference"
            for entry in accepted
            if (config_identity(entry.table), tuple(entry.key)) not in used
        ),
    ]
    return SeedDriftReport(
        seed_side=seed_side,
        against=against,
        scope=scope,
        tables=tuple(tables),
        not_compared=tuple(not_compared),
        unused=tuple(unused),
    )


def against_target(spec: str, project_dir: Path | None = None) -> tuple[Any, str, str | None]:
    """``(what to open, how a report names it, the environment name)`` for a ``--against`` value.

    A URL is opened as given and named masked. Anything else is an environment
    name, opened as its :class:`Environment`, so its ``ssh_tunnel`` is honoured.

    Raises:
        ConfigurationError: ``CONFIG_001`` for an environment with no config file.
    """
    if spec.startswith(("postgres://", "postgresql://")):
        return spec, redact_url(spec), None
    return Environment.load(spec, project_dir=project_dir), spec, spec


def _resolve(conn: Any, read: SchemaRead, settings: SeedDriftSettings) -> None:
    """Run the tree's prep-seed resolvers, parents first, as level 5 runs them.

    Raises:
        SeedError: a resolver failed, named with where it is written.
    """
    resolution = read_resolution(
        read, catalog_schema=settings.catalog_schema, prep_seed_schema=settings.prep_seed_schema
    )
    if not resolution.resolvers:
        return
    failed = Level5ExecutionValidator(catalog_schema=settings.catalog_schema).execute_resolutions(
        conn, resolution.resolvers
    )
    if failed:
        first = failed[0]
        raise SeedError(f"{first.message} ({first.file_path}:{first.line_number})")


@contextmanager
def built_side(
    server_url: str,
    env: str,
    project_dir: Path | None,
    files: Sequence[Path],
    read: SchemaRead,
    settings: SeedDriftSettings,
) -> Generator[Any]:
    """A scratch database built as confiture rebuilds *env*: schema, seed files, resolvers.

    The schema-only build, then each seed file on its own, in order, as
    ``migrate rebuild --seed`` and ``test-db`` build one, so a seed file that fails
    is named; then the prep-seed resolvers.
    """
    schema_sql = SchemaBuilder(env=env, project_dir=project_dir).build(schema_only=True)
    with (
        seeded_database(server_url, schema_sql, files) as (url, _applied),
        psycopg.connect(url, autocommit=True) as conn,
    ):
        _resolve(conn, read, settings)
        yield conn


def run(
    env: str,
    against: str,
    *,
    project_dir: Path | None = None,
    seeds_dir: Path | None = None,
    build: bool = False,
    scratch_url: str | None = None,
) -> SeedDriftReport:
    """Compare *env*'s seeded rows with *against*'s.

    The seed side is *env*'s own database, or with *build* a scratch database on
    *scratch_url* (else the environment's ``scratch_url``, never its
    ``database_url``) built from the tree and its seeds. A seed side that cannot be
    built is reported, not raised: the comparison did not run, and the tree's error
    is the reason.

    Raises:
        ConfigurationError: ``CONFIG_006`` when a database does not answer;
            ``CONFIG_001`` for ``--build`` with no scratch server, or an unknown
            ``--against`` environment.
    """
    environment = Environment.load(env, project_dir=project_dir)
    root = project_dir or Path.cwd()
    files = seed_files(env, project_dir, seeds_dir=seeds_dir)
    read = read_schema(env=env, project_dir=project_dir)
    settings = environment.seed_drift
    scope = seed_scope(
        [(label_for(path, root), path.read_text(encoding="utf-8")) for path in files],
        read,
        settings,
    )
    server = scratch_url or environment.scratch_url
    if build and server is None:
        raise ConfigurationError(
            "--build needs a scratch server to build the seed side on",
            error_code="CONFIG_001",
            resolution_hint="Pass --scratch-url, or set scratch_url in the environment",
        )
    target, label, against_env = against_target(against, project_dir)
    side: Literal["database", "built"] = "built" if build else "database"
    with open_connection(target) as live_conn:
        try:
            seed_cm = (
                built_side(server or "", env, project_dir, files, read, settings)
                if build
                else open_connection(environment)
            )
            with seed_cm as seed_conn:
                return compare(
                    scope,
                    seed_conn,
                    live_conn,
                    settings,
                    seed_side=side,
                    against=label,
                    against_env=against_env,
                )
        except (SchemaError, SeedError) as exc:
            if not build:
                raise
            return SeedDriftReport(
                seed_side=side,
                against=label,
                scope=scope,
                not_compared=(
                    *scope.not_compared,
                    NotCompared("seed side", f"building the seed side failed: {exc}"),
                ),
                unused=scope.unused,
            )
