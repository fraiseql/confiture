"""Orchestrator for 5-level prep-seed validation with progressive execution.

This module coordinates running all validation levels (1-5) sequentially,
accumulating violations, and optionally stopping early on CRITICAL violations.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import psycopg

from confiture.core import live_catalog
from confiture.core.builder import files_under
from confiture.core.connection import Connection, create_connection, require_mode
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import SchemaModel, Table
from confiture.core.schema_sources import SchemaRead, read_schema
from confiture.core.seed.validation.prep_seed.level_1_seed_files import (
    Level1SeedValidator,
)
from confiture.core.seed.validation.prep_seed.level_2_schema import (
    Level2SchemaValidator,
)
from confiture.core.seed.validation.prep_seed.level_3_resolvers import (
    Level3ResolutionValidator,
)
from confiture.core.seed.validation.prep_seed.level_4_runtime import (
    Level4RuntimeValidator,
)
from confiture.core.seed.validation.prep_seed.level_5_execution import (
    Level5ExecutionValidator,
)
from confiture.core.seed.validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedReport,
    PrepSeedViolation,
    ViolationSeverity,
)
from confiture.core.seed.validation.prep_seed.resolvers import Resolver, find_resolvers
from confiture.exceptions import ConfigurationError, ConfiturError, SchemaError, SeedError
from confiture.models.warnings import BuildWarning

#: The validation levels there are.
LEVELS = range(1, 6)

#: The first level that reads the schema directory.
FIRST_SCHEMA_LEVEL = 2

#: The first level that reads the resolution functions.
FIRST_RESOLVER_LEVEL = 3

#: The first level that runs against a database.
FIRST_DATABASE_LEVEL = 4


def _read(path: Path, error: type[ConfiturError]) -> str:
    """*path*'s UTF-8 text, or *error* naming it: a file validation cannot read did not pass."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise error(
            f"Cannot read {path}: {exc}",
            resolution_hint="Validation reads every file it checks as UTF-8 text.",
        ) from exc


@dataclass
class SchemaTables:
    """The model's tables, sorted onto the two sides level 2 compares.

    Keyed by ``(schema, name)``: a bare table name is not an identity — keyed on
    it, ``tenant.tb_x`` and ``etl.tb_x`` would be one entry. ``schemas_seen``
    is every schema the tree actually declares into, so a tree with nothing in
    either configured schema can say so rather than pass empty.
    """

    prep: dict[tuple[str, str], Table] = field(default_factory=dict)
    catalog: dict[tuple[str, str], Table] = field(default_factory=dict)
    schemas_seen: set[str] = field(default_factory=set)


@dataclass
class OrchestrationConfig:
    """Configuration for orchestrating prep-seed validation.

    Attributes:
        max_level: Maximum validation level to run (1-5)
        seeds_dir: Directory containing seed files
        schema_dir: Directory containing schema files
        database_url: Optional database URL for levels 4-5. Internal configuration,
            so it keeps the name the CLI's option has; the seam's
            :func:`validate_seeds` spells it ``database``.
        connection: A caller's connection for levels 4-5, in place of a URL: used
            inside a savepoint that is rolled back, never committed or closed
        stop_on_critical: Stop early if CRITICAL violation found (default: True)
        show_progress: Show progress indicators during validation (default: True)
        prep_seed_schema: Schema name for prep-seed tables (default: "prep_seed")
        catalog_schema: Schema name for final tables (default: "catalog")
        tables_to_validate: Optional list of specific tables to validate
        level_5_mode: Validation mode for Level 5 ("standard" or "comprehensive")
    """

    max_level: int
    seeds_dir: Path
    schema_dir: Path
    database_url: str | None = None
    connection: Connection | None = None
    stop_on_critical: bool = True
    show_progress: bool = True
    prep_seed_schema: str = "prep_seed"
    catalog_schema: str = "catalog"
    tables_to_validate: list[str] | None = None
    level_5_mode: str = "standard"


