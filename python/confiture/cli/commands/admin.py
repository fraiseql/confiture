"""Admin commands: install_helpers, validate_profile, verify-checksums, restore,
validate-config."""

from importlib import resources
from pathlib import Path
from typing import Any

import typer
from rich.markup import escape

from confiture.cli.dsn import DATABASE_URL_OPTION_HELP, resolve_database_url
from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import (
    _get_tracking_table,
    console,
    emit,
    error_console,
    is_json,
    open_connection,
)
from confiture.cli.markup import verbatim
from confiture.cli.options import (
    config_option,
    database_url_option,
    env_option,
    format_option,
    migrations_dir_option,
)
from confiture.config.environment import Environment
from confiture.core import checksum as _core_checksum
from confiture.core import connection as _core_connection
from confiture.core import ledger as _core_ledger
from confiture.core.checksum import ChecksumConfig, ChecksumMismatchBehavior
from confiture.core.error_handler import handle_cli_error
from confiture.core.ledger import notable_resolution
from confiture.core.restorer import DatabaseRestorer, RestoreOptions
from confiture.core.validation.config_validator import ConfigValidator
from confiture.core.view_manager import ViewManager
from confiture.error_codes import FINDINGS
from confiture.exceptions import (
    ConfigurationError,
    ConfiturError,
    DatabaseNotInitializedError,
    RestoreError,
)

#: Shared by `verify-checksums` and `migrate verify` — both hit the same state
#: (a database built from schema files rather than migrated) and both offer the
#: same three ways forward.
_NO_LEDGER_HINT = (
    "This database has no recorded migrations — it was likely built from schema "
    "files rather than migrated. Run `confiture migrate up` to apply migrations, "
    "`confiture migrate baseline --through <version>` if the schema is already "
    "present, or pass --allow-uninitialized to treat 'no ledger' as success."
)

ALLOW_UNINITIALIZED_HELP = (
    "Treat a database with no migration ledger as success (exit 0) instead of "
    "exit 2.  For gates that legitimately run against schema-built databases."
)


def _checksum_payload(
    *,
    ledger_present: bool,
    checked: int,
    mismatches: list,
    tracking_table: str,
    resolved_table: str | None = None,
    fixed: int | None = None,
) -> dict:
    """Build ``verify-checksums --format json`` output (#189).

    One builder for every exit path — clean, mismatched, and ledger-less — so
    text and JSON cannot describe different outcomes. Reuses the shared issue
    object (``issue-object.schema.json``) rather than inventing a mismatch
    shape, matching the house envelope `migrate verify` established.

    ``tracking_table`` is what the operator configured; ``resolved_table`` is
    what that name resolved to for this session (#188). They differ whenever a
    bare name is involved, so both are always emitted rather than one
    conditionally — a consumer should not have to guess which it is holding.

    ``ok`` and the exit code answer different questions, and neither may be
    computed as though it answered the other (#311):

    * the **exit code** answers "should this gate trip?" — and
      ``--allow-uninitialized`` is the operator declaring, in advance, that a
      ledger-less database must not trip it (the fraisier adapter branches on
      that integer; see ``docs/reference/fraisier-adapter-contract.md``);
    * **``ok``** answers "did verification succeed?" — and it did not, because
      it did not happen.

    So an absent ledger is ``ok: false`` at exit ``0``. Computed as
    ``not mismatches`` it would be ``true``: no ledger yields no mismatches, and
    the published schema tells consumers to read ``ok`` and nothing else, so a
    run that compared zero files would report green to a conforming consumer.

    ``was_skipped`` is always present, never absent-on-success: a key that
    appears on one path only makes every consumer branch before it can read it.
    """
    payload: dict = {
        "ok": ledger_present and not mismatches,
        "was_skipped": not ledger_present,
        "ledger_present": ledger_present,
        "summary": {
            "checked": checked,
            "mismatched": len(mismatches),
            "tracking_table": tracking_table,
            "resolved_table": resolved_table,
        },
        "issues": [
            {
                "severity": "error",
                "code": "CHECKSUM_MISMATCH",
                "message": (
                    f"{m.version}_{m.name} no longer matches the checksum stored "
                    "when it was applied"
                ),
                "actionable": (
                    "Restore the file to its applied content, or re-record the "
                    "current content with `confiture verify-checksums --fix` "
                    "(dangerous — it accepts whatever is on disk now)."
                ),
                "details": {
                    "expected": m.expected,
                    "actual": m.actual,
                },
                "migration": m.version,
                "file": str(m.file_path) if m.file_path else None,
                "line": None,
            }
            for m in mismatches
        ],
    }
    if fixed is not None:
        payload["fixed"] = fixed
    return payload


