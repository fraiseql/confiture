"""Three-phase pg_restore orchestrator.

Eliminates FK constraint race conditions during parallel restores by running
pre-data and post-data phases serially and only parallelising the data phase
(where no FK constraints exist yet).

Requires custom format (-Fc) or directory format (-Fd) dumps.
"""

from __future__ import annotations

import dataclasses
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from confiture.exceptions import RestoreError

_log = logging.getLogger(__name__)

_PGDUMP_MAGIC = b"PGDMP"


@dataclass
class RestoreOptions:
    """Options for a three-phase pg_restore run.

    Attributes:
        backup_path: Path to the pg_dump backup (custom or directory format).
        target_db: Name of the target database.
        host: PostgreSQL host or socket directory path.
        port: PostgreSQL port.
        username: PostgreSQL role to connect as. None uses the OS default.
        jobs: Number of parallel workers for the data phase.
        no_owner: Skip restoration of object ownership (--no-owner).
        no_acl: Skip restoration of access privileges (--no-acl).
        exit_on_error: Abort on first error (--exit-on-error). Recommended for
            production restores. Note: when ``parallel_restore=True`` this is
            automatically overridden to ``False``.
        superuser: If set, run pg_restore via ``sudo -u <superuser>``.
        min_tables: After restore, verify at least this many tables exist.
            0 skips the check.
        min_tables_schema: Schema to count tables in for --min-tables.
        parallel_restore: When ``True``, ``exit_on_error`` is automatically set
            to ``False`` so that transient FK violations during the parallel
            data phase do not abort the restore.  Use for all restores with
            ``jobs > 1``.
    """

    backup_path: Path
    target_db: str
    host: str = "/var/run/postgresql"
    port: int = 5432
    username: str | None = None
    jobs: int = 4
    no_owner: bool = False
    no_acl: bool = False
    exit_on_error: bool = True
    superuser: str | None = None
    min_tables: int = 0
    min_tables_schema: str = "public"
    parallel_restore: bool = False
    """When ``True``, ``exit_on_error`` is automatically overridden to ``False``
    for the restore run and a warning is logged.

    Use this for all restores with ``jobs > 1``.  During the data phase of a
    parallel restore, FK constraints do not yet exist, so any FK-related errors
    are transient and non-fatal.  Keeping ``exit_on_error=True`` with parallel
    workers causes these transient errors to abort the restore unnecessarily.

    Note: even with ``parallel_restore=True``, ``exit_on_error=False`` is set
    on :class:`RestoreOptions`; the original options object is **not** mutated.
    """


@dataclass
class RestoreResult:
    """Result from a restore run or an individual phase.

    Attributes:
        success: True if the phase/run completed without fatal errors.
        phases_completed: List of section names that succeeded.
        table_count: Number of tables found during post-restore validation.
            None if --min-tables was 0 or validation was not reached.
        errors: Lines from pg_restore stderr containing ``pg_restore: error:``.
        warnings: Lines from pg_restore stderr containing ``pg_restore: warning:``.
        diagnostics: Actionable hints emitted when known error patterns are
            detected.  Currently populated after the post-data phase when
            ``"out of shared memory"`` is found in errors or warnings.
    """

    success: bool
    phases_completed: list[str]
    table_count: int | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


