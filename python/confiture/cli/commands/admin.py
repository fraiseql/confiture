"""Admin commands: install_helpers, validate_profile, verify-checksums, restore,
validate-config."""

from pathlib import Path

import typer

from confiture.cli.error_json import fail
from confiture.cli.helpers import (
    DATABASE_URL_OPTION_HELP,
    _get_tracking_table,
    _output_json,
    console,
    error_console,
    is_json,
    resolve_database_url,
)
from confiture.core.connection import create_connection
from confiture.core.error_handler import handle_cli_error
from confiture.exceptions import (
    ConfigurationError,
    ConfiturError,
    DatabaseNotInitializedError,
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
    """
    payload: dict = {
        "ok": not mismatches,
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


def install_helpers(
    config: Path = typer.Option(
        None,
        "--config",
        "-c",
        help="Configuration file (YAML)",
    ),
    env: str = typer.Option(
        "local",
        "--env",
        "-e",
        help="Environment name (default: local)",
    ),
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
) -> None:
    """Install confiture SQL helper functions in the target database.

    Creates the `confiture` schema with `save_and_drop_dependent_views()`
    and `recreate_saved_views()` PL/pgSQL functions for use in migrations
    that need to ALTER COLUMN TYPE on tables with dependent views.
    """
    try:
        from confiture.core.connection import load_config
        from confiture.core.view_manager import ViewManager

        if config:
            cfg = load_config(config)
        else:
            from confiture.config.environment import Environment

            environment = Environment.load(env)
            cfg = {"database": {"url": environment.database_url}}

        conn = create_connection(cfg)

        if dry_run:
            from importlib import resources

            sql = resources.files("confiture.sql").joinpath("view_helpers.sql").read_text()
            console.print("[bold]SQL that would be executed:[/bold]\n")
            console.print(sql)
            conn.close()
            return

        vm = ViewManager(conn)

        if not force and vm.helpers_installed():
            console.print("[green]✓[/green] View helpers already installed — nothing to do")
            console.print("  Use [bold]--force[/bold] to reinstall")
            conn.close()
            return

        vm.install_helpers()
        conn.close()

        console.print("[green]✓[/green] Installed confiture view helper functions")
        console.print("  Schema: [bold]confiture[/bold]")
        console.print("  Functions:")
        console.print("    • confiture.save_and_drop_dependent_views(schemas TEXT[])")
        console.print("    • confiture.recreate_saved_views()")

    except Exception as e:
        raise typer.Exit(handle_cli_error(e)) from e


def validate_profile(
    path: Path = typer.Argument(
        ...,
        help="Path to anonymization profile YAML file",
    ),
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
    try:
        from confiture.core.anonymization.profile import AnonymizationProfile

        console.print(f"[cyan]📋 Validating profile: {path}[/cyan]")
        profile = AnonymizationProfile.load(path)

        # Print profile summary
        console.print("[green]✅ Valid profile![/green]")
        console.print(f"   Name: {profile.name}")
        console.print(f"   Version: {profile.version}")
        if profile.global_seed:
            console.print(f"   Global Seed: {profile.global_seed}")

        # List strategies
        console.print(f"\n[cyan]Strategies ({len(profile.strategies)})[/cyan]:")
        for strategy_name, strategy_def in profile.strategies.items():
            console.print(
                f"   • {strategy_name}: {strategy_def.type}",
                end="",
            )
            if strategy_def.seed_env_var:
                console.print(f" [env: {strategy_def.seed_env_var}]")
            else:
                console.print()

        # List tables
        console.print(f"\n[cyan]Tables ({len(profile.tables)})[/cyan]:")
        for table_name, table_def in profile.tables.items():
            console.print(f"   • {table_name}: {len(table_def.rules)} rules")
            for rule in table_def.rules:
                console.print(f"      - {rule.column} → {rule.strategy}", end="")
                if rule.seed:
                    console.print(f" [seed: {rule.seed}]")
                else:
                    console.print()

        console.print("[green]\n✅ Profile validation passed![/green]")

    except FileNotFoundError as e:
        fail(
            ConfigurationError(
                f"Profile file not found: {e}",
                error_code="CONFIG_004",
                resolution_hint="Check the path to the anonymization profile YAML.",
            ),
            json_mode=False,
        )
    except ValueError as e:
        fail(
            ConfiturError(f"Invalid profile: {e}", error_code="ANON_1400"),
            json_mode=False,
        )
    except Exception as e:
        fail(e, json_mode=False)


def verify_checksums(
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file",
    ),
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
    output_format: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text or json (default: text)",
    ),
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

    JSON output: {ok, ledger_present, summary{checked,mismatched,tracking_table},
    issues[]} — see docs/reference/json-schemas/verify-checksums.schema.json.
    Exit 1 on mismatches is a success-signal (the gate tripped), so it still
    carries this shape; a real error emits the error envelope instead.
    """
    from confiture.core.checksum import (
        ChecksumConfig,
        ChecksumMismatchBehavior,
        MigrationChecksumVerifier,
    )
    from confiture.core.connection import create_connection, load_config
    from confiture.core.ledger import find_ledger_relations, notable_resolution, probe_ledger

    if output_format not in ("text", "json"):
        fail(
            ConfigurationError(
                f"Invalid format '{output_format}'. Use 'text' or 'json'.",
                resolution_hint="Pass --format text or --format json.",
            ),
            json_mode=False,
        )
    json_mode = is_json(output_format)

    try:
        # Load config and connect
        config_data = load_config(config)
        conn = create_connection(config_data)

        # Probe before building the verifier: if verify_all() returned [] for
        # "no table", that would be indistinguishable from "no mismatches" —
        # the absent-vs-empty conflation this guard exists to prevent.
        tracking_table = _get_tracking_table(config_data)
        ledger = probe_ledger(conn, tracking_table)
        if not ledger.exists:
            # Since 0.41.0 a bare name is resolved through search_path, so
            # "absent" can mean "present, but not where this session looks".
            # Saying which is the difference between an actionable message and
            # a puzzle (#188).
            _elsewhere = find_ledger_relations(conn, tracking_table)
            _note = (
                f" A relation of that name does exist in {', '.join(_elsewhere)}, but this "
                "connection's search_path does not reach it."
                if _elsewhere
                else ""
            )
            conn.close()
            if allow_uninitialized:
                if json_mode:
                    # 0.37.0 turned this crash into a graceful exit but left it
                    # returning after a Rich print, so --format json produced
                    # no JSON at all on the one path most likely to be scripted.
                    _output_json(
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
                    f"[yellow]ℹ️  No migration ledger found (`{tracking_table}` is not "
                    f"present in this database){_note} — 0 migrations recorded, nothing to "
                    "verify.[/yellow]"
                )
                return
            raise DatabaseNotInitializedError(
                f"No migration ledger found: `{tracking_table}` is not present in "
                f"this database.{_note}",
                resolution_hint=_NO_LEDGER_HINT,
            )

        # Run verification (warn mode - we'll handle display)
        verifier = MigrationChecksumVerifier(
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
                _output_json(
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
                console.print(f"[green]✅ All migration checksums verified!{_suffix}[/green]")
            conn.close()
            return

        updated: int | None = None
        if fix:
            updated = verifier.update_all_checksums(migrations_dir)

        if json_mode:
            _output_json(
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
            console.print(f"[red]❌ Found {len(mismatches)} checksum mismatch(es):[/red]\n")
            for m in mismatches:
                console.print(f"  [yellow]{m.version}_{m.name}[/yellow]")
                console.print(f"    File: {m.file_path}")
                expected_preview = m.expected[:16] if m.expected else "(none)"
                console.print(f"    Expected: {expected_preview}...")
                console.print(f"    Actual:   {m.actual[:16]}...")
                console.print()
            if fix:
                console.print("[yellow]⚠️  Updating stored checksums...[/yellow]")
                console.print(f"[green]✅ Updated {updated} checksum(s)[/green]")
            else:
                console.print(
                    "[yellow]💡 Tip: Use --fix to update stored checksums (dangerous)[/yellow]"
                )

        conn.close()
        if not fix:
            # success-signal: verification ran and found mismatches (the CI gate
            # this command exists to trip) — not a confiture-domain error.
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        fail(e, json_mode=json_mode)


def verify_deprecated(
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        "-c",
        help="Configuration file",
    ),
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
    output_format: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text or json (default: text)",
    ),
) -> None:
    """[DEPRECATED] Alias for `confiture verify-checksums`.

    `confiture verify` was ambiguous with `confiture migrate verify` (runtime
    correctness). Use `confiture verify-checksums` for file-integrity checks.
    This alias still works for one release cycle and is removed in the next major.
    """
    # Warning to stderr so piped/JSON stdout consumers stay clean (#143).
    error_console.print(
        "[yellow]⚠️  'confiture verify' is deprecated and will be removed in a "
        "future major release. Use 'confiture verify-checksums' for checksum "
        "integrity (or 'confiture migrate verify' for runtime correctness).[/yellow]"
    )
    # Every argument forwarded explicitly: an omitted one arrives as Typer's
    # OptionInfo sentinel rather than its default, which the format validation
    # would reject as an invalid format (exit 5).
    verify_checksums(
        migrations_dir=migrations_dir,
        config=config,
        fix=fix,
        allow_uninitialized=allow_uninitialized,
        output_format=output_format,
    )


def validate_config(
    config: Path = typer.Option(
        None,
        "--config",
        "-c",
        help="Configuration file to validate (default: db/environments/local.yaml)",
    ),
    database_url: str = typer.Option(
        None,
        "--database-url",
        "-d",
        help=DATABASE_URL_OPTION_HELP,
    ),
    migrations_path: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-path",
        help="Migrations directory to validate (default: db/migrations)",
    ),
    output_format: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: text or json (default: text)",
    ),
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
    from confiture.core.config_validator import ConfigValidator

    if output_format not in ("text", "json"):
        fail(
            ConfigurationError(
                f"Invalid format '{output_format}'. Use 'text' or 'json'.",
                resolution_hint="Pass --format text or --format json.",
            ),
            json_mode=False,
        )

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
        _output_json(report.to_dict(), None, console)
        if exit_code:
            raise typer.Exit(exit_code)
        return

    if report.valid and not report.issues:
        console.print(
            f"[green]✅ Configuration valid[/green] "
            f"({report.config_source}, {report.migration_count} migration(s))"
        )
        if exit_code:
            raise typer.Exit(exit_code)
        return

    error_console.print(f"[red]❌ Configuration issues ({report.config_source}):[/red]")
    for issue in report.issues:
        color = "red" if issue.severity in ("error", "critical") else "yellow"
        error_console.print(
            f"  [{color}]{issue.severity.upper()}[/{color}] {issue.code}: {issue.message}"
        )
        if issue.actionable:
            error_console.print(f"    [dim]💡 {issue.actionable}[/dim]")
    if exit_code:
        raise typer.Exit(exit_code)


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
    from confiture.core.restorer import DatabaseRestorer, RestoreOptions
    from confiture.exceptions import RestoreError

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
        f"[bold]Restoring[/bold] [cyan]{backup_file.name}[/cyan] → [cyan]{database}[/cyan]"
    )

    def on_stderr_line(line: str) -> None:
        if "pg_restore: error:" in line:
            console.print(f"  [red]{line}[/red]")
        elif "pg_restore: warning:" in line:
            console.print(f"  [yellow]{line}[/yellow]")

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
                    f"  Materialized views: {result.matviews_refreshed} refreshed after ANALYZE"
                )
            else:
                console.print(
                    f"  Materialized views: {result.matviews_deferred} left WITH NO DATA "
                    "(not refreshed) — refresh them after ANALYZE on your own schedule"
                )
        if result.table_count is not None:
            console.print(f"  Tables verified: {result.table_count} (≥ {min_tables} required)")
    else:
        for err in result.errors:
            console.print(f"[red]{err}[/red]")
        fail(
            RestoreError("Restore failed; see the errors above."),
            json_mode=False,
        )