class PrepSeedOrchestrator:
    """Orchestrates 5-level prep-seed validation with progressive execution.

    Runs validators 1→N sequentially, accumulates violations across levels,
    and optionally stops early on CRITICAL violations.

    Example:
        >>> config = OrchestrationConfig(
        ...     max_level=3,
        ...     seeds_dir=Path("db/seeds/prep"),
        ...     schema_dir=Path("db/schema"),
        ... )
        >>> orchestrator = PrepSeedOrchestrator(config)
        >>> report = orchestrator.run()
        >>> if report.has_violations:
        ...     print(f"Found {report.violation_count} violations")
    """

    def __init__(self, config: OrchestrationConfig) -> None:
        """Initialize orchestrator.

        Args:
            config: Orchestration configuration
        """
        self.config = config
        self._schema: SchemaRead | None = None
        self._found: list[Resolver] | None = None

    def run(self) -> PrepSeedReport:
        """Run validation levels 1 through max_level.

        Runs validators sequentially, accumulating violations. Stops early on
        CRITICAL violations if configured.

        Returns:
            PrepSeedReport with accumulated violations from all levels

        Raises:
            ConfigurationError: a max_level outside 1-5.
            ValueError: levels 4-5 with neither a database_url nor a connection
            SeedError: ``SEED_001`` for a seeds_dir that is not a directory, or a
                seed file level 1 cannot read as UTF-8 text.
            SchemaError: ``SCHEMA_201`` for a schema_dir that is not a directory
                when a level that reads it runs (2 and up); ``SCHEMA_001`` for a
                schema file levels 2-3 cannot read as UTF-8 text.
        """
        if self.config.max_level not in LEVELS:
            raise ConfigurationError(
                f"max_level {self.config.max_level} is not a validation level: "
                f"levels run {LEVELS.start} to {LEVELS.stop - 1}",
                resolution_hint="Pass max_level=3 for the static levels, 5 for all of them.",
            )
        if self.config.max_level >= FIRST_DATABASE_LEVEL and not (
            self.config.database_url or self.config.connection is not None
        ):
            msg = "database_url or connection required for levels 4-5"
            raise ValueError(msg)
        self._require_directories()

        # Initialize report
        report = PrepSeedReport()

        # Level 1: Seed file validation
        if self.config.max_level >= 1:
            violations = self._run_level_1(report)
            report.violations.extend(violations)
            self._record_scanned_files_level1(report)

            if self._should_exit_early(report):
                return report

        # Level 2: Schema consistency
        if self.config.max_level >= 2:
            violations = self._run_level_2()
            report.violations.extend(violations)

            if self._should_exit_early(report):
                return report

        # Level 3: Resolution function validation (CRITICAL level)
        if self.config.max_level >= FIRST_RESOLVER_LEVEL:
            violations = self._no_resolver() + self._run_level_3()
            report.violations.extend(violations)

            if self._should_exit_early(report):
                return report

        # Level 4: Runtime validation
        if self.config.max_level >= 4:
            violations = self._run_level_4()
            report.violations.extend(violations)

            if self._should_exit_early(report):
                return report

        # Level 5: Full execution
        if self.config.max_level >= 5:
            violations = self._run_level_5()
            report.violations.extend(violations)

        return report

    def _require_directories(self) -> None:
        """Refuse a directory that is not there: nothing read is not a clean result."""
        if not self.config.seeds_dir.is_dir():
            raise SeedError(
                f"Seeds directory not found: {self.config.seeds_dir}",
                seed_file=str(self.config.seeds_dir),
                resolution_hint="Pass the directory the seed files are in, as it is on disk.",
            )
        if self.config.max_level >= FIRST_SCHEMA_LEVEL and not self.config.schema_dir.is_dir():
            raise SchemaError(
                f"Schema directory not found: {self.config.schema_dir}",
                error_code="SCHEMA_201",
                resolution_hint="Pass the directory the schema's DDL is in, as it is on disk.",
            )

    def _seed_files(self) -> list[Path]:
        """The seed files every level reads: the tree ``seed apply`` loads, in its order."""
        return files_under(self.config.seeds_dir)

    def _run_level_1(self, report: PrepSeedReport) -> list[PrepSeedViolation]:
        """Run Level 1: every statement of every seed file, every row of it.

        A UUID column is one the schema types ``uuid`` when the schema can be
        read; otherwise the prep-seed convention names them, and the report
        says which it was.
        """
        validator = Level1SeedValidator(
            self._level_1_model(), prep_seed_schema=self.config.prep_seed_schema
        )
        violations: list[PrepSeedViolation] = []

        for file_path in self._seed_files():
            content = _read(file_path, SeedError)
            violations.extend(validator.validate_seed_file(content, str(file_path)))

        report.uuid_basis = validator.uuid_basis
        report.rows_read = dict(validator.rows_read)
        return violations

    def _level_1_model(self) -> SchemaModel | None:
        """The schema's model for level 1, or ``None`` when there is none to read.

        Level 1 needs no schema: a directory that is not there, or a tree that
        cannot be read or does not parse, leaves the convention to name the UUID
        columns, and the report's ``uuid_basis`` says so — level 2 reports that
        tree when it runs.
        """
        if not self.config.schema_dir.is_dir():
            return None
        try:
            return self._read_schema().model
        except SchemaError:
            return None

    def _run_level_2(self) -> list[PrepSeedViolation]:
        """Run Level 2: Schema consistency validation.

        Validates that prep_seed tables have corresponding final tables
        with correct schema patterns (trinity pattern, FK mappings, etc.).

        Returns:
            List of violations found
        """
        try:
            read = self._read_schema()
        except SchemaError as exc:
            if exc.error_code != "DIFFER_400":
                raise
            return [self._unparseable(exc)]
        tables = self._schema_tables(read.model)
        violations = [self._duplicate(warning) for warning in read.warnings]

        if not tables.prep:
            violations.extend(self._nothing_to_compare(tables))
            return violations

        # The catalog counterpart of a prep-seed table is the same name in the
        # configured catalog schema — the pairing is across schemas, by name,
        # which is why the *side* a table is on is read from its qualifier.
        catalog_schema = self.config.catalog_schema.lower()

        def get_final_table(table_name: str) -> Table | None:
            return tables.catalog.get((catalog_schema, table_name))

        validator = Level2SchemaValidator(
            get_final_table=get_final_table,
            locate=lambda table: self._where(table.schema or DEFAULT_SCHEMA, table.name),
            locate_resolver=self._resolver_of,
            prep_seed_schema=self.config.prep_seed_schema,
            catalog_schema=self.config.catalog_schema,
        )
        for prep_table in tables.prep.values():
            violations.extend(validator.validate_schema_mapping(prep_table))

        return violations

    def _run_level_3(self) -> list[PrepSeedViolation]:
        """Run Level 3: each resolver's body against the schema's tables."""
        resolvers = self._discovered()
        if not resolvers:
            return []
        validator = Level3ResolutionValidator(
            self._read_schema().model,
            prep_seed_schema=self.config.prep_seed_schema,
            catalog_schema=self.config.catalog_schema,
        )
        return [violation for resolver in resolvers for violation in validator.validate(resolver)]

    def _no_resolver(self) -> list[PrepSeedViolation]:
        """A schema holding no resolver: levels 3-5 checked nothing, which is not a pass."""
        try:
            if self._resolvers():
                return []
        except SchemaError as exc:
            if exc.error_code != "DIFFER_400":
                raise
            return []
        return [
            PrepSeedViolation(
                pattern=PrepSeedPattern.MISSING_RESOLVER_FUNCTION,
                severity=ViolationSeverity.WARNING,
                message=(
                    f"no resolution function found in {self.config.schema_dir}: no routine "
                    f"it defines is named fn_resolve*, so levels 3-5 check no resolver"
                ),
                file_path=str(self.config.schema_dir),
                line_number=1,
                impact="Resolution functions were not validated",
            )
        ]

    def _run_level_4(self) -> list[PrepSeedViolation]:
        """Run Level 4: Runtime validation.

        Connects to database and validates that resolution functions
        can execute without errors (using SAVEPOINT for safety).

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        resolvers = self._discovered()
        if not resolvers:
            return violations

        try:
            with self._database() as connection:
                violations.extend(self._check_resolvers(connection, resolvers))
        except Exception as e:  # Reason: level-4 reaches the database through create_connection; any failure is a CRITICAL violation, not a crash
            violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Database connection failed: {e!s}",
                    file_path="database_url",
                    line_number=1,
                    impact="Cannot validate resolution functions",
                )
            )

        return violations

    @contextlib.contextmanager
    def _database(self) -> Iterator[psycopg.Connection]:
        """The connection levels 4 and 5 run on, in a transaction nothing outlives.

        A URL's connection is this run's: opened here, rolled back and closed. A
        caller's connection runs inside a savepoint rolled back on the way out, so
        its transaction holds afterwards what it held before; it is never
        committed or closed here.
        """
        if self.config.connection is not None:
            conn = cast("psycopg.Connection", self.config.connection)
            conn.execute("SAVEPOINT confiture_validate_seeds")
            try:
                yield conn
            finally:
                conn.execute("ROLLBACK TO SAVEPOINT confiture_validate_seeds")
                conn.execute("RELEASE SAVEPOINT confiture_validate_seeds")
            return
        conn = create_connection({"database_url": self.config.database_url})
        try:
            yield conn
        finally:
            with contextlib.suppress(Exception):
                conn.rollback()
            with contextlib.suppress(Exception):
                conn.close()

    def _check_resolvers(
        self, connection: psycopg.Connection, resolvers: list[Resolver]
    ) -> list[PrepSeedViolation]:
        """Level 4 on an open connection: each resolver's table, then a dry run."""
        violations: list[PrepSeedViolation] = []

        # Define callbacks for table/column lookups
        def table_exists(schema: str, table: str) -> bool:
            try:
                return live_catalog.relation_exists(
                    connection, schema, table, kinds=live_catalog.TABLE_LIKE
                )
            except psycopg.Error:
                return False

        # Create validator with callbacks
        validator = Level4RuntimeValidator(table_exists=table_exists)

        for resolver in resolvers:
            runtime_violations = validator.validate_runtime(
                resolver,
                target_schema=self.config.catalog_schema,
                target_table=resolver.table,
            )
            violations.extend(runtime_violations)

            # Skip dry-run if table doesn't exist
            if runtime_violations:
                continue

            # Dry-run the resolution function with SAVEPOINT
            try:
                violations.extend(validator.dry_run_resolution(resolver, connection))
            except Exception as e:  # Reason: dry-running a user resolution function; any failure is a reported violation
                violations.append(
                    PrepSeedViolation(
                        pattern=PrepSeedPattern.MISSING_FK_TRANSFORMATION,
                        severity=ViolationSeverity.ERROR,
                        message=(f"Failed to validate {resolver.name}: {e!s}"),
                        file_path=resolver.file,
                        line_number=resolver.line,
                        impact="Resolution function validation failed",
                    )
                )

        return violations

    def _run_level_5(self) -> list[PrepSeedViolation]:
        """Run Level 5: Full execution validation.

        Executes seeds, runs resolution functions, and validates results
        for data integrity issues (NULL FKs, duplicates, constraint violations).

        Returns:
            List of violations found
        """
        violations: list[PrepSeedViolation] = []

        # In the order `seed apply` loads them: a file may reference the rows of
        # one before it.
        seed_file_paths = [str(f) for f in self._seed_files()]

        if not seed_file_paths:
            # No seeds to execute
            return violations

        resolvers = self._discovered()
        target_tables = self.config.tables_to_validate or [r.table for r in resolvers]

        try:
            with self._database() as connection:
                # Every level-5 query is qualified with the configured
                # `catalog_schema`, never a hardwired `catalog.`.
                validator = Level5ExecutionValidator(
                    catalog_schema=self.config.catalog_schema, locate=self._locate
                )
                run = (
                    validator.execute_full_cycle_comprehensive
                    if self.config.level_5_mode == "comprehensive"
                    else validator.execute_full_cycle
                )
                violations.extend(
                    run(
                        connection=connection,
                        seed_files=seed_file_paths,
                        resolution_functions=resolvers,
                        tables=target_tables,
                    )
                )
        except Exception as e:  # Reason: level-5 executes arbitrary seed SQL; any failure is a CRITICAL violation, not a crash
            violations.append(
                PrepSeedViolation(
                    pattern=PrepSeedPattern.PREP_SEED_TARGET_MISMATCH,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Level 5 execution failed: {e!s}",
                    file_path="database_url",
                    line_number=1,
                    impact="Could not validate seed execution",
                )
            )

        return violations

    def _should_exit_early(self, report: PrepSeedReport) -> bool:
        """Check if orchestrator should exit early.

        Early exit occurs when:
        1. stop_on_critical is True AND
        2. Report contains at least one CRITICAL violation

        Args:
            report: Current report to check

        Returns:
            True if should exit early, False otherwise
        """
        if not self.config.stop_on_critical:
            return False

        return any(v.severity == ViolationSeverity.CRITICAL for v in report.violations)

    def _record_scanned_files_level1(self, report: PrepSeedReport) -> None:
        """Record scanned files from Level 1 to report."""
        for file_path in self._seed_files():
            report.add_file_scanned(str(file_path))

    def _read_schema(self) -> SchemaRead:
        """The schema tree as one model, read once and kept for every level that asks.

        The tree is read as ``confiture build`` reads it — every ``.sql`` under
        ``schema_dir``, in path order — so an ``ALTER`` in one file folds into
        the table another file creates.

        Raises:
            SchemaError: ``DIFFER_400`` naming the file and line PostgreSQL's
                parser rejected — level 2 reports it as a finding — and
                ``SCHEMA_001`` naming a file that is not UTF-8, which it does not:
                a file the run could not read is an error, as at levels 1 and 3.
        """
        if self._schema is None:
            self._schema = read_schema(self.config.schema_dir)
        return self._schema

    def _schema_tables(self, model: SchemaModel) -> SchemaTables:
        """The model's tables, on the side their qualifier puts them.

        Which side a table is on is a fact the statement carries:
        ``CREATE TABLE catalog.tb_manufacturer`` is in ``catalog``, and
        ``Table.schema`` holds it. The file's path is never consulted: a
        directory name says nothing about where the DDL in it lands, and
        ``examples/06`` declares ``tb_manufacturer`` on both sides (#317).

        Identity is ``(schema, name)`` with a missing qualifier folded to
        :data:`~confiture.core.schema_identity.DEFAULT_SCHEMA`, so a table in
        neither configured schema is on neither side rather than colliding with
        one that is.
        """
        tables = SchemaTables()
        sides = {
            self.config.prep_seed_schema.lower(): tables.prep,
            self.config.catalog_schema.lower(): tables.catalog,
        }
        for table in model.tables.values():
            schema = (table.schema or DEFAULT_SCHEMA).lower()
            tables.schemas_seen.add(schema)
            side = sides.get(schema)
            if side is not None:
                side[(schema, table.name)] = table
        return tables

    def _unparseable(self, exc: SchemaError) -> PrepSeedViolation:
        """A schema file PostgreSQL's parser rejects: a finding naming it, never a skip."""
        file = (exc.context or {}).get("file")
        return PrepSeedViolation(
            pattern=PrepSeedPattern.MISSING_FK_MAPPING,
            severity=ViolationSeverity.CRITICAL,
            message=str(exc).split("\n", 1)[0],
            file_path=str(file or self.config.schema_dir),
            line_number=int((exc.context or {}).get("line") or 1),
            impact="Level 2 compared nothing: PostgreSQL rejects the schema as written",
        )

    def _duplicate(self, warning: BuildWarning) -> PrepSeedViolation:
        """One table defined twice. ``confiture build`` keeps the first definition —
        ``duplicates.wins``' answer — and so does the model level 2 validates (#313).
        """
        return PrepSeedViolation(
            pattern=PrepSeedPattern.MISSING_FK_MAPPING,
            severity=ViolationSeverity.WARNING,
            message=warning.message,
            file_path=str(self.config.schema_dir),
            line_number=1,
            impact="Level 2 validates the definition the build keeps",
        )

    def _nothing_to_compare(self, tables: SchemaTables) -> list[PrepSeedViolation]:
        """Level 2 looked at a schema tree and found no prep-seed table in it.

        Returning no violations for a tree it never compared would be a silent
        pass. A table is placed by its qualifier, never by its path, so a tree
        whose DDL never names the prep-seed schema reaches here; saying which
        schemas the files actually declare is the difference between "nothing is
        wrong" and "nothing was checked".
        """
        if not tables.schemas_seen:
            return []
        return [
            PrepSeedViolation(
                pattern=PrepSeedPattern.PREP_SEED_TARGET_MISMATCH,
                severity=ViolationSeverity.WARNING,
                message=(
                    f"No table is declared in the configured prep-seed schema "
                    f"'{self.config.prep_seed_schema}'; the schema files declare tables in "
                    f"{', '.join(sorted(tables.schemas_seen))}. Level 2 compared nothing."
                ),
                file_path=str(self.config.schema_dir),
                line_number=1,
                impact="Schema mapping between prep-seed and final tables was not validated",
            )
        ]

    def _resolvers(self) -> list[Resolver]:
        """The resolvers the schema defines, parents first, read once.

        A resolver is found by the name its ``CREATE`` gives it, never by the
        file it is written in (#385).

        Raises:
            SchemaError: as :meth:`_read_schema`.
        """
        if self._found is None:
            self._found = find_resolvers(
                self._read_schema(), catalog_schema=self.config.catalog_schema
            )
        return self._found

    def _discovered(self) -> list[Resolver]:
        """:meth:`_resolvers` for levels 4-5: a schema that does not parse holds none.

        Level 2 has reported that schema as a finding naming its file and line.
        """
        try:
            return self._resolvers()
        except SchemaError as exc:
            if exc.error_code != "DIFFER_400":
                raise
            return []

    def _locate(self, table: str) -> tuple[str, int]:
        """The file and line ``<catalog>.<table>`` is created on, for a level-5 finding."""
        return self._where(self.config.catalog_schema, table)

    def _where(self, schema: str, table: str) -> tuple[str, int]:
        """The file and line ``<schema>.<table>`` is created on, as the schema read found it.

        A table the read holds no file for — the schema is not read, or does not
        parse — is named as the schema directory, never as a path made up from
        the table's name.
        """
        try:
            definitions = self._read_schema().definitions
        except SchemaError:
            definitions = ()
        for definition in definitions:
            obj = definition.obj
            if (
                obj.kind == "table"
                and obj.folded_name == table
                and (obj.folded_schema or DEFAULT_SCHEMA).lower() == schema.lower()
                and definition.file is not None
            ):
                return str(definition.file), definition.line
        return str(self.config.schema_dir), 1

    def _resolver_of(self, table: Table) -> tuple[str, int] | None:
        """The file and line of the resolver that fills *table*, when the schema defines one."""
        for resolver in self._discovered():
            if resolver.name == f"fn_resolve_{table.name}" and resolver.file:
                return resolver.file, resolver.line
        return None