_VIEW_HELPERS = (
    "confiture.save_and_drop_dependent_views(schemas TEXT[])",
    "confiture.recreate_saved_views()",
)


def _install_view_helpers(conn: Any, *, dry_run: bool, force: bool) -> dict[str, Any]:
    """Install the view helpers on *conn* (or not), and say which of three things happened."""
    payload: dict[str, Any] = {"schema": "confiture", "functions": list(_VIEW_HELPERS)}
    if dry_run:
        sql = resources.files("confiture.sql").joinpath("view_helpers.sql").read_text()
        return {"status": "dry_run", **payload, "sql": sql}
    vm = ViewManager(conn)
    if not force and vm.helpers_installed():
        return {"status": "already_installed", **payload}
    vm.install_helpers()
    return {"status": "installed", **payload}


def _print_install_outcome(outcome: dict[str, Any]) -> None:
    if outcome["status"] == "dry_run":
        console.print("[bold]SQL that would be executed:[/bold]\n")
        console.print(outcome["sql"])
    elif outcome["status"] == "already_installed":
        console.print("[green]✓[/green] View helpers already installed — nothing to do")
        console.print("  Use [bold]--force[/bold] to reinstall")
    else:
        console.print("[green]✓[/green] Installed confiture view helper functions")
        console.print("  Schema: [bold]confiture[/bold]")
        console.print("  Functions:")
        for function in outcome["functions"]:
            console.print(f"    • {verbatim(function)}")


@cli_boundary
def install_helpers(
    config: Path = config_option(None),
    env: str = env_option(),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show SQL without executing",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Reinstall even if already installed",
    ),
    format_output: str = format_option("text", "json"),
) -> None:
    """Install confiture SQL helper functions in the target database.

    Creates the `confiture` schema with `save_and_drop_dependent_views()`
    and `recreate_saved_views()` PL/pgSQL functions for use in migrations
    that need to ALTER COLUMN TYPE on tables with dependent views.

    NOTE: if the role you connect as is *itself* named `confiture`, PostgreSQL's
    default `search_path` (`"$user", public`) puts this new schema ahead of
    public for that role — so unqualified CREATE statements start landing in it.
    Schema-qualify your DDL, or pin `search_path` on that role.
    """
    json_mode = is_json(format_output)
    try:
        if config:
            cfg = _core_connection.load_config(config)
        else:
            environment = Environment.load(env)
            cfg = {"database": {"url": environment.database_url}}

        with open_connection(cfg) as conn:
            outcome = _install_view_helpers(conn, dry_run=dry_run, force=force)
    # Reason: legacy text command: any failure maps to its exit code; the boundary has already printed it
    except Exception as e:
        if json_mode:
            fail(e, json_mode=True)
        raise typer.Exit(handle_cli_error(e)) from e

    if json_mode:
        emit(outcome)
    else:
        _print_install_outcome(outcome)


def _profile_summary(path: Path, profile: Any) -> dict[str, Any]:
    """What ``validate-profile --format json`` reports: the profile's shape, never a seed.

    A seed is the key to an anonymization's pseudonyms, so the payload says
    whether one is set and not what it is; a strategy's ``seed_env_var`` names a
    variable, not its value.
    """
    return {
        "valid": True,
        "path": str(path),
        "name": profile.name,
        "version": profile.version,
        "has_global_seed": profile.global_seed is not None,
        "strategies": {
            name: {"type": strategy.type, "seed_env_var": strategy.seed_env_var}
            for name, strategy in profile.strategies.items()
        },
        "tables": {
            name: [
                {
                    "column": rule.column,
                    "strategy": rule.strategy,
                    "has_seed": rule.seed is not None,
                }
                for rule in table.rules
            ]
            for name, table in profile.tables.items()
        },
    }


