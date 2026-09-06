"""`confiture migrate preflight`.

Split out of the monolithic migrate command modules (Phase 04, Cycle 8).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from confiture.cli.dsn import NO_CONFIG_OPTION_HELP
from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import (
    _emit_hint,
    _get_tracking_table,
    _output_json,
    _resolve_config,
    connect,
    console,
    error_console,
    is_json,
    open_connection,
)
from confiture.cli.options import format_option
from confiture.core._migrator.discovery import parse_migration_filename
from confiture.core._migrator.session import MigratorSession
from confiture.core.connection import load_config
from confiture.core.migrator import Migrator
from confiture.core.schema_facts import SchemaFacts
from confiture.exceptions import ConfigurationError
from confiture.url_redaction import redact_url

_CHANGE_SET_TIER_COLOR = {
    "additive": "green",
    "reversible": "green",
    "lock_risky": "yellow",
    "destructive": "red",
    "irreversible": "red",
}


def _preflight_version_from_filename(filename: str) -> str:
    """Extract version prefix from a migration filename."""
    return parse_migration_filename(filename)[0]


def _preflight_tracking_table(config: Path | None) -> str:
    """Resolve the configured ledger name for the preflight target (#190).

    Falls back to the default only when there is no config to read — never
    because the name was hardcoded.
    """
    if config is None or not Path(config).exists():
        return "tb_confiture"

    from confiture.cli.helpers import _get_tracking_table  # noqa: PLC0415
    from confiture.core.connection import load_config  # noqa: PLC0415

    try:
        return _get_tracking_table(load_config(Path(config)))
    except (OSError, ValueError, ConfigurationError):
        # An unreadable or malformed config: the preflight run itself fails
        # loudly a few lines later, so this advisory probe just defaults. The
        # catch is deliberately narrow — a bare `except Exception` here masked
        # a NameError and made this function silently return the default.
        return "tb_confiture"


def _target_tracking_table_state(session: MigratorSession, table: str) -> tuple[bool, bool]:
    """Return ``(exists, is_empty)`` for the preflight target's ledger.

    Split apart (#190) because the caller's hint means different things for the
    two states: a ledger that is *absent* was probably dropped during
    anonymization, while one that is *present but empty* was probably truncated.
    The old probe collapsed both — plus every error — into a single "looks
    empty" boolean, and queried the literal ``tb_confiture`` regardless of
    ``tracking_table``, which raises ``UndefinedTable`` on any project that
    renamed its ledger.

    Best-effort: presence comes from :func:`core.ledger.ledger_exists`, and any
    database error still degrades to "absent and empty", because the worst case
    is one extra advisory hint.
    """
    import contextlib

    from psycopg import sql as pgsql

    from confiture.core.ledger import ledger_exists, table_identifier  # noqa: PLC0415

    conn = getattr(session, "_conn", None)
    if conn is None:
        return (False, False)

    try:
        if not ledger_exists(conn, table):
            with contextlib.suppress(Exception):
                conn.rollback()
            return (False, True)

        with conn.cursor() as cur:
            cur.execute(pgsql.SQL("SELECT 1 FROM {} LIMIT 1").format(table_identifier(table)))
            row = cur.fetchone()
        # Roll back any aborted transaction state so run_against starts clean.
        with contextlib.suppress(Exception):
            conn.rollback()
        return (True, row is None)
    except Exception:  # noqa: BLE001 — best-effort: permission denied / connection drop
        with contextlib.suppress(Exception):
            conn.rollback()
        return (False, True)


def _collect_preflight_facts(session: MigratorSession) -> SchemaFacts:
    """Read the target's column types and server version (#199). Best-effort.

    The ``--against`` database is seeded from the production schema, which makes
    it the honest source for the *current* type of a column a migration is about
    to alter — the one fact ``ALTER TABLE … ALTER COLUMN … TYPE`` never states.
    Read before the replay, so it describes the schema being migrated *from*.

    Any failure yields empty facts and every consumer falls back to the static
    answer. Losing the refinement is acceptable; failing a preflight over it is
    not.
    """
    import contextlib

    from confiture.core.schema_facts import collect_schema_facts  # noqa: PLC0415

    conn = getattr(session, "_conn", None)
    if conn is None:
        return SchemaFacts()
    try:
        facts = collect_schema_facts(conn)
    except Exception:  # noqa: BLE001 — best-effort; never fail preflight for a refinement
        facts = SchemaFacts()
    # Leave no aborted transaction behind for run_against.
    with contextlib.suppress(Exception):
        conn.rollback()
    return facts


def _preflight_replica_policy(config: Path | None, env_name: str | None) -> tuple[bool, bool]:
    """Best-effort (has_replicas, bypass) for the replica lint, never connects.

    Reads ``infrastructure.replicas`` and ``migration.allow_unsafe_under_replication``
    from --env or --config when available; otherwise defaults to (False, False)
    — no replicas declared, so the replica lint warns rather than errors (#139).
    """
    try:
        from confiture.config.environment import Environment

        if env_name:
            e = Environment.load(env_name)
        elif config is not None and config.exists():
            from confiture.core.connection import load_config

            e = Environment.model_validate(load_config(config))
        else:
            return False, False
        return bool(e.infrastructure.replicas), bool(e.migration.allow_unsafe_under_replication)
    except Exception:  # noqa: BLE001 — policy degrades to warn-by-default
        return False, False


def _resolve_preflight_pending(
    migrations_dir: Path,
    *,
    config_path: Path | None,
    env_name: str | None,
    since: str | None,
    database_url_override: str | None = None,
) -> list[Path]:
    """Return migration files to test in a preflight --against run.

    Priority order:
    1. --database-url override (explicit flag only): connect to that DB, return
       pending files. Ambient env vars do not reach here — the caller passes a
       value only for an explicit flag (issue #140 precedence).
    2. --config / --env: connect to configured DB, return pending files.
    3. --since: all local files with version >= since (no DB required).
    4. Neither: all local migration files.
    """
    if database_url_override is not None or config_path is not None or env_name is not None:
        if database_url_override is not None:
            config_data: Any = {"database_url": database_url_override}
        else:
            resolved = _resolve_config(config_path or Path("confiture.yaml"), env_name)
            config_data = load_config(resolved)
        with open_connection(config_data) as conn:
            migrator = Migrator(
                connection=conn,
                migration_table=_get_tracking_table(config_data),
            )
            return migrator.find_pending(migrations_dir=migrations_dir)

    all_files: list[Path] = sorted(
        list(migrations_dir.glob("*.up.sql"))
        + [f for f in migrations_dir.glob("*.py") if not f.name.startswith("_")],
        key=lambda f: _preflight_version_from_filename(f.name),
    )

    if since is not None:
        return [f for f in all_files if _preflight_version_from_filename(f.name) >= since]

    return all_files


def _display_change_set(change_set: Any, cons: Any) -> None:
    """Render the #197 risk tiers: the worst tier, then the changes that are not additive.

    Text mode is for a human deciding whether to look closer, so it leads with
    the verdict. The full per-change set is the JSON payload's job.
    """
    if not change_set.changes:
        return

    total = len(change_set.changes)
    unclassified = sum(1 for c in change_set.changes if c.tier is None)

    worst = change_set.worst_tier
    if worst is not None:
        color = _CHANGE_SET_TIER_COLOR.get(worst.value, "yellow")
        # "classified" counts only what carries a tier — saying it of the whole
        # set would be the confident-wrong phrasing this feature exists to avoid.
        cons.print(
            f"Risk: [{color}]{worst.value}[/{color}] "
            f"(worst of {total - unclassified} classified change(s) of {total})"
        )
    if unclassified:
        cons.print(
            f"  [yellow]⚠️  {unclassified} change(s) could not be classified — "
            "a consumer gating on risk will refuse them[/yellow]"
        )
    # #199: a full-table rewrite is the thing that turns a deploy into an
    # outage, and it is not recoverable from the tier — an `additive`
    # `ADD COLUMN … DEFAULT` rewrites below PG 11, a `destructive` `DROP INDEX`
    # does not. Called out separately for that reason.
    rewrites = [c for c in change_set.changes if c.lock is not None and c.lock.rewrites_table]
    if rewrites:
        cons.print(
            f"  [yellow]⏳ {len(rewrites)} change(s) rewrite the table[/yellow] — "
            "plan for a maintenance window proportional to its size"
        )

    for change in change_set.changes:
        if change.tier is None or change.tier.severity == 0:
            continue  # additive changes are the floor; they do not need a line
        color = _CHANGE_SET_TIER_COLOR.get(change.tier.value, "yellow")
        cost = _lock_annotation(change.lock)
        cons.print(f"  [{color}]{change.tier.value}[/{color}] {change.kind} {change.object}{cost}")


def _lock_annotation(lock: Any) -> str:
    """`  [rewrite, minutes+]` — what the change costs, or nothing if unknown (#199)."""
    if lock is None:
        return ""
    parts = ["rewrite"] if lock.rewrites_table else []
    if lock.blocks_writes and not lock.blocks_reads:
        parts.append("blocks writes")
    elif lock.blocks_reads:
        parts.append("blocks reads+writes")
    parts.append(lock.duration.value)
    return f"  [dim]({', '.join(parts)})[/dim]"


def _display_against_result(
    result: Any,
    format_type: str,
    cons: Any,
) -> None:
    """Render --against execution results to the console."""

    if format_type == "json":
        return

    safe_url = redact_url(result.against_url)
    cons.print(
        f"\nExecution check: {len(result.migrations)} migration(s) against [dim]{safe_url}[/dim]"
    )

    for m in result.migrations:
        if m.skipped:
            cons.print(f"  [yellow]⤳[/yellow]  {m.version}  {m.name:<40}  [dim](skipped)[/dim]")
            if m.skipped_reason:
                cons.print(f"       [dim]{m.skipped_reason}[/dim]")
        elif m.success:
            cons.print(
                f"  [green]✓[/green]  {m.version}  {m.name:<40}  "
                f"({m.execution_time_ms / 1000:.2f}s)"
            )
        else:
            cons.print(f"  [red]✗[/red]  {m.version}  {m.name:<40}")
            if m.error:
                first_line = m.error.splitlines()[0][:120]
                cons.print(f"       [red]Error:[/red] {first_line}")

    cons.print()
    if result.all_passed:
        if result.has_skipped:
            cons.print(
                f"  [green]✓[/green] All {len(result.migrations)} migration(s) passed "
                f"({len(result.skipped_migrations)} skipped)."
            )
        else:
            cons.print(f"  [green]✓[/green] All {len(result.migrations)} migration(s) passed.")
    else:
        cons.print(
            f"  [red]✗[/red] {len(result.failures)} of "
            f"{len(result.migrations)} migration(s) would fail."
        )
    if result.db_consumed:
        cons.print("  [yellow]⚠[/yellow]  Preflight DB consumed — reprovision before next run.")
    else:
        cons.print("  [dim](Rolled back — preflight DB unchanged)[/dim]")


def _run_dependent_check(
    *,
    mode: str,
    pending_files: list[Path],
    migrations_dir: Path,
    against_url: str,
) -> Any:
    """Resolve pending migrations' CoR targets and run the pg_depend check.

    On any error (pglast missing, connection failure, query failure) returns
    a skipped report with a clear reason rather than raising — the caller
    decides how to surface that. ``mode`` is ``"fail"`` (severity=error) or
    ``"warn"`` (severity=info).
    """
    from confiture.models.preflight import DependentAnalysisReport

    try:
        from confiture.core.cor_extractor import find_cor_targets_in_file
    except ImportError:
        error_console.print(
            "[red]❌ Dependent check requires pglast. "
            "Install with: pip install fraiseql-confiture[ast][/red]"
        )
        return DependentAnalysisReport(
            entries=[], status="skipped", skip_reason="pglast_not_installed"
        )

    targets: list[Any] = []
    for migration_file in pending_files:
        targets.extend(find_cor_targets_in_file(migration_file, project_root=migrations_dir))

    if not targets:
        return DependentAnalysisReport(entries=[], status="ok")

    import psycopg

    from confiture.core.dependent_objects import DependentObjectsChecker

    severity = "info" if mode == "warn" else "error"
    try:
        with psycopg.connect(against_url) as conn:
            return DependentObjectsChecker(severity=severity).check(targets, conn)
    except psycopg.Error as e:
        error_console.print(f"[red]❌ Dependent check connection failed: {e}[/red]")
        return DependentAnalysisReport(
            entries=[], status="skipped", skip_reason="connection_failed"
        )


def _display_dependent_analysis(report: Any, cons: Any) -> None:
    """Render the dependent-objects analysis section."""
    cons.print()
    if report.status == "skipped":
        cons.print(
            f"[yellow]⚠️  Dependent analysis skipped[/yellow] [dim]({report.skip_reason})[/dim]"
        )
        return

    if not report.entries:
        cons.print("[green]✓[/green] No CREATE OR REPLACE targets in pending migrations.")
        return

    blocking = report.has_blocking()
    if blocking:
        cons.print("[red]Dependent analysis — live dependents found:[/red]")
    elif any(e.dependents for e in report.entries):
        cons.print("[yellow]Dependent analysis — live dependents (informational):[/yellow]")
    else:
        cons.print("[green]✓[/green] No dependents found for replaced objects.")
        return

    for entry in report.entries:
        if not entry.dependents:
            continue
        sev = entry.severity
        marker = "[red]✗[/red]" if sev == "error" else "[yellow]ℹ[/yellow]"
        cons.print(
            f"  {marker} {entry.target.kind} [cyan]{entry.target.qualified}[/cyan] "
            f"is being replaced; {len(entry.dependents)} dependent(s):"
        )
        for dep in entry.dependents:
            cols = (
                f"  [dim](references: {', '.join(dep.referenced_columns)})[/dim]"
                if dep.referenced_columns
                else ""
            )
            cons.print(f"      - {dep.kind} [cyan]{dep.schema}.{dep.name}[/cyan]{cols}")


@cli_boundary
def migrate_preflight(
    ctx: typer.Context,
    migrations_dir: Path = typer.Option(
        Path("db/migrations"),
        "--migrations-dir",
        help="Migrations directory (default: db/migrations)",
    ),
    format_type: str = format_option("table", "json"),
    output_file: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save output to file (default: stdout)",
    ),
    against: str | None = typer.Option(
        None,
        "--against",
        help=(
            "PostgreSQL URL of the preflight database to test migrations against. "
            "Typically seeded from pg_dump --schema-only. "
            "Migrations are executed inside a transaction that is always rolled back."
        ),
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help=(
            "Config file for pending-migration detection. "
            "Connects to the configured database to read the tracking table."
        ),
    ),
    database_url: str | None = typer.Option(
        None,
        "--database-url",
        "-d",
        help=(
            "PostgreSQL DSN of the tracking database for pending-migration "
            "detection (distinct from --against, which is the throwaway target). "
            "Takes precedence over --config / --env and the CONFITURE_DATABASE_URL "
            "/ DATABASE_URL env vars."
        ),
    ),
    env: str | None = typer.Option(
        None,
        "--env",
        help="Environment shortcut — db/environments/{name}.yaml (e.g. --env production).",
    ),
    no_config: bool = typer.Option(
        False,
        "--no-config",
        help=NO_CONFIG_OPTION_HELP,
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help=(
            "Test migrations with version >= SINCE (e.g. --since 20260428000000). "
            "Inclusive. Alternative to --config when no second DB connection is available."
        ),
    ),
    allow_non_transactional: bool = typer.Option(
        False,
        "--allow-non-transactional",
        help=(
            "Run non-transactional migrations (CREATE INDEX CONCURRENTLY, etc.) "
            "outside the rollback SAVEPOINT in autocommit mode. "
            "The preflight DB will be permanently modified (db_consumed=True). "
            "By default such migrations are skipped."
        ),
    ),
    check_dependents: str = typer.Option(
        "off",
        "--check-dependents",
        help=(
            "Enumerate live dependents of CREATE OR REPLACE targets via "
            "pg_depend on the --against preflight DB. "
            "'off' (default), 'fail' (exit 1 on dependents found), or "
            "'warn' (render dependents as informational, exit code unchanged). "
            "Requires the [ast] extra (pglast)."
        ),
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Treat warnings as errors for exit purposes (warnings → exit 7).",
    ),
) -> None:
    """Check if pending migrations are safe to deploy.

    Verifies reversibility (.down.sql exists), detects non-transactional
    statements (CREATE INDEX CONCURRENTLY, etc.), checks for duplicate
    versions, and verifies checksums of applied migrations.

    MODES:
      Default mode — static analysis only. No --against, no DB connection.
        Scans local migration files and reports per-file reversibility +
        transactionality. Cannot detect "is this migration already
        applied?" because there's no source of truth to compare against.

      Explicit source mode — --against <url> [+ --config OR --env OR --since]
        Replays pending migrations inside a SAVEPOINT against a preflight
        DB and reports per-migration success/failure. Source of "pending"
        is determined by the flag combination:
          • --against alone        → all local files
          • --against + --config   → pending files (read tb_confiture from
                                     the --config DB, not from --against)
          • --against + --env      → same, using db/environments/{env}.yaml
          • --against + --since V  → all files with version >= V (no DB
                                     needed for pending detection)

    EXAMPLES:
      confiture migrate preflight
        ↳ Check all migration files in db/migrations

      confiture migrate preflight --format json
        ↳ Output structured JSON for CI/CD integration

      confiture migrate preflight --migrations-dir custom/migrations
        ↳ Check migrations in a custom directory

      confiture migrate preflight --against postgresql://localhost/myapp_preflight
        ↳ Test all local migrations against a schema-only preflight DB

      confiture migrate preflight --against postgresql://localhost/myapp_preflight --env production
        ↳ Test only pending migrations (detected from production tracking table)

      confiture migrate preflight --against postgresql://localhost/myapp_preflight --since 20260428000000
        ↳ Test migrations at or after version 20260428000000 (inclusive)

      confiture migrate preflight --against postgresql://localhost/myapp_preflight --allow-non-transactional
        ↳ Also run non-transactional migrations in autocommit mode (preflight DB consumed)

      confiture migrate preflight --against postgresql://localhost/myapp_preflight --format json
        ↳ Output static + execution results as JSON

    EXIT CODES (default, no --against — the structured report, issue #148):
      0 — no error-severity issues (warnings alone are non-fatal unless --strict)
      7 — one or more error-severity issues (or, under --strict, any warning)
      A preflight that *crashes* (config/DB error) exits per the #146 convention
      (e.g. 5 config invalid, 3 connection failed) with the #145 error envelope.

    With --against (execution replay, #151):
      0 — all replays passed; 7 — one or more replays failed (a replay failure is
      an error-severity issue, folded into the unified report); an unreachable
      --against URL → 3 (connection failed), other config/connection errors per #146.

    JSON SCHEMA:
      See docs/reference/json-schemas.md for the JSON output schemas:
        - default: migrate-preflight.schema.json
        - with --against: migrate-preflight-against.schema.json
    """
    from confiture.core.change_set import build_change_set
    from confiture.core.linting.libraries.replica import replica_preflight_issues
    from confiture.core.preflight import preflight_exit_code, run_preflight

    if check_dependents not in {"off", "fail", "warn"}:
        error_console.print(
            f"[red]❌ Invalid --check-dependents value: {check_dependents!r}. "
            "Must be one of 'off', 'fail', 'warn'.[/red]"
        )
        raise typer.Exit(2)

    result = run_preflight(migrations_dir)

    if against is None:
        _static_preflight(
            result,
            migrations_dir=migrations_dir,
            config=config,
            env=env,
            check_dependents=check_dependents,
            strict=strict,
            format_type=format_type,
            output_file=output_file,
        )
        return

    # --against path: static analysis + exhaustive execution against preflight DB.
    pending_files = _against_pending_files(
        ctx,
        migrations_dir=migrations_dir,
        config=config,
        env=env,
        since=since,
        database_url=database_url,
        no_config=no_config,
        format_type=format_type,
        output_file=output_file,
    )
    # Resolved once and threaded through the override, the probe and the hint
    # (#190) — three sites that previously each spelled the default by hand.
    target_tracking_table = _preflight_tracking_table(config)
    run = _run_against(
        pending_files,
        migrations_dir=migrations_dir,
        against=against,
        tracking_table=target_tracking_table,
        allow_non_transactional=allow_non_transactional,
        format_type=format_type,
        output_file=output_file,
    )
    dependent_report = None
    if check_dependents != "off":
        dependent_report = _run_dependent_check(
            mode=check_dependents,
            pending_files=pending_files,
            migrations_dir=migrations_dir,
            against_url=against,
        )
    if run.tracking_empty and pending_files:
        _state = "is empty" if run.tracking_exists else "is missing"
        _emit_hint(
            f"`{target_tracking_table}` on the target {_state}. If --against points "
            "at a restored backup, was the tracking table dropped during "
            "anonymization?",
            # The unified --against envelope (#151) has no `hints` array; in
            # text mode this still prints the breadcrumb to stderr.
            hints_list=[],
            format_=format_type,
        )

    # #151: unified {ok, summary, issues[]} envelope — same shape as the
    # no-`--against` path. Replay failures join the static + replica findings;
    # run-level metadata (db_consumed) rides in `summary`.
    _has_replicas, _replica_bypass = _preflight_replica_policy(config, env)
    replica_issues = replica_preflight_issues(
        migrations_dir, has_replicas=_has_replicas, bypass=_replica_bypass
    )
    all_issues = result.issues + replica_issues + run.result.replay_issues
    summary = _preflight_summary(
        all_issues,
        migrations_checked=len(run.result.migrations),
        db_consumed=run.result.db_consumed,
    )
    exit_code = preflight_exit_code(summary, strict=strict)
    # #199: the same change set as the no-`--against` path, plus the refinements
    # the target database made possible (current column types, server version).
    change_set = build_change_set(migrations_dir, facts=run.facts)
    if format_type == "json":
        payload = _preflight_payload(all_issues, summary, change_set, exit_code)
        if dependent_report is not None:
            payload["dependent_analysis"] = dependent_report.to_dict()
        _output_json(payload, output_file, console)
    else:
        _display_against_result(run.result, format_type, console)
        _display_change_set(change_set, console)
        if dependent_report is not None:
            _display_dependent_analysis(dependent_report, console)
    if exit_code:
        raise typer.Exit(exit_code)
    if dependent_report is not None and dependent_report.has_blocking():
        raise typer.Exit(1)


def _preflight_summary(all_issues: list[Any], **counts: Any) -> dict[str, Any]:
    return {
        "errors": sum(1 for i in all_issues if i.severity in ("error", "critical")),
        "warnings": sum(1 for i in all_issues if i.severity == "warning"),
        "info": sum(1 for i in all_issues if i.severity == "info"),
        **counts,
    }


def _preflight_payload(
    all_issues: list[Any], summary: dict[str, Any], change_set: Any, exit_code: int
) -> dict[str, Any]:
    from confiture.core.preflight import is_window_safe

    return {
        "ok": exit_code == 0,
        # #154: top-level typed blue-green window-safety verdict — the whole
        # safety contract for the consumer (folds in replica-unsafe ops,
        # unreadable .py migrations, and the down path).
        "window_safe": is_window_safe(all_issues),
        "summary": summary,
        "issues": [i.to_dict() for i in all_issues],
        # #197: per-change risk tiers. The object wrapper is load-bearing —
        # an empty `changes` means "classified, nothing to change", while an
        # absent `change_set` means "did not classify" and denies.
        "change_set": change_set.to_dict(),
    }


def _static_preflight(
    result: Any,
    *,
    migrations_dir: Path,
    config: Path,
    env: str | None,
    check_dependents: str,
    strict: bool,
    format_type: str,
    output_file: Path | None,
) -> None:
    """No ``--against``: static findings only, flat output."""
    from confiture.core.change_set import build_change_set
    from confiture.core.linting.libraries.replica import replica_preflight_issues
    from confiture.core.preflight import preflight_exit_code

    # #148 structured report + #139 replica-safety: merge the base preflight
    # issues with the replica-forward-compat findings (PFLIGHT_REPLICA_*).
    has_replicas, replica_bypass = _preflight_replica_policy(config, env)
    replica_issues = replica_preflight_issues(
        migrations_dir, has_replicas=has_replicas, bypass=replica_bypass
    )
    all_issues = result.issues + replica_issues
    summary = _preflight_summary(all_issues, migrations_checked=len(result.migrations))
    exit_code = preflight_exit_code(summary, strict=strict)
    change_set = build_change_set(migrations_dir)
    if format_type == "json":
        payload = _preflight_payload(all_issues, summary, change_set, exit_code)
        if check_dependents != "off":
            payload["dependent_analysis"] = {
                "status": "skipped",
                "entries": [],
                "has_blocking": False,
                "skip_reason": "no_preflight_db",
            }
        _output_json(payload, output_file, console)
    else:
        _render_static_preflight(result, summary, change_set, all_issues, check_dependents)
    if exit_code:
        raise typer.Exit(exit_code)


def _render_static_preflight(
    result: Any, summary: dict[str, Any], change_set: Any, issues: list[Any], check_dependents: str
) -> None:
    from rich.table import Table

    table = Table(title="Pre-flight Check")
    table.add_column("Version", style="cyan")
    table.add_column("Name")
    table.add_column("Reversible", justify="center")
    table.add_column("Transactional", justify="center")
    for m in result.migrations:
        rev = "[green]✓[/green]" if m.reversible else "[red]✗[/red]"
        if m.fully_transactional:
            txn = "[green]✓[/green]"
        else:
            txn = "[red]✗[/red] " + "; ".join(m.non_transactional_statements)
        table.add_row(m.version, m.name, rev, txn)
    console.print(table)
    console.print(
        f"\nSummary: {summary['migrations_checked']} migration(s) checked, "
        f"{summary['errors']} error(s), {summary['warnings']} warning(s)"
    )
    _display_change_set(change_set, console)
    if not issues:
        console.print("  [green]✓ No issues[/green]")
    for issue in issues:
        color = "red" if issue.severity == "error" else "yellow"
        console.print(
            f"  [{color}]{issue.severity.upper()}[/{color}] {issue.code}: {issue.message}"
        )
        if issue.actionable:
            console.print(f"    [dim]💡 {issue.actionable}[/dim]")
    if check_dependents != "off":
        console.print(
            "[yellow]⚠️  Dependent check skipped: no preflight DB configured. "
            "Pass --against <url> to enable.[/yellow]"
        )


def _against_pending_files(
    ctx: typer.Context,
    *,
    migrations_dir: Path,
    config: Path,
    env: str | None,
    since: str | None,
    database_url: str | None,
    no_config: bool,
    format_type: str,
    output_file: Path | None,
) -> list[Path]:
    """The pending set to replay, under the #152 DSN-precedence contract.

    A ``--database-url`` flag, ``--no-config``, an explicit ``--config``/``--env``,
    or the canonical ``CONFITURE_DATABASE_URL`` drive a tracking-DB connect; a
    merely-ambient ``DATABASE_URL`` must NOT silently flip "``--against`` alone →
    all local files" into a tracking-DB connect. Two explicit sources fail loud
    (CONFIG_007).
    """
    try:
        from confiture.cli.dsn import (
            config_is_explicit,
            has_intentional_dsn_source,
            resolve_database_url,
        )

        return _resolve_preflight_pending(
            migrations_dir=migrations_dir,
            config_path=config,
            env_name=env,
            since=since,
            database_url_override=(
                resolve_database_url(
                    database_url,
                    config,
                    config_explicit=config_is_explicit(ctx),
                    no_config=no_config,
                )
                if has_intentional_dsn_source(ctx, database_url, no_config)
                else None
            ),
        )
    except Exception as e:
        from confiture.exceptions import ConfigurationError, ConfiturError  # noqa: PLC0415

        # #152: a precedence conflict (CONFIG_007) or missing source (CONFIG_010)
        # — and any other ConfiturError — surfaces with its own exit code +
        # remediation via the shared error boundary.
        if isinstance(e, ConfiturError):
            fail(e, json_mode=is_json(format_type), output_file=output_file)
        # #151: any other failure resolving the pending set is a harness /
        # connection failure — align to the canonical connection-failure exit 3
        # (CONFIG_006), not the old generic exit 2.
        fail(
            ConfigurationError(
                f"Failed to resolve pending migrations: {e}",
                error_code="CONFIG_006",
            ),
            json_mode=is_json(format_type),
            output_file=output_file,
        )


@dataclass(frozen=True)
class _AgainstRun:
    result: Any
    facts: SchemaFacts
    tracking_exists: bool
    tracking_empty: bool


def _run_against(
    pending_files: list[Path],
    *,
    migrations_dir: Path,
    against: str,
    tracking_table: str,
    allow_non_transactional: bool,
    format_type: str,
    output_file: Path | None,
) -> _AgainstRun:
    """Replay the pending set against the preflight database."""
    target_tracking_empty = False
    target_tracking_exists = True
    # Empty unless the --against connection yields facts (#199).
    schema_facts = SchemaFacts()
    try:
        session = MigratorSession(
            config=None,
            migrations_dir=migrations_dir,
            database_url_override=against,
            migration_table_override=tracking_table,
            connection_factory=connect,
        )
        with session:
            # Snapshot whether the target's tracking table is empty BEFORE the
            # SAVEPOINT-bounded run_against — used to emit a quiet-success hint
            # when the target looks like a restored backup with the tracking
            # table stripped.
            target_tracking_exists, target_tracking_empty = _target_tracking_table_state(
                session, tracking_table
            )
            # #199: read the current column types and server version BEFORE the
            # replay, so `ALTER COLUMN … TYPE` can be reasoned about as widening
            # or narrowing. Strictly additive — failure leaves `schema_facts`
            # empty and every answer falls back to the static one.
            schema_facts = _collect_preflight_facts(session)
            against_result = session.run_against(
                pending_files,
                against_url=against,
                allow_non_transactional=allow_non_transactional,
            )
    except Exception as e:
        # #151: an unreachable --against URL is a connection failure → exit 3
        # (CONFIG_006), with the shared {ok:false, error} envelope in JSON mode.
        from confiture.exceptions import ConfigurationError  # noqa: PLC0415

        fail(
            ConfigurationError(
                f"Connection to --against URL failed: {e}",
                error_code="CONFIG_006",
            ),
            json_mode=is_json(format_type),
            output_file=output_file,
        )
    return _AgainstRun(against_result, schema_facts, target_tracking_exists, target_tracking_empty)