def validate_seeds(
    seeds: Path | str,
    *,
    schema_dir: Path | str,
    max_level: int = 3,
    database: str | Connection | None = None,
    prep_seed_schema: str = "prep_seed",
    catalog_schema: str = "catalog",
) -> PrepSeedReport:
    """Validate seeds written for the prep-seed pattern, levels 1 through *max_level*.

    The prep-seed pattern loads UUID-keyed rows into *prep_seed_schema* and
    resolves them into BIGINT-keyed rows in *catalog_schema*. Levels 1-3 read
    files and need no database; 4 and 5 load the seeds and run the resolvers
    against *database*, in a transaction nothing outlives: a URL's connection is
    opened, rolled back and closed here, and a caller's connection runs inside a
    savepoint rolled back on the way out. Nothing is printed: the report is the
    answer, and a file the run could not read is an error rather than a file that
    passed.

    Raises:
        SeedError: ``SEED_001`` for *seeds* that is not a directory, or a seed file
            that cannot be read as UTF-8 text.
        SchemaError: ``SCHEMA_201`` for a *schema_dir* that is not a directory when
            a level that reads it runs (2 and up), ``SCHEMA_001`` for a schema
            file that cannot be read as UTF-8 text.
        ConfigurationError: ``CONFIG_001`` for a *max_level* outside 1-5;
            ``CONFIG_013`` for a connection in autocommit at levels 4-5, which
            need a transaction to roll back.
        TypeError: a *database* that is neither a URL nor a :class:`Connection`.
        ValueError: *max_level* of 4 or 5 without a *database*.
    """
    seeds_dir, schema_dir = Path(seeds), Path(schema_dir)
    if database is not None and not isinstance(database, str | Connection):
        raise TypeError(
            "database must be a URL (str) or a connection meeting "
            f"confiture.platform.Connection, not {type(database).__name__}"
        )
    if database is None and max_level in range(FIRST_DATABASE_LEVEL, LEVELS.stop):
        msg = f"max_level {max_level} needs a database: levels 4-5 run against one"
        raise ValueError(msg)
    connection = None if database is None or isinstance(database, str) else database
    if connection is not None and max_level >= FIRST_DATABASE_LEVEL:
        require_mode(
            connection,
            autocommit=False,
            call="validate_seeds",
            reason="levels 4 and 5 roll what they load back to a savepoint",
        )
    config = OrchestrationConfig(
        max_level=max_level,
        seeds_dir=seeds_dir,
        schema_dir=schema_dir,
        database_url=database if isinstance(database, str) else None,
        connection=connection,
        show_progress=False,
        prep_seed_schema=prep_seed_schema,
        catalog_schema=catalog_schema,
    )
    return PrepSeedOrchestrator(config).run()