class DatabaseRestorer:
    """Orchestrates a three-phase pg_restore to avoid FK constraint race conditions.

    Usage::

        from pathlib import Path
        from confiture.core.restorer import DatabaseRestorer, RestoreOptions

        opts = RestoreOptions(
            backup_path=Path("prod.pgdump"),
            target_db="staging",
            jobs=8,
            parallel_restore=True,  # recommended for jobs > 1
            min_tables=300,
        )
        result = DatabaseRestorer().restore(opts)
        if not result.success:
            for err in result.errors:
                print(err)
        for hint in result.diagnostics:
            print(hint)
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def restore(
        self,
        options: RestoreOptions,
        on_stderr_line: Callable[[str], None] | None = None,
    ) -> RestoreResult:
        """Run the three-phase restore.

        Phases:
            1. pre-data (serial) — DDL, sequences, types
            2. data (parallel)   — table rows; no FK constraints exist yet
            3. post-data (serial) — indexes, FK constraints

        Args:
            options: Restore configuration.
            on_stderr_line: Optional callback called for every stderr line from
                pg_restore, useful for streaming live progress to the terminal.

        Returns:
            :class:`RestoreResult` with aggregated phase outcomes.

        Raises:
            RestoreError: If the dump format is unsupported, pg_restore is not
                found, or the restore is interrupted.
        """
        self._validate_dump_format(options.backup_path)

        # parallel_restore=True implies exit_on_error=False; FK violations during
        # the data phase are transient and non-fatal when running parallel workers.
        if options.parallel_restore and options.exit_on_error:
            _log.warning(
                "parallel_restore=True: overriding exit_on_error to False. "
                "FK violations during the data phase are transient when using "
                "parallel workers and will not abort the restore."
            )
            options = dataclasses.replace(options, exit_on_error=False)

        all_warnings: list[str] = []
        phases_done: list[str] = []
        post_data_result: RestoreResult | None = None

        for section, parallel in [
            ("pre-data", False),
            ("data", True),
            ("post-data", False),
        ]:
            result = self._run_section(section, options, parallel, on_stderr_line)
            all_warnings.extend(result.warnings)
            if section == "post-data":
                post_data_result = result
            if not result.success:
                diagnostics = (
                    self._diagnose_post_data_errors(result.errors + result.warnings)
                    if section == "post-data"
                    else []
                )
                return RestoreResult(
                    success=False,
                    phases_completed=phases_done,
                    errors=result.errors,
                    warnings=all_warnings,
                    diagnostics=diagnostics,
                )
            phases_done.extend(result.phases_completed)

        # Collect diagnostics from post-data phase (success or not)
        post_data_lines = (
            (post_data_result.errors + post_data_result.warnings)
            if post_data_result is not None
            else []
        )
        diagnostics = self._diagnose_post_data_errors(post_data_lines)

        # Optional post-restore table count check
        if options.min_tables > 0:
            check = self._validate_table_count(options)
            return RestoreResult(
                success=check.success,
                phases_completed=phases_done,
                table_count=check.table_count,
                errors=check.errors,
                warnings=all_warnings,
                diagnostics=diagnostics,
            )

        return RestoreResult(
            success=True,
            phases_completed=phases_done,
            warnings=all_warnings,
            diagnostics=diagnostics,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_dump_format(self, backup_path: Path) -> None:
        """Raise RestoreError if the dump is not custom or directory format.

        The ``--section`` flag only works with custom (-Fc) and directory (-Fd)
        format dumps. Plain-text SQL dumps would silently apply everything on
        each pg_restore call, producing wrong results.

        Args:
            backup_path: Path to validate.

        Raises:
            RestoreError: If the format is plain-text, unrecognised, or the
                file cannot be read.
        """
        if backup_path.is_dir():
            toc = backup_path / "toc.dat"
            if not toc.exists():
                raise RestoreError(
                    f"{backup_path} is a directory but contains no toc.dat — "
                    "not a valid pg_dump directory-format archive"
                )
            header = toc.read_bytes()[:5]
        else:
            try:
                header = backup_path.read_bytes()[:5]
            except OSError as e:
                raise RestoreError(f"Cannot read backup file: {e}") from e

        if header == _PGDUMP_MAGIC:
            return  # custom or directory format — both use the PGDMP magic

        # Heuristic: plain-text dumps start with SQL comments or keywords
        try:
            text_prefix = backup_path.read_bytes()[:200].decode("utf-8", errors="replace")
            if text_prefix.lstrip().startswith(("--", "SET ", "SELECT ", "CREATE ")):
                raise RestoreError(
                    "Backup appears to be plain-text SQL format. "
                    "The three-phase restore requires custom format (-Fc) or "
                    "directory format (-Fd). Re-create the dump with:\n"
                    "  pg_dump -Fc dbname > dump.pgdump"
                )
        except OSError:
            pass

        raise RestoreError(
            f"Unrecognised dump format for {backup_path}. "
            "confiture restore requires custom format (-Fc) or directory format (-Fd)."
        )

    def _build_command(self, section: str, options: RestoreOptions, parallel: bool) -> list[str]:
        """Construct the pg_restore argument list for a single section.

        Args:
            section: One of ``"pre-data"``, ``"data"``, or ``"post-data"``.
            options: Restore configuration.
            parallel: Whether to enable parallel workers for this phase.

        Returns:
            Full argv list (including optional ``sudo -u`` prefix).
        """
        cmd: list[str] = []
        if options.superuser:
            cmd += ["sudo", "-u", options.superuser]
        cmd += [
            "pg_restore",
            "-h",
            options.host,
            "-p",
            str(options.port),
            "-d",
            options.target_db,
            f"--section={section}",
        ]
        if options.username:
            cmd += ["-U", options.username]
        if options.exit_on_error:
            cmd.append("--exit-on-error")
        if options.no_owner:
            cmd.append("--no-owner")
        if options.no_acl:
            cmd.append("--no-acl")
        if parallel and options.jobs > 1:
            cmd += ["-j", str(options.jobs)]
        cmd.append(str(options.backup_path))
        return cmd

    @staticmethod
    def _diagnose_post_data_errors(lines: list[str]) -> list[str]:
        """Return actionable hints for known post-data error patterns.

        Args:
            lines: Combined error and warning lines from the post-data phase.

        Returns:
            List of human-readable diagnostic strings (may be empty).
        """
        hints: list[str] = []
        if any("out of shared memory" in line for line in lines):
            hints.append(
                "Hint: 'out of shared memory' during the post-data phase indicates that "
                "max_locks_per_transaction is too low. For schemas with many partitions "
                "(2 000+), set max_locks_per_transaction = 256 (or higher) in "
                "postgresql.conf and reload PostgreSQL before retrying the restore."
            )
        return hints

    @staticmethod
    def _classify_stderr_line(line: str) -> str:
        """Classify a pg_restore stderr line.

        Args:
            line: A single line from pg_restore stderr (stripped of newline).

        Returns:
            ``"error"``, ``"warning"``, or ``"info"``.
        """
        if "pg_restore: error:" in line:
            return "error"
        if "pg_restore: warning:" in line:
            return "warning"
        return "info"

    def _run_section(
        self,
        section: str,
        options: RestoreOptions,
        parallel: bool,
        on_stderr_line: Callable[[str], None] | None = None,
    ) -> RestoreResult:
        """Run pg_restore for a single section with streaming stderr.

        Uses ``subprocess.Popen`` (not ``subprocess.run``) so that:

        - stderr is streamed line-by-line in real time
        - the pipe buffer cannot stall on verbose restores
        - Ctrl+C cleanly kills the subprocess

        Args:
            section: pg_restore ``--section`` value.
            options: Restore configuration.
            parallel: Enable ``-j`` workers.
            on_stderr_line: Optional callback for every stderr line.

        Returns:
            :class:`RestoreResult` for this section.

        Raises:
            RestoreError: If pg_restore is not found or the process is
                interrupted.
        """
        cmd = self._build_command(section, options, parallel)
        errors: list[str] = []
        warnings: list[str] = []

        try:
            with subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            ) as proc:
                try:
                    for line in proc.stderr:  # type: ignore[union-attr]
                        line = line.rstrip()
                        if on_stderr_line:
                            on_stderr_line(line)
                        kind = self._classify_stderr_line(line)
                        if kind == "error":
                            errors.append(line)
                        elif kind == "warning":
                            warnings.append(line)
                    returncode = proc.wait()
                except KeyboardInterrupt:
                    proc.kill()
                    raise RestoreError(f"pg_restore {section} phase interrupted by user") from None
        except FileNotFoundError as e:
            raise RestoreError(
                "pg_restore not found. Ensure PostgreSQL client tools are installed and on PATH."
            ) from e

        if returncode != 0 and (options.exit_on_error or errors):
            return RestoreResult(
                success=False,
                phases_completed=[],
                errors=errors or [f"pg_restore exited with code {returncode}"],
                warnings=warnings,
            )
        # Lenient mode (exit_on_error=False, no hard errors, non-zero exit): treat as success

        return RestoreResult(
            success=True, phases_completed=[section], errors=errors, warnings=warnings
        )

    def _validate_table_count(self, options: RestoreOptions) -> RestoreResult:
        """Count base tables in the target schema and compare against the minimum.

        Uses ``pg_catalog.pg_class`` (faster than ``information_schema.tables``
        on large schemas) with a parameterised schema name to avoid SQL injection.

        Args:
            options: Restore configuration (provides connection details and
                ``min_tables`` / ``min_tables_schema``).

        Returns:
            :class:`RestoreResult` with ``success=True`` if the count meets the
            minimum, ``success=False`` otherwise.

        Raises:
            RestoreError: If the database connection fails.
        """
        conninfo = f"host={options.host} port={options.port} dbname={options.target_db}" + (
            f" user={options.username}" if options.username else ""
        )
        try:
            with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
                cur.execute(
                    """
                        SELECT COUNT(*)
                        FROM pg_catalog.pg_class c
                        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                        WHERE c.relkind = 'r'
                          AND n.nspname = %s
                        """,
                    (options.min_tables_schema,),
                )
                row = cur.fetchone()
                count = row[0] if row else 0
        except psycopg.OperationalError as e:
            raise RestoreError(
                f"Cannot connect to {options.target_db} for table count validation: {e}"
            ) from e

        if count < options.min_tables:
            return RestoreResult(
                success=False,
                phases_completed=["pre-data", "data", "post-data"],
                table_count=count,
                errors=[
                    f"Post-restore validation failed: found {count} tables in schema "
                    f"'{options.min_tables_schema}', expected at least {options.min_tables}"
                ],
            )
        return RestoreResult(
            success=True,
            phases_completed=["pre-data", "data", "post-data"],
            table_count=count,
        )