def _print_profile(profile: Any) -> None:
    """The profile in text mode; every value from the file is escaped, never markup."""
    console.print("[green]✅ Valid profile![/green]")
    console.print(f"   Name: {escape(str(profile.name))}")
    console.print(f"   Version: {escape(str(profile.version))}")
    if profile.global_seed:
        console.print(f"   Global Seed: {verbatim(profile.global_seed)}")

    console.print(f"\n[cyan]Strategies ({len(profile.strategies)})[/cyan]:")
    for strategy_name, strategy_def in profile.strategies.items():
        line = f"   • {strategy_name}: {strategy_def.type}"
        if strategy_def.seed_env_var:
            line += f" [env: {strategy_def.seed_env_var}]"
        console.print(escape(line))

    console.print(f"\n[cyan]Tables ({len(profile.tables)})[/cyan]:")
    for table_name, table_def in profile.tables.items():
        console.print(escape(f"   • {table_name}: {len(table_def.rules)} rules"))
        for rule in table_def.rules:
            line = f"      - {rule.column} → {rule.strategy}"
            if rule.seed:
                line += f" [seed: {rule.seed}]"
            console.print(escape(line))

    console.print("[green]\n✅ Profile validation passed![/green]")


@cli_boundary
def validate_profile(
    path: Path = typer.Argument(
        ...,
        help="Path to anonymization profile YAML file",
    ),
    format_output: str = format_option("text", "json"),
) -> None:
    """Validate anonymization profile YAML structure and schema.

    Performs security validation:
    - Uses safe_load() to prevent YAML injection
    - Validates against Pydantic schema
    - Checks strategy types are whitelisted
    - Verifies all required fields present

    Example:
        confiture validate-profile db/profiles/production.yaml
    """
    json_mode = is_json(format_output)
    try:
        # Reason: CLI start-up: importing confiture.core.anonymization.profile costs ~14 ms at start (importtime, 2026-09-07); deferred until the command runs
        from confiture.core.anonymization.profile import AnonymizationProfile

        if not json_mode:
            console.print(f"[cyan]📋 Validating profile: {escape(str(path))}[/cyan]")
        profile = AnonymizationProfile.load(path)
    except IsADirectoryError:
        fail(
            ConfigurationError(
                f"Profile path is a directory, not a file: {path}",
                error_code="CONFIG_004",
                resolution_hint="Name the anonymization profile YAML itself.",
            ),
            json_mode=json_mode,
        )
    except FileNotFoundError as e:
        # The loader's message names the path already; prefixing it said it twice.
        fail(
            ConfigurationError(
                str(e),
                error_code="CONFIG_004",
                resolution_hint="Check the path to the anonymization profile YAML.",
            ),
            json_mode=json_mode,
        )
    except ValueError as e:
        fail(ConfiturError(str(e), error_code="ANON_1400"), json_mode=json_mode)
    if json_mode:
        emit(_profile_summary(path, profile))
    else:
        _print_profile(profile)


def _report_absent_ledger(
    conn: object,
    tracking_table: str,
    *,
    allow_uninitialized: bool,
    json_mode: bool,
) -> None:
    """Emit (or raise) the no-ledger outcome. Returns only when it is survivable.

    Split out of ``verify_checksums`` because it is the branch with the most
    going on — four outcomes across two output modes — and none of it is about
    checksums.

    Raises:
        DatabaseNotInitializedError: unless ``--allow-uninitialized`` was given.
    """
    # A bare name is resolved through search_path, so "absent" can mean
    # "present, but not where this session looks". Saying which is the
    # difference between an actionable message and a puzzle (#188).
    elsewhere = _core_ledger.find_ledger_relations(conn, tracking_table)
    note = (
        f" A relation of that name does exist in {', '.join(elsewhere)}, but this "
        "connection's search_path does not reach it."
        if elsewhere
        else ""
    )

    if not allow_uninitialized:
        raise DatabaseNotInitializedError(
            f"No migration ledger found: `{tracking_table}` is not present in this database.{note}",
            resolution_hint=_NO_LEDGER_HINT,
        )

    if json_mode:
        # The payload, not a Rich print: this is the path most likely to be
        # scripted, and --format json must produce JSON on it too.
        emit(
            _checksum_payload(
                ledger_present=False,
                checked=0,
                mismatches=[],
                tracking_table=tracking_table,
                resolved_table=None,
            ),
            None,
            console,
        )
        return

    console.print(
        f"[yellow]⏭️  Skipped: no migration ledger found (`{verbatim(tracking_table)}` is "
        f"not present in this database){verbatim(note)} — 0 migrations recorded, so "
        "nothing was verified.[/yellow]"
    )
    console.print(
        "[dim]   Exit 0 comes from --allow-uninitialized, not from a comparison. "
        "Point this at a database that has a ledger to actually check file "
        "integrity.[/dim]"
    )


