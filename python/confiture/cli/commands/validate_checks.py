"""Check adapters and registry construction for ``migrate validate`` (#187).

:func:`build_registry` turns one parsed invocation into the ordered list of
:class:`~confiture.core.validation.registry.ValidationCheck` descriptors the
runner executes. Each adapter here is the seam between a ``core/validation``
handler (which computes) and a ``formatters/validate_formatter`` renderer
(which prints or returns a payload); the adapter itself only decides whether
the check passed.

The registry order reproduces the pre-0.40.0 dispatch order exactly, so a
single-flag invocation behaves — and prints — as it always did. That is
deliberate: reordering for elegance would change which error a user sees first
for no benefit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from confiture.cli.helpers import _validate_idempotency, console
from confiture.core.validation.registry import CheckOutcome, ValidationCheck
from confiture.exceptions import ConfigurationError, GitError

if TYPE_CHECKING:
    from typing import Any

    from confiture.core.validation.context import ValidationContext


# Flags that are modifiers rather than checks, and the checks they modify. Each
# entry is (flag, "at least one of these must also be on"). Replaces the ad-hoc
# `if check_body and not check_signatures` guards that used to sit halfway down
# the dispatch — halfway down meant a git flag returned before they were ever
# evaluated, so an illegal combination could pass silently.
_FLAG_DEPENDENCIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("--check-body", ("--check-signatures",)),
    ("--show-diff", ("--check-body", "--check-body-views", "--check-body-replay")),
)


@dataclass(frozen=True)
class ValidateOptions:
    """One parsed ``migrate validate`` invocation.

    Carries the Typer options verbatim, plus the two values the command
    resolves before building the registry: ``git_env`` and
    ``idempotent_base_ref`` (which encodes #181's "was scoping actually asked
    for?" decision, since ``--base-ref``'s default is truthy).
    """

    # Output
    format_output: str
    json_mode: bool
    # Paths and connection
    migrations_dir: Path
    config: Path
    git_env: str
    schema_file: Path | None
    scratch_url: str | None
    schemas: str
    ssh_via: str | None
    ddl_dir: list[Path] = field(default_factory=list)
    # Enabling flags, in dispatch order
    list_patterns: bool = False
    list_unmigrated_bodies: bool = False
    check_drift: bool = False
    require_migration: bool = False
    require_migration_bodies: bool = False
    require_grant_migration: bool = False
    check_acls: bool = False
    check_ownership_coverage: bool = False
    check_function_uniqueness: bool = False
    check_security_definer: bool = False
    check_imports: bool = False
    check_live_drift: bool = False
    check_signatures: bool = False
    check_body_views: bool = False
    check_body_replay: bool = False
    idempotent: bool = False
    # Modifiers
    allow_grant_only: bool = False
    staged: bool = False
    check_body: bool = False
    show_diff: bool = False
    strict_cor: bool = False
    secdef_against_db: bool = False
    emit_remediation: Path | None = None
    fix_naming: bool = False
    dry_run: bool = False
    idempotent_base_ref: str | None = None

    @property
    def scan_paths(self) -> list[Path]:
        """DDL directories for the source-scanning checks."""
        return list(self.ddl_dir) if self.ddl_dir else [Path("db/schema")]

    @property
    def git_group_enabled(self) -> bool:
        """Whether the git-accompaniment group runs at all.

        ``--staged`` on its own still enters the group (and passes trivially),
        which is the pre-0.40.0 behaviour — except when ``--idempotent`` is also
        set, where #181 routes ``--staged`` to the idempotency scope instead.
        """
        return bool(
            self.check_drift
            or self.require_migration
            or self.require_migration_bodies
            or self.require_grant_migration
            or (self.staged and not self.idempotent)
        )


def validate_flag_dependencies(opts: ValidateOptions) -> None:
    """Reject modifier flags whose check was not requested.

    Raises:
        ConfigurationError: a modifier is on with none of its checks.
    """
    on = {
        "--check-body": opts.check_body,
        "--check-signatures": opts.check_signatures,
        "--check-body-views": opts.check_body_views,
        "--check-body-replay": opts.check_body_replay,
        "--show-diff": opts.show_diff,
    }
    for modifier, required in _FLAG_DEPENDENCIES:
        if not on[modifier]:
            continue
        if any(on[req] for req in required):
            continue
        if len(required) == 1:
            raise ConfigurationError(f"{modifier} requires {required[0]}")
        raise ConfigurationError(
            f"{modifier} requires {', '.join(required[:-1])}, or {required[-1]}"
        )


# ---------------------------------------------------------------------------
# Git-accompaniment group
# ---------------------------------------------------------------------------


def _run_git_group(opts: ValidateOptions, ctx: ValidationContext) -> CheckOutcome:
    """Run every requested git sub-check and report them together.

    Before 0.40.0 this block aggregated correctly in text mode but raised
    ``typer.Exit(1)`` on the first failure in JSON mode, so a failing drift
    check meant accompaniment and grant never ran. Both modes now run all
    three and report once.
    """
    from confiture.cli.git_validation import (
        validate_git_drift,
        validate_git_flags_in_repo,
        validate_grant_accompaniment,
        validate_migration_accompaniment,
    )

    # NotAGitRepositoryError (GIT_002 → exit 7) propagates to fail().
    validate_git_flags_in_repo()

    # ARCH-L1: --staged is only meaningful for the grant-accompaniment check.
    # Drift and migration accompaniment compare committed refs (base_ref →
    # HEAD); diffing the staged index for them is not implemented.
    target_ref = "HEAD"

    requested: list[str] = []
    results: dict[str, dict[str, Any]] = {}
    failed: list[str] = []

    if opts.check_drift:
        requested.append("drift")
        try:
            drift_result = validate_git_drift(
                env=opts.git_env,
                base_ref=ctx.effective_base_ref,
                target_ref=target_ref,
                console=console,
                format_output=opts.format_output,
            )
        except Exception as e:
            raise GitError(f"Drift check failed: {e}") from e
        results["drift"] = drift_result
        if not drift_result.get("passed"):
            failed.append("drift")

    if opts.require_migration or opts.require_migration_bodies:
        requested.append("accompaniment")
        try:
            acc_result = validate_migration_accompaniment(
                env=opts.git_env,
                base_ref=ctx.effective_base_ref,
                target_ref=target_ref,
                console=console,
                format_output=opts.format_output,
                check_bodies=opts.require_migration_bodies,
            )
        except Exception as e:
            raise GitError(f"Accompaniment check failed: {e}") from e
        results["accompaniment"] = acc_result
        if not acc_result.get("is_valid"):
            failed.append("accompaniment")

    if opts.require_grant_migration:
        # Historically the envelope lists grant_accompaniment whenever it was
        # *requested*, including when --allow-grant-only suppresses the run.
        # Kept verbatim: the list means "asked for", and --allow-grant-only is
        # documented as suppressing the failure, not the request.
        requested.append("grant_accompaniment")
        if not opts.allow_grant_only:
            try:
                grant_result = validate_grant_accompaniment(
                    base_ref=ctx.effective_base_ref,
                    target_ref=target_ref,
                    staged_only=opts.staged,
                    console=console,
                    format_output=opts.format_output,
                    grant_dir=_resolve_grant_dir(opts, ctx),
                    migrations_dir=str(opts.migrations_dir),
                )
            except Exception as e:
                raise GitError(f"Grant accompaniment check failed: {e}") from e
            results["grant_accompaniment"] = grant_result
            if not grant_result.get("is_valid"):
                failed.append("grant_accompaniment")

    passed = not failed
    if not opts.json_mode:
        if passed:
            console.print("[green]✅ All git validation checks passed[/green]")
        return CheckOutcome("git_accompaniment", passed=passed)

    if passed:
        payload: dict[str, Any] = {"status": "passed", "checks": requested}
    elif len(requested) == 1:
        # Byte-identical to the 0.39.0 single-check failure envelope.
        payload = {"status": "failed", "check": requested[0], **results[requested[0]]}
    else:
        payload = {
            "status": "failed",
            "checks": requested,
            "failed": failed,
            "results": results,
        }
    return CheckOutcome("git_accompaniment", passed=passed, payload=payload)


def _resolve_grant_dir(opts: ValidateOptions, ctx: ValidationContext) -> str:
    """The configured grant sweep directory, or the documented default.

    A "broad coverage" gate that ignored a non-default ``migration.grant_dir``
    would be a trap, so the config wins when it names one.
    """
    if not (opts.config and Path(opts.config).exists()):
        return "db/7_grant"
    try:
        cfg_data = ctx.config_data
        configured = (
            cfg_data.get("migration", {}).get("grant_dir") if isinstance(cfg_data, dict) else None
        )
    except Exception:  # noqa: BLE001 — fall back to the default
        return "db/7_grant"
    return str(configured) if configured else "db/7_grant"


# ---------------------------------------------------------------------------
# Report modes
# ---------------------------------------------------------------------------


def _run_list_patterns(opts: ValidateOptions, _ctx: ValidationContext) -> CheckOutcome:
    from confiture.cli.commands.migrate_analysis import _pattern_catalog_payload

    return CheckOutcome("list_patterns", passed=True, payload=_pattern_catalog_payload(opts))


def _run_list_unmigrated_bodies(opts: ValidateOptions, ctx: ValidationContext) -> CheckOutcome:
    from confiture.cli.git_validation import report_unmigrated_bodies

    body_result = report_unmigrated_bodies(
        env=opts.git_env,
        base_ref=ctx.effective_base_ref,
        target_ref="HEAD",
        console=console,
        format_output=opts.format_output,
    )
    payload = {"check": "unmigrated_bodies", **body_result} if opts.json_mode else None
    # Report-only by contract (#178): sizes the backlog, never fails.
    return CheckOutcome("unmigrated_bodies", passed=True, payload=payload)


# ---------------------------------------------------------------------------
# Static checks
# ---------------------------------------------------------------------------


def _run_acls(opts: ValidateOptions, ctx: ValidationContext) -> CheckOutcome:
    from confiture.cli.formatters.validate_formatter import render_acl_coverage
    from confiture.core.validation.acl_coverage import check_acl_coverage

    report = check_acl_coverage(opts.migrations_dir, opts.config, ctx)
    payload = render_acl_coverage(report, json_mode=opts.json_mode)
    return CheckOutcome("acl_coverage", passed=not report.has_errors, payload=payload)


def _run_ownership_coverage(opts: ValidateOptions, ctx: ValidationContext) -> CheckOutcome:
    from confiture.cli.formatters.validate_formatter import render_ownership_coverage
    from confiture.core.validation.ownership_coverage import check_ownership_coverage

    report = check_ownership_coverage(opts.migrations_dir, opts.config, ctx)
    payload = render_ownership_coverage(report, json_mode=opts.json_mode)
    return CheckOutcome("ownership_coverage", passed=not report.has_errors, payload=payload)


def _run_function_uniqueness(opts: ValidateOptions, ctx: ValidationContext) -> CheckOutcome:
    from confiture.cli.formatters.validate_formatter import render_function_uniqueness
    from confiture.core.validation.function_uniqueness import check_function_uniqueness

    report = check_function_uniqueness(opts.scan_paths, opts.config, ctx)
    payload = render_function_uniqueness(report, json_mode=opts.json_mode)
    return CheckOutcome("function_uniqueness", passed=not report.has_violations, payload=payload)


def _run_security_definer(opts: ValidateOptions, ctx: ValidationContext) -> CheckOutcome:
    from confiture.cli.formatters.validate_formatter import render_security_definer

    if opts.secdef_against_db:
        from confiture.core.validation.security_definer import check_security_definer_live

        report = check_security_definer_live(
            config_path=opts.config,
            schemas=opts.schemas,
            ssh_via=opts.ssh_via,
            ctx=ctx,
        )
    else:
        from confiture.core.validation.security_definer import check_security_definer

        report = check_security_definer(opts.scan_paths, opts.config, ctx)

    payload = render_security_definer(report, json_mode=opts.json_mode)
    if opts.emit_remediation is not None and report.has_violations:
        from confiture.core.validation.security_definer import emit_remediation as _emit

        count = _emit(report, opts.emit_remediation)
        console.print(
            f"[dim]Remediation script ({count} statement(s)) written to "
            f"{opts.emit_remediation}[/dim]"
        )
    return CheckOutcome("security_definer", passed=not report.has_errors, payload=payload)


def _run_imports(opts: ValidateOptions, _ctx: ValidationContext) -> CheckOutcome:
    from confiture.cli.formatters.validate_formatter import render_import_check
    from confiture.core.import_checker import ImportChecker

    result = ImportChecker(opts.migrations_dir).check()
    payload = render_import_check(result, json_mode=opts.json_mode)
    return CheckOutcome("imports", passed=result.success, payload=payload)


# ---------------------------------------------------------------------------
# Database-backed checks
# ---------------------------------------------------------------------------


def _run_live_drift(opts: ValidateOptions, ctx: ValidationContext) -> CheckOutcome:
    from confiture.cli.formatters.validate_formatter import render_live_drift
    from confiture.core.validation.live_drift import check_live_drift

    report = check_live_drift(opts.config, opts.schema_file, ctx)
    payload = render_live_drift(report, json_mode=opts.json_mode)
    return CheckOutcome("live_drift", passed=not report.has_critical_drift, payload=payload)


def _run_signatures(opts: ValidateOptions, ctx: ValidationContext) -> CheckOutcome:
    from confiture.cli.formatters.validate_formatter import render_signature_drift
    from confiture.core.validation.signature_drift import check_signature_drift

    result = check_signature_drift(
        config_path=opts.config,
        schema_file=opts.schema_file,
        schemas=opts.schemas,
        check_body=opts.check_body,
        ssh_via=opts.ssh_via,
        ctx=ctx,
    )
    if not opts.json_mode:
        if result.auto_built:
            console.print("[dim]  (schema auto-built from DDL files)[/dim]")
        if result.ssh_target:
            console.print(f"[dim]  (connecting via SSH tunnel to {result.ssh_target})[/dim]")
    payload = render_signature_drift(
        result.drift_report,
        result.body_report,
        json_mode=opts.json_mode,
        show_diff=opts.show_diff,
    )
    return CheckOutcome(
        "function_signature_drift", passed=not result.has_any_drift, payload=payload
    )


def _run_body_views(opts: ValidateOptions, ctx: ValidationContext) -> CheckOutcome:
    from confiture.cli.formatters.validate_formatter import render_view_drift
    from confiture.core.validation.view_drift import check_view_drift

    result = check_view_drift(
        config_path=opts.config,
        schema_file=opts.schema_file,
        schemas=opts.schemas,
        ssh_via=opts.ssh_via,
        scratch_url=opts.scratch_url,
        ctx=ctx,
    )
    if not opts.json_mode:
        if result.auto_built:
            console.print("[dim]  (schema auto-built from DDL files)[/dim]")
        if result.ssh_target:
            console.print(f"[dim]  (connecting via SSH tunnel to {result.ssh_target})[/dim]")
    payload = render_view_drift(
        result.view_report, json_mode=opts.json_mode, show_diff=opts.show_diff
    )
    return CheckOutcome("view_body_drift", passed=not result.has_drift, payload=payload)


def _run_body_replay(opts: ValidateOptions, ctx: ValidationContext) -> CheckOutcome:
    from confiture.cli.formatters.validate_formatter import render_replay_drift
    from confiture.core.validation.replay_drift import check_replay_drift

    result = check_replay_drift(
        config_path=opts.config,
        migrations_dir=opts.migrations_dir,
        schemas=opts.schemas,
        ssh_via=opts.ssh_via,
        scratch_url=opts.scratch_url,
        ctx=ctx,
    )
    if not opts.json_mode and result.ssh_target:
        console.print(f"[dim]  (connecting via SSH tunnel to {result.ssh_target})[/dim]")
    payload = render_replay_drift(
        result.body_report, json_mode=opts.json_mode, show_diff=opts.show_diff
    )
    return CheckOutcome("replay_body_drift", passed=not result.has_drift, payload=payload)


# ---------------------------------------------------------------------------
# Migrations-directory checks (idempotency + naming)
# ---------------------------------------------------------------------------


def _require_migrations_dir(opts: ValidateOptions) -> None:
    if not opts.migrations_dir.exists():
        raise ConfigurationError(
            f"Migrations directory not found: {opts.migrations_dir.absolute()}",
            error_code="CONFIG_004",
        )


def _run_idempotent(opts: ValidateOptions, _ctx: ValidationContext) -> CheckOutcome:
    _require_migrations_dir(opts)
    passed, payload = _validate_idempotency(
        opts.migrations_dir,
        opts.format_output,
        strict_cor=opts.strict_cor,
        base_ref=opts.idempotent_base_ref,
        staged=opts.staged,
    )
    return CheckOutcome("idempotent", passed=passed, payload=payload)


def _run_naming(opts: ValidateOptions, _ctx: ValidationContext) -> CheckOutcome:
    """The default mode: orphaned-file detection, optionally fixing names."""
    from confiture.cli.formatters.validate_formatter import render_naming
    from confiture.core.migrator import Migrator, find_duplicate_migration_versions

    _require_migrations_dir(opts)

    # Migrator needs a connection object for construction only — every method
    # used here reads the filesystem.
    from unittest.mock import Mock

    migrator = Migrator(connection=Mock())
    duplicate_versions = find_duplicate_migration_versions(opts.migrations_dir)
    orphaned_files = migrator.find_orphaned_sql_files(opts.migrations_dir)

    fixed: dict[str, Any] | None = None
    if orphaned_files and opts.fix_naming and not duplicate_versions:
        fixed = migrator.fix_orphaned_sql_files(opts.migrations_dir, dry_run=opts.dry_run)

    payload = render_naming(
        duplicate_versions=duplicate_versions,
        orphaned_files=orphaned_files,
        fixed=fixed,
        json_mode=opts.json_mode,
        dry_run=opts.dry_run,
    )
    return CheckOutcome("naming", passed=not duplicate_versions, payload=payload)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def build_registry(opts: ValidateOptions) -> list[ValidationCheck]:
    """The ordered descriptor list for one invocation.

    Order is the pre-0.40.0 source order of the ``if <flag>: … return`` chain.
    The naming check is last and enabled only when nothing else is — it is the
    command's default mode, not a composable check, and that is exactly how it
    behaved when every other branch returned before reaching it.
    """
    checks: list[ValidationCheck] = [
        ValidationCheck(
            flag="--list-patterns",
            name="list_patterns",
            enabled=opts.list_patterns,
            run=lambda ctx: _run_list_patterns(opts, ctx),
            report_only=True,
            exclusive=True,
        ),
        ValidationCheck(
            flag="--list-unmigrated-bodies",
            name="unmigrated_bodies",
            enabled=opts.list_unmigrated_bodies,
            run=lambda ctx: _run_list_unmigrated_bodies(opts, ctx),
            needs_git=True,
            report_only=True,
            exclusive=True,
        ),
        ValidationCheck(
            flag="--check-drift/--require-migration/--require-grant-migration",
            name="git_accompaniment",
            enabled=opts.git_group_enabled,
            run=lambda ctx: _run_git_group(opts, ctx),
            needs_git=True,
        ),
        ValidationCheck(
            flag="--check-acls",
            name="acl_coverage",
            enabled=opts.check_acls,
            run=lambda ctx: _run_acls(opts, ctx),
        ),
        ValidationCheck(
            flag="--check-ownership-coverage",
            name="ownership_coverage",
            enabled=opts.check_ownership_coverage,
            run=lambda ctx: _run_ownership_coverage(opts, ctx),
        ),
        ValidationCheck(
            flag="--check-function-uniqueness",
            name="function_uniqueness",
            enabled=opts.check_function_uniqueness,
            run=lambda ctx: _run_function_uniqueness(opts, ctx),
        ),
        ValidationCheck(
            flag="--check-security-definer",
            name="security_definer",
            enabled=opts.check_security_definer,
            run=lambda ctx: _run_security_definer(opts, ctx),
            needs_db=opts.secdef_against_db,
        ),
        ValidationCheck(
            flag="--check-imports",
            name="imports",
            enabled=opts.check_imports,
            run=lambda ctx: _run_imports(opts, ctx),
        ),
        ValidationCheck(
            flag="--check-live-drift",
            name="live_drift",
            enabled=opts.check_live_drift,
            run=lambda ctx: _run_live_drift(opts, ctx),
            needs_db=True,
        ),
        ValidationCheck(
            flag="--check-signatures",
            name="function_signature_drift",
            enabled=opts.check_signatures,
            run=lambda ctx: _run_signatures(opts, ctx),
            needs_db=True,
        ),
        ValidationCheck(
            flag="--check-body-views",
            name="view_body_drift",
            enabled=opts.check_body_views,
            run=lambda ctx: _run_body_views(opts, ctx),
            needs_db=True,
        ),
        ValidationCheck(
            flag="--check-body-replay",
            name="replay_body_drift",
            enabled=opts.check_body_replay,
            run=lambda ctx: _run_body_replay(opts, ctx),
            needs_db=True,
        ),
        ValidationCheck(
            flag="--idempotent",
            name="idempotent",
            enabled=opts.idempotent,
            run=lambda ctx: _run_idempotent(opts, ctx),
        ),
    ]
    checks.append(
        ValidationCheck(
            flag="(default)",
            name="naming",
            enabled=not any(c.enabled for c in checks),
            run=lambda ctx: _run_naming(opts, ctx),
        )
    )
    return checks
