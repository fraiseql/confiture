"""Three-phase pg_restore orchestrator.

Eliminates FK constraint race conditions during parallel restores by running
pre-data and post-data phases serially and only parallelising the data phase
(where no FK constraints exist yet).

Requires custom format (-Fc) or directory format (-Fd) dumps.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from confiture.core.url_redaction import libpq_env
from confiture.exceptions import RestoreError

_log = logging.getLogger(__name__)

_PGDUMP_MAGIC = b"PGDMP"

# A `pg_restore -l` entry line: "<dumpId>; <catalogId> <oid> <desc> <schema> <name> <owner>".
# We only need the leading dump id and the description that follows the oid.
_TOC_LINE_RE = re.compile(r"^(?P<dump_id>\d+);\s+\d+\s+\d+\s+(?P<rest>.+)$")

# pg_restore object descriptions that contain spaces, longest first so that
# "MATERIALIZED VIEW DATA" is matched before the "MATERIALIZED VIEW" definition.
_MULTIWORD_DESCS = (
    "MATERIALIZED VIEW DATA",
    "MATERIALIZED VIEW",
    "TABLE DATA",
    "FK CONSTRAINT",
    "SEQUENCE OWNED BY",
    "SEQUENCE SET",
    "DEFAULT ACL",
    "PUBLICATION TABLE",
    "ROW SECURITY",
)

_MATVIEW_DATA_DESC = "MATERIALIZED VIEW DATA"


@dataclass(frozen=True)
class TocEntry:
    """A single entry from a ``pg_restore -l`` table-of-contents listing.

    Attributes:
        dump_id: The numeric dump id at the start of the line. This is the token
            ``pg_restore -L`` uses to select an entry.
        description: The object description, e.g. ``"TABLE DATA"`` or
            ``"MATERIALIZED VIEW DATA"``.
        raw_line: The original ``-l`` line, preserved verbatim so it can be
            written back into a ``-L`` use-list unchanged.
    """

    dump_id: int
    description: str
    raw_line: str

    @property
    def is_matview_data(self) -> bool:
        """True if this entry is a ``REFRESH MATERIALIZED VIEW`` (matview data)."""
        return self.description == _MATVIEW_DATA_DESC


@dataclass
class RestoreOptions:
    """Options for a three-phase pg_restore run.

    Attributes:
        backup_path: Path to the pg_dump backup (custom or directory format).
        target_db: Name of the target database.
        host: PostgreSQL host or socket directory path.
        port: PostgreSQL port.
        username: PostgreSQL role to connect as. None uses the OS default.
        password: Password for ``username``, required by any server that is not
            trust/peer-authenticated. Passed to the ``pg_restore`` / ``psql``
            children via ``PGPASSWORD``, never on argv (``ps aux`` is world-
            readable). None leaves the ambient environment untouched, so an
            operator-set ``PGPASSWORD`` or ``~/.pgpass`` still works.
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
    password: str | None = None
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
    no_refresh_matviews: bool = False
    """When ``True``, materialized-view refreshes are excluded from the restore
    entirely: their data is filtered out of every restore phase and the deferred
    ANALYZE + refresh step is skipped, leaving every matview ``WITH NO DATA`` for
    the caller to refresh on their own schedule.

    When ``False`` (default), a backup containing materialized views is restored
    with the refresh **deferred**: base tables load first, then a database-wide
    ``ANALYZE`` runs, then the matviews are refreshed serially — so every refresh
    replans on real statistics instead of the empty ``pg_statistic`` of a freshly
    loaded database.
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
        matviews_deferred: Number of materialized-view refreshes held out of the
            restore phases and deferred past ANALYZE. None when the backup
            contains no matviews (the phase structure is unchanged in that case).
        matviews_refreshed: Number of deferred matviews actually refreshed after
            ANALYZE. 0 when ``no_refresh_matviews`` left them empty; None when no
            matviews were present.
        analyze_ran: True if the post-load ANALYZE step ran (only when matviews
            were deferred and refresh was not suppressed).
    """

    success: bool
    phases_completed: list[str]
    table_count: int | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    matviews_deferred: int | None = None
    matviews_refreshed: int | None = None
    analyze_ran: bool = False


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
        """Run the three-phase restore, deferring matview refreshes past ANALYZE.

        Phases:
            1. pre-data (serial) — DDL, sequences, types
            2. data (parallel)   — table rows; no FK constraints exist yet
            3. post-data (serial) — indexes, FK constraints

        When the archive contains materialized-view data, the ``REFRESH`` is
        deferred out of the parallel data phase (which otherwise refreshes on the
        empty statistics of a freshly loaded database, risking catastrophic query
        plans) and run after two extra serial steps:

            4. analyze (serial)  — database-wide ANALYZE so stats exist
            5. refresh-matviews (serial) — REFRESH MATERIALIZED VIEW on real stats

        Backups without matviews take the classic three-phase path unchanged.
        ``options.no_refresh_matviews`` keeps matviews out of the data phase and
        skips steps 4–5, leaving them ``WITH NO DATA``.

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

        non_matview, matview_data = self._partition_entries(self._list_toc(options))
        defer = bool(matview_data)

        all_warnings: list[str] = []
        phases_done: list[str] = []
        post_data_result: RestoreResult | None = None
        analyze_ran = False
        matviews_refreshed = 0

        with contextlib.ExitStack() as stack:
            tables_list, matviews_list = self._prepare_use_lists(stack, non_matview, matview_data)

            # Steps 1-3: classic pre-data → data → post-data. When deferring,
            # ``tables_list`` excludes the matview-data (REFRESH) items from every
            # phase — pg_dump files them under data or post-data depending on its
            # version, so a whole-restore ``-L`` filter is the version-robust way
            # to keep the refresh out until stats exist. ``tables_list`` is None on
            # the no-matview fast path, leaving the argv byte-for-byte unchanged.
            for section, parallel in [
                ("pre-data", False),
                ("data", True),
                ("post-data", False),
            ]:
                result = self._run_section(
                    section, options, parallel, on_stderr_line, use_list=tables_list
                )
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
                        matviews_deferred=len(matview_data) if defer else None,
                    )
                phases_done.extend(result.phases_completed)

            # Steps 4-5: ANALYZE, then refresh the deferred matviews on real stats.
            # The refresh runs with no ``--section`` so it restores exactly the
            # matview-data items regardless of which section pg_dump assigned them.
            if defer and not options.no_refresh_matviews:
                analyze = self._run_analyze(options, on_stderr_line)
                all_warnings.extend(analyze.warnings)
                if not analyze.success:
                    return RestoreResult(
                        success=False,
                        phases_completed=phases_done,
                        errors=analyze.errors,
                        warnings=all_warnings,
                        matviews_deferred=len(matview_data),
                    )
                analyze_ran = True
                phases_done.extend(analyze.phases_completed)

                refresh = self._run_section(
                    None, options, False, on_stderr_line, use_list=matviews_list
                )
                all_warnings.extend(refresh.warnings)
                if not refresh.success:
                    return RestoreResult(
                        success=False,
                        phases_completed=phases_done,
                        errors=refresh.errors,
                        warnings=all_warnings,
                        matviews_deferred=len(matview_data),
                        analyze_ran=analyze_ran,
                    )
                phases_done.append("refresh-matviews")
                matviews_refreshed = len(matview_data)

        # Collect diagnostics from post-data phase (success or not)
        post_data_lines = (
            (post_data_result.errors + post_data_result.warnings)
            if post_data_result is not None
            else []
        )
        diagnostics = self._diagnose_post_data_errors(post_data_lines)

        deferred_count = len(matview_data) if defer else None
        refreshed_count = matviews_refreshed if defer else None

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
                matviews_deferred=deferred_count,
                matviews_refreshed=refreshed_count,
                analyze_ran=analyze_ran,
            )

        return RestoreResult(
            success=True,
            phases_completed=phases_done,
            warnings=all_warnings,
            diagnostics=diagnostics,
            matviews_deferred=deferred_count,
            matviews_refreshed=refreshed_count,
            analyze_ran=analyze_ran,
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

    def _list_toc(self, options: RestoreOptions) -> list[TocEntry]:
        """List the archive's table of contents via ``pg_restore -l``.

        ``pg_restore -l`` reads the archive only (no database connection), so it
        needs neither host/port nor a target database — but it honours the same
        ``sudo -u superuser`` prefix in case the archive is only readable by that
        user.

        Args:
            options: Restore configuration (for the backup path and superuser).

        Returns:
            Parsed TOC entries, or ``[]`` if the archive lists no elements.

        Raises:
            RestoreError: If pg_restore is not found or the listing fails.
        """
        cmd: list[str] = []
        if options.superuser:
            cmd += ["sudo", "-u", options.superuser]
        cmd += ["pg_restore", "-l", str(options.backup_path)]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError as e:
            raise RestoreError(
                "pg_restore not found. Ensure PostgreSQL client tools are installed and on PATH."
            ) from e

        if proc.returncode != 0:
            raise RestoreError(
                f"pg_restore -l failed for {options.backup_path}: {proc.stderr.strip()}"
            )
        return self._parse_toc_lines(proc.stdout.splitlines())

    def _prepare_use_lists(
        self,
        stack: contextlib.ExitStack,
        non_matview: list[TocEntry],
        matview_data: list[TocEntry],
    ) -> tuple[Path | None, Path | None]:
        """Materialize the ``-L`` use-lists for a deferred-matview restore.

        Returns ``(None, None)`` when there is no matview data (the classic
        three-phase path, argv unchanged). Otherwise writes ``tables.list`` (data
        phase, matview refreshes excluded) and ``matviews.list`` (refresh phase)
        into a temporary directory registered on ``stack`` for cleanup.

        Args:
            stack: ExitStack owning the temp directory's lifetime.
            non_matview: Every non-matview-data TOC entry.
            matview_data: The matview-data (REFRESH) TOC entries.

        Returns:
            ``(tables_list, matviews_list)`` paths, or ``(None, None)``.
        """
        if not matview_data:
            return None, None
        base = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="confiture-restore-")))
        tables_list = base / "tables.list"
        matviews_list = base / "matviews.list"
        self._write_use_list(non_matview, tables_list)
        self._write_use_list(matview_data, matviews_list)
        return tables_list, matviews_list

    @staticmethod
    def _partition_entries(
        entries: list[TocEntry],
    ) -> tuple[list[TocEntry], list[TocEntry]]:
        """Split TOC entries into (everything-else, matview-data).

        The first list drives the parallel data phase (table data, minus matview
        refreshes); the second drives the deferred serial refresh phase.

        Args:
            entries: Parsed TOC entries.

        Returns:
            A ``(non_matview, matview_data)`` tuple.
        """
        matview_data = [e for e in entries if e.is_matview_data]
        non_matview = [e for e in entries if not e.is_matview_data]
        return non_matview, matview_data

    @staticmethod
    def _write_use_list(entries: list[TocEntry], path: Path) -> None:
        """Write a ``pg_restore -L`` use-list of the given entries' raw lines.

        Args:
            entries: Entries to include (their verbatim ``-l`` lines are written).
            path: Destination file path.
        """
        path.write_text("\n".join(e.raw_line for e in entries) + "\n")

    def _build_command(
        self,
        section: str | None,
        options: RestoreOptions,
        parallel: bool,
        use_list: Path | None = None,
    ) -> list[str]:
        """Construct the pg_restore argument list for a single section.

        Args:
            section: One of ``"pre-data"``, ``"data"``, or ``"post-data"``, or
                ``None`` to omit ``--section`` entirely (used for the deferred
                matview refresh, whose TOC items may be data or post-data
                depending on the pg_dump version — a ``-L`` list plus no section
                filter restores exactly the listed items in either case).
            options: Restore configuration.
            parallel: Whether to enable parallel workers for this phase.
            use_list: Optional ``pg_restore -L`` use-list restricting the restore
                to the listed archive elements (used to defer matview refreshes).

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
        ]
        if section is not None:
            cmd.append(f"--section={section}")
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
        if use_list is not None:
            cmd += ["-L", str(use_list)]
        cmd.append(str(options.backup_path))
        return cmd

    def _build_analyze_command(self, options: RestoreOptions) -> list[str]:
        """Construct the ``psql`` argument list for the post-load ANALYZE.

        ANALYZE is run through ``psql`` (not psycopg) so it reuses the exact
        ``sudo -u superuser`` and connection flags as pg_restore — a whole-DB
        ANALYZE by a role that does not own the tables silently skips them, which
        would leave the deferred matview refresh running on empty statistics.

        Args:
            options: Restore configuration.

        Returns:
            Full argv list (including optional ``sudo -u`` prefix).
        """
        cmd: list[str] = []
        if options.superuser:
            cmd += ["sudo", "-u", options.superuser]
        cmd += [
            "psql",
            "-h",
            options.host,
            "-p",
            str(options.port),
            "-d",
            options.target_db,
        ]
        if options.username:
            cmd += ["-U", options.username]
        cmd += ["-v", "ON_ERROR_STOP=1", "-c", "ANALYZE"]
        return cmd

    def _run_analyze(
        self,
        options: RestoreOptions,
        on_stderr_line: Callable[[str], None] | None = None,
    ) -> RestoreResult:
        """Run a database-wide ANALYZE so deferred matview refreshes see stats.

        Args:
            options: Restore configuration.
            on_stderr_line: Optional callback for every psql stderr line.

        Returns:
            :class:`RestoreResult` with ``phases_completed=["analyze"]`` on
            success, or ``success=False`` with the captured error lines.

        Raises:
            RestoreError: If psql is not found or the process is interrupted.
        """
        cmd = self._build_analyze_command(options)
        errors: list[str] = []

        try:
            with subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                env=libpq_env(options.password),
            ) as proc:
                try:
                    assert proc.stderr is not None
                    for raw in proc.stderr:
                        line = raw.rstrip()
                        if on_stderr_line:
                            on_stderr_line(line)
                        if "ERROR:" in line or "psql: error" in line:
                            errors.append(line)
                    returncode = proc.wait()
                except KeyboardInterrupt:
                    proc.kill()
                    raise RestoreError("ANALYZE phase interrupted by user") from None
        except FileNotFoundError as e:
            raise RestoreError(
                "psql not found. Ensure PostgreSQL client tools are installed and on PATH."
            ) from e

        if returncode != 0:
            return RestoreResult(
                success=False,
                phases_completed=[],
                errors=errors or [f"psql ANALYZE exited with code {returncode}"],
            )
        return RestoreResult(success=True, phases_completed=["analyze"])

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
    def _parse_toc_lines(lines: list[str]) -> list[TocEntry]:
        """Parse ``pg_restore -l`` output into structured TOC entries.

        Comment lines (starting with ``;``) and blank lines are skipped. Each
        remaining line is parsed for its dump id and object description; the
        original line is preserved for round-tripping into a ``-L`` use-list.

        Args:
            lines: Lines from ``pg_restore -l`` (already split, newline-stripped
                or not — trailing whitespace is ignored).

        Returns:
            One :class:`TocEntry` per archive element, in listing order.
        """
        entries: list[TocEntry] = []
        for raw in lines:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                continue
            match = _TOC_LINE_RE.match(stripped)
            if match is None:
                continue
            rest = match.group("rest")
            description = next(
                (desc for desc in _MULTIWORD_DESCS if rest.startswith(desc + " ")),
                rest.split(" ", 1)[0],
            )
            entries.append(
                TocEntry(
                    dump_id=int(match.group("dump_id")),
                    description=description,
                    raw_line=stripped,
                )
            )
        return entries

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
        section: str | None,
        options: RestoreOptions,
        parallel: bool,
        on_stderr_line: Callable[[str], None] | None = None,
        use_list: Path | None = None,
    ) -> RestoreResult:
        """Run pg_restore for a single section with streaming stderr.

        Uses ``subprocess.Popen`` (not ``subprocess.run``) so that:

        - stderr is streamed line-by-line in real time
        - the pipe buffer cannot stall on verbose restores
        - Ctrl+C cleanly kills the subprocess

        Args:
            section: pg_restore ``--section`` value, or ``None`` to omit it (the
                deferred matview refresh drives the section via its ``-L`` list).
            options: Restore configuration.
            parallel: Enable ``-j`` workers.
            on_stderr_line: Optional callback for every stderr line.
            use_list: Optional ``pg_restore -L`` use-list restricting the restore
                to the listed archive elements.

        Returns:
            :class:`RestoreResult` for this section (``phases_completed`` carries
            the section name, or is empty when ``section`` is ``None``).

        Raises:
            RestoreError: If pg_restore is not found or the process is
                interrupted.
        """
        cmd = self._build_command(section, options, parallel, use_list=use_list)
        errors: list[str] = []
        warnings: list[str] = []

        try:
            with subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                env=libpq_env(options.password),
            ) as proc:
                try:
                    assert proc.stderr is not None
                    for line in proc.stderr:
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
                    phase = section or "matview-refresh"
                    raise RestoreError(f"pg_restore {phase} phase interrupted by user") from None
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
            success=True,
            phases_completed=[section] if section is not None else [],
            errors=errors,
            warnings=warnings,
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
        try:
            with (
                psycopg.connect(
                    host=options.host,
                    port=options.port,
                    dbname=options.target_db,
                    user=options.username or None,
                    password=options.password,
                ) as conn,
                conn.cursor() as cur,
            ):
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