def _print_mismatches(mismatches: list, *, fixed: int | None) -> None:
    """Render the mismatch report in text mode.

    ``fixed`` is ``None`` when ``--fix`` was not passed, and otherwise the
    number of rows re-stamped — which equals ``len(mismatches)``, because
    ``--fix`` re-stamps what this run reported and nothing else (#311).
    """
    console.print(f"[red]❌ Found {len(mismatches)} checksum mismatch(es):[/red]\n")
    for m in mismatches:
        console.print(f"  [yellow]{verbatim(m.version)}_{verbatim(m.name)}[/yellow]")
        console.print(f"    File: {verbatim(m.file_path)}")
        expected_preview = m.expected[:16] if m.expected else "(none)"
        console.print(f"    Expected: {verbatim(expected_preview)}...")
        console.print(f"    Actual:   {verbatim(m.actual[:16])}...")
        console.print()
    if fixed is None:
        console.print("[yellow]💡 Tip: Use --fix to update stored checksums (dangerous)[/yellow]")
        return
    console.print("[yellow]⚠️  Updating stored checksums...[/yellow]")
    console.print(f"[green]✅ Updated {verbatim(fixed)} checksum(s)[/green]")


@cli_boundary
def verify_checksums(
    migrations_dir: Path = migrations_dir_option(),
    config: Path = config_option(),
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Update stored checksums to match current files (dangerous)",
    ),
    allow_uninitialized: bool = typer.Option(
        False,
        "--allow-uninitialized",
        help=ALLOW_UNINITIALIZED_HELP,
    ),
    output_format: str = format_option("text", "json"),
) -> None:
    """Verify migration file integrity against stored checksums.

    Compares SHA-256 checksums of migration files against the checksums
    stored when migrations were applied. Detects if files have been
    modified after application (file-tampering / schema-drift detection).

    For *runtime correctness* (did the migrations produce the expected
    schema/data state, via .verify.sql sidecars?) use `confiture migrate verify`
    instead — this command checks file integrity, not runtime state.

    This helps prevent:
    - Silent schema drift between environments
    - Production/staging mismatches
    - Debugging nightmares from modified migrations

    Examples:
        # Verify all migrations
        confiture verify-checksums

        # Verify with specific config
        confiture verify-checksums --config db/environments/production.yaml

        # Fix checksums (update stored to match current files)
        confiture verify-checksums --fix

        # Structured output for a CI gate
        confiture verify-checksums --format json

    JSON output: {ok, was_skipped, ledger_present,
    summary{checked,mismatched,tracking_table}, issues[]} — see
    docs/reference/json-schemas/verify-checksums.schema.json.
    Exit 1 on mismatches is a success-signal (the gate tripped), so it still
    carries this shape; a real error emits the error envelope instead.

    `ok` is true only when a comparison actually happened and found nothing.
    A ledger-less run under --allow-uninitialized exits 0 but reports
    `ok: false` with `was_skipped: true` — the exit code answers "should this
    gate trip", `ok` answers "did verification succeed" (#311).
    """

    json_mode = is_json(output_format)

    config_data = _core_connection.load_config(config)
    with open_connection(config_data) as conn:
        tracking_table = _get_tracking_table(config_data)
        ledger = _core_ledger.probe_ledger(conn, tracking_table)
        if not ledger.exists:
            _report_absent_ledger(
                conn,
                tracking_table,
                allow_uninitialized=allow_uninitialized,
                json_mode=json_mode,
            )
            return

        # Run verification (warn mode - we'll handle display)
        verifier = _core_checksum.MigrationChecksumVerifier(
            conn,
            ChecksumConfig(
                enabled=True,
                on_mismatch=ChecksumMismatchBehavior.WARN,
            ),
            migration_table=tracking_table,
        )
        mismatches = verifier.verify_all(migrations_dir)
        checked = verifier.count_applied()

        if not mismatches:
            if json_mode:
                emit(
                    _checksum_payload(
                        ledger_present=True,
                        checked=checked,
                        mismatches=[],
                        tracking_table=tracking_table,
                        resolved_table=ledger.resolved_name,
                    ),
                    None,
                    console,
                )
            else:
                _read = notable_resolution(tracking_table, ledger.resolved_name)
                _suffix = f" (read `{_read}`)" if _read else ""
                console.print(
                    f"[green]✅ All migration checksums verified!{verbatim(_suffix)}[/green]"
                )
            return

        updated: int | None = None
        if fix:
            # Scoped to what was just reported, and atomic (#311). Not
            # `update_all_checksums`, which re-stamps every recorded row one
            # transaction at a time: `--fix` for one bad checksum would rewrite
            # them all, right after a report that said "Found 1".
            updated = verifier.update_checksums_for(mismatches)

        if json_mode:
            emit(
                _checksum_payload(
                    ledger_present=True,
                    checked=checked,
                    mismatches=mismatches,
                    tracking_table=tracking_table,
                    resolved_table=ledger.resolved_name,
                    fixed=updated,
                ),
                None,
                console,
            )
        else:
            _print_mismatches(mismatches, fixed=updated)

    if not fix:
        # success-signal: verification ran and found mismatches (the CI gate
        # this command exists to trip) — not a confiture-domain error.
        raise typer.Exit(FINDINGS)


@cli_boundary
def validate_config(
    config: Path = config_option(
        None, help="Configuration file to validate (default: db/environments/local.yaml)"
    ),
    database_url: str = database_url_option(help=DATABASE_URL_OPTION_HELP),
    migrations_path: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-path",
        help="Migrations directory to validate (default: db/migrations)",
    ),
    output_format: str = format_option("text", "json"),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Treat warnings as errors for exit purposes.",
    ),
) -> None:
    """Validate configuration and the migrations tree — without connecting (#144).

    Checks YAML/schema validity, include-dir existence, DSN *format*, and the
    migrations tree (well-formed filenames, no duplicate versions). It never
    opens a database connection — for DB-level checks use `migrate preflight
    --against`.

    Accepts the same connection sources as the migrate family
    (`--config` / `--database-url` / `CONFITURE_DATABASE_URL` / `DATABASE_URL`).

    EXIT CODES:
      0 — config valid (warnings alone are non-fatal unless --strict)
      5 — config invalid (or, under --strict, warnings present)

    JSON output: {valid, config_source, migrations_path, migration_count, issues[]}.
    """

    # Source selection: an explicit --config validates that YAML; a
    # --database-url flag is validated for *format* as an issue (not raised);
    # otherwise an env-var DSN, else the default config path. We avoid routing
    # the flag through resolve_database_url() here so a malformed DSN surfaces
    # as a CONFIG_003 issue rather than raising before validation.
    if config is not None:
        validator = ConfigValidator.from_config(config, migrations_path=migrations_path)
    elif database_url:
        validator = ConfigValidator.from_flags(
            database_url=database_url, migrations_path=migrations_path
        )
    elif (env_url := resolve_database_url(None, None)) is not None:
        validator = ConfigValidator.from_env(database_url=env_url, migrations_path=migrations_path)
    else:
        validator = ConfigValidator.from_config(
            Path("db/environments/local.yaml"), migrations_path=migrations_path
        )

    report = validator.validate()
    has_error = any(i.severity in ("error", "critical") for i in report.issues)
    has_warning = any(i.severity == "warning" for i in report.issues)
    exit_code = 5 if has_error or (strict and has_warning) else 0

    if is_json(output_format):
        emit(report.to_dict(), None, console)
        if exit_code:
            raise typer.Exit(exit_code)
        return

    if report.valid and not report.issues:
        console.print(
            f"[green]✅ Configuration valid[/green] "
            f"({verbatim(report.config_source)}, {verbatim(report.migration_count)} migration(s))"
        )
        if exit_code:
            raise typer.Exit(exit_code)
        return

    error_console.print(f"[red]❌ Configuration issues ({verbatim(report.config_source)}):[/red]")
    for issue in report.issues:
        color = "red" if issue.severity in ("error", "critical") else "yellow"
        error_console.print(
            f"  [{color}]{verbatim(issue.severity.upper())}[/{color}] {verbatim(issue.code)}: {verbatim(issue.message)}"
        )
        if issue.actionable:
            error_console.print(f"    [dim]💡 {verbatim(issue.actionable)}[/dim]")
    if exit_code:
        raise typer.Exit(exit_code)


@cli_boundary
def restore(
    backup_file: Path = typer.Argument(
        ...,
        help="Path to pg_dump backup file. Must be custom (-Fc) or directory (-Fd) format.",
    ),
    database: str = typer.Option(
        ...,
        "--database",
        "-d",
        help="Target database name",
    ),
    host: str = typer.Option(
        "/var/run/postgresql",
        "--host",
        help="PostgreSQL host or socket path",
    ),
    port: int = typer.Option(
        5432,
        "--port",
        help="PostgreSQL port",
    ),
    username: str | None = typer.Option(
        None,
        "--username",
        "-U",
        help="PostgreSQL user",
    ),
    jobs: int = typer.Option(
        4,
        "--jobs",
        "-j",
        help="Parallel workers for the data phase",
    ),
    no_owner: bool = typer.Option(
        False,
        "--no-owner/--owner",
        help="Skip ownership restoration",
    ),
    no_acl: bool = typer.Option(
        False,
        "--no-acl/--acl",
        help="Skip access privilege restoration",
    ),
    exit_on_error: bool = typer.Option(
        True,
        "--exit-on-error/--no-exit-on-error",
        help="Abort on first error (recommended for production restores)",
    ),
    min_tables: int = typer.Option(
        0,
        "--min-tables",
        help="Post-restore: minimum expected table count (0 = skip check)",
    ),
    min_tables_schema: str = typer.Option(
        "public",
        "--min-tables-schema",
        help="Schema for --min-tables validation",
    ),
    superuser: str | None = typer.Option(
        None,
        "--superuser",
        help="Run pg_restore via sudo as this OS user",
    ),
    refresh_matviews: bool = typer.Option(
        True,
        "--refresh-matviews/--no-refresh-matviews",
        help=(
            "Refresh materialized views after a database-wide ANALYZE (default). "
            "--no-refresh-matviews leaves them WITH NO DATA for you to refresh later."
        ),
    ),
) -> None:
    """Restore a PostgreSQL backup using three-phase pg_restore.

    Prevents FK constraint race conditions during parallel restore by running
    pre-data and post-data phases serially, parallelising only the data phase
    (where no FK constraints exist yet).

    When the backup contains materialized views, their REFRESH is deferred out of
    the parallel data phase: base tables load first, then a database-wide ANALYZE
    runs, then the matviews are refreshed serially — so every refresh replans on
    real statistics instead of the empty stats of a freshly loaded database (which
    can turn a fast refresh into a multi-hour nested loop). Use
    --no-refresh-matviews to leave them empty and refresh on your own schedule.

    Requires custom format (-Fc) or directory format (-Fd) dumps. To create one:

      pg_dump -Fc mydb > backup.pgdump

    Example usage:

      confiture restore prod.pgdump --database staging --jobs 4

      confiture restore prod.pgdump --database staging --jobs 8 --min-tables 300

      confiture restore /backups/dump --database staging --superuser postgres

      confiture restore prod.pgdump --database staging --no-refresh-matviews
    """

    if not backup_file.exists():
        fail(
            RestoreError(
                f"Backup file not found: {backup_file}",
                resolution_hint="Check the backup path; restore needs a -Fc/-Fd dump.",
            ),
            json_mode=False,
        )

    options = RestoreOptions(
        backup_path=backup_file,
        target_db=database,
        host=host,
        port=port,
        username=username,
        jobs=jobs,
        no_owner=no_owner,
        no_acl=no_acl,
        exit_on_error=exit_on_error,
        superuser=superuser,
        min_tables=min_tables,
        min_tables_schema=min_tables_schema,
        no_refresh_matviews=not refresh_matviews,
    )

    console.print(
        f"[bold]Restoring[/bold] [cyan]{verbatim(backup_file.name)}[/cyan] → [cyan]{verbatim(database)}[/cyan]"
    )

    def on_stderr_line(line: str) -> None:
        if "pg_restore: error:" in line:
            console.print(f"  [red]{verbatim(line)}[/red]")
        elif "pg_restore: warning:" in line:
            console.print(f"  [yellow]{verbatim(line)}[/yellow]")

    try:
        result = DatabaseRestorer().restore(options, on_stderr_line=on_stderr_line)
    except RestoreError as e:
        fail(e, json_mode=False)

    if result.warnings:
        console.print(f"[yellow]⚠ {len(result.warnings)} warning(s) during restore[/yellow]")

    if result.success:
        console.print(f"[green]✓ Restore complete[/green] ({len(result.phases_completed)} phases)")
        if result.matviews_deferred:
            if result.matviews_refreshed:
                console.print(
                    f"  Materialized views: {verbatim(result.matviews_refreshed)} refreshed after ANALYZE"
                )
            else:
                console.print(
                    f"  Materialized views: {verbatim(result.matviews_deferred)} left WITH NO DATA "
                    "(not refreshed) — refresh them after ANALYZE on your own schedule"
                )
        if result.table_count is not None:
            console.print(
                f"  Tables verified: {verbatim(result.table_count)} (≥ {verbatim(min_tables)} required)"
            )
    else:
        for err in result.errors:
            console.print(f"[red]{verbatim(err)}[/red]")
        fail(
            RestoreError("Restore failed; see the errors above."),
            json_mode=False,
        )
