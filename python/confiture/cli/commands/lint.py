"""``confiture lint``: the schema linter, its rule selection, gate and baseline."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
from rich.table import Table

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import (
    _convert_linter_report,
    console,
    emit,
    error_console,
    is_json,
)
from confiture.cli.lint_formatter import format_lint_report, save_report
from confiture.cli.markup import verbatim
from confiture.cli.options import (
    ProjectDirOpt,
    env_option,
    format_option,
    migrations_dir_option,
    output_option,
)
from confiture.core.linting import SchemaLinter
from confiture.core.linting.gate import (
    Gate,
    Threshold,
    compute_gate,
    parse_threshold,
    should_fail,
    threshold_from_aliases,
    unrun_reaches,
)
from confiture.core.linting.rule_registry import (
    LEGACY_CODE_ALIASES,
    LINT_RULES,
)
from confiture.core.linting.selection import (
    apply_baseline,
    keep_selected_rules,
    linter_config,
    resolve_lint_rules,
    severity_escalations,
    tree_rule_findings,
)
from confiture.error_codes import FINDINGS, USAGE

FailOnOpt = Annotated[
    str | None,
    typer.Option(
        "--fail-on",
        help="Severity at which the run fails: error (default), warning, info "
        "or never. `--fail-on-error` and `--fail-on-warning` are aliases for "
        "the first two; passing both an alias and this exits 2. When no "
        "selected rule can emit at the threshold, the run says so instead of "
        "passing quietly (#247).",
    ),
]
FailOnErrorOpt = Annotated[
    bool,
    typer.Option("--fail-on-error", help="Alias for `--fail-on error` (default: on)"),
]
FailOnWarningOpt = Annotated[
    bool,
    typer.Option(
        "--fail-on-warning", help="Alias for `--fail-on warning` (default: off, stricter)"
    ),
]
SelectOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--select",
        help="Rules or families to run, comma-separated (#150). `default` means "
        "the rules a plain lint runs, so `--select default,replica` is the "
        "defaults plus one family. Omit to run the defaults. "
        "See `--list-rules`.",
    ),
]
IgnoreOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--ignore",
        help="Rules or families to skip, comma-separated. Applied after --select, "
        "so --ignore always wins.",
    ),
]
BaselineOpt = Annotated[
    Path | None,
    typer.Option(
        "--baseline",
        help="Baseline file (#219): fail only on findings it does not know, print only those, rewrite it when findings disappear",
    ),
]
WriteBaselineOpt = Annotated[
    bool,
    typer.Option(
        "--write-baseline", help="Create or reset the --baseline file from the current findings"
    ),
]
ListRulesOpt = Annotated[
    bool,
    typer.Option(
        "--list-rules",
        help="Print the rule catalogue (code, family, severity, default/opt-in) "
        "and exit 0. Honours --format json.",
    ),
]
ReplicaSafeOpt = Annotated[
    bool,
    typer.Option(
        "--replica-safe",
        help="Deprecated alias for `--select default,replica` (#139). Still "
        "supported; new rules register instead of adding a flag.",
    ),
]
OverridesDirOpt = Annotated[
    Path | None,
    typer.Option(
        "--overrides-dir",
        help="Overrides mirror directory. tree_004 needs it and is skipped without it: "
        "there is no conventional location to guess.",
    ),
]
ServerUrlOpt = Annotated[
    str | None,
    typer.Option(
        "--server-url",
        help="Writable PostgreSQL server the body family builds its scratch "
        "database on. Only the server is used: a throwaway database is created "
        "beside the configured one and dropped again. Defaults to the "
        "environment's own database_url.",
    ),
]
CheckTenantIsolationOpt = Annotated[
    bool,
    typer.Option(
        "--check-tenant-isolation",
        help="Deprecated alias for `--select default,tenant` (tenant_001): flag "
        "function INSERTs missing the FK column a tenant-scoped view requires.",
    ),
]
CheckSecurityDefinerOpt = Annotated[
    bool,
    typer.Option(
        "--check-security-definer",
        help="Deprecated alias for `--select default,security-definer`. Runs "
        "sec_002 over the env's schema DDL: flag SECURITY DEFINER "
        "functions/procedures that do not pin search_path (CVE-2018-1058). "
        "No-op when the config has no `security_lint:` block or "
        "`security_lint.enabled` is false. Default severity is advisory "
        "(warning); set `security_lint.severity: error` to make it a hard gate.",
    ),
]


@cli_boundary
def lint(
    ctx: typer.Context,
    env: str = env_option(),
    project_dir: ProjectDirOpt = Path(),
    format_type: str = format_option("table", "json", "csv"),
    output: Path | None = output_option(
        help="Output file path (default: stdout, only with json/csv)"
    ),
    fail_on: FailOnOpt = None,
    fail_on_error: FailOnErrorOpt = True,
    fail_on_warning: FailOnWarningOpt = False,
    select: SelectOpt = None,
    ignore: IgnoreOpt = None,
    baseline: BaselineOpt = None,
    write_baseline: WriteBaselineOpt = False,
    list_rules: ListRulesOpt = False,
    replica_safe: ReplicaSafeOpt = False,
    migrations_dir: Path = migrations_dir_option(
        help="Migrations directory the migration-tree rules read — replica_001, "
        "own_001, own_002 (default: db/migrations)"
    ),
    overrides_dir: OverridesDirOpt = None,
    server_url: ServerUrlOpt = None,
    check_tenant_isolation: CheckTenantIsolationOpt = False,
    check_security_definer: CheckSecurityDefinerOpt = False,
) -> None:
    """Validate schema against best practices.

    PROCESS:
      Runs the default rule set — naming_001, naming_002, pk_001, doc_001–doc_004,
      build_001, build_002, sec_001, qual_001 — plus whatever `--select` adds.
      `--list-rules` prints the full catalogue with codes and families. Results
      in table, JSON or CSV.

    RULES:
      Select by code or family: `--select pk,naming`, `--select naming_001`,
      `--ignore doc`. `default` means every rule that is on by default, so
      `--select default,replica` is the usual lint plus one opt-in family.
      `--ignore` wins over `--select`; an unknown selector exits 5.

      naming_001, naming_002, pk_001, doc_001–doc_004, build_001, build_002,
      build_003, sec_001, qual_001 — on by default. build_001 is the one that
      emits `error`, so a plain lint fails on a duplicate definition.

      Opt-in, each needing its configuration as well as its selector:
      acl_001 (`acls.lint_enabled: true`), tenant_001, replica_001, sec_002
      (`security_lint.enabled: true`), func_001 (`function_coverage.enabled:
      true`), own_001 / own_002 (an `ownership:` block), qual_002 (relations and
      types created without a schema), doc_005 (a COMMENT that says only what
      the object's own name says), and tree_001–tree_004, the DDL file-tree
      rules — `--select tree`; tree_004 also needs `--overrides-dir`.
      `--list-rules` prints all of it with the configuration each needs.

    EXAMPLES:
      confiture lint
        ↳ Lint local environment, display results as table

      confiture lint --list-rules
        ↳ Print every rule with its code, family and default state

      confiture lint --select pk,naming
        ↳ Run only the primary-key and naming families

      confiture lint --ignore doc
        ↳ The default rules, minus doc_001

      confiture lint --select default,qual_002
        ↳ Also report relations and types created without a schema

      confiture lint --select default,doc_005
        ↳ Also report a COMMENT that says only what the object's name says

      confiture lint --env production
        ↳ Lint production environment

      confiture lint --format json --output report.json
        ↳ Save linting report to JSON file

      confiture lint --fail-on warning
        ↳ Fail the run on warnings as well as errors (--fail-on-warning is an alias)

      confiture lint --fail-on never
        ↳ Report every finding and never fail — a setting neither alias can express

    RELATED:
      confiture build       - Build schema from DDL files
      confiture migrate up  - Apply migrations
      confiture schema-to-schema - Compare and sync schemas

    OPTIONS:
      CORE: --env, --format, --output
        What to lint and how to report results

      SEVERITY: --fail-on (error | warning | info | never)
        The one threshold that decides the exit code. --fail-on-error and
        --fail-on-warning are aliases; passing both an alias and --fail-on
        exits 2. A threshold no selected rule can reach is reported, not
        obeyed quietly.
    """
    try:
        if list_rules:
            _emit_rule_catalogue(format_type, output)
            return
        if write_baseline and baseline is None:
            error_console.print("[red]❌ Error: --write-baseline requires --baseline <file>[/red]")
            raise typer.Exit(USAGE)
        threshold = _resolve_threshold(
            ctx, fail_on=fail_on, fail_on_error=fail_on_error, fail_on_warning=fail_on_warning
        )
        # One selection, resolved once (#150). The three per-rule flags are
        # aliases over it rather than branches further down: each adds its
        # family to the defaults.
        selected = resolve_lint_rules(
            select=select,
            ignore=ignore,
            replica_safe=replica_safe,
            check_tenant_isolation=check_tenant_isolation,
            check_security_definer=check_security_definer,
        )
        config = linter_config(selected, threshold, server_url)
        if format_type == "table":
            # The banner is for humans; in json/csv mode stdout is the payload alone.
            console.print(f"[cyan]🔍 Linting schema for environment: {verbatim(env)}[/cyan]")
        linter = SchemaLinter(env=env, project_dir=project_dir, config=config)
        linter_report = linter.lint()
        # LintConfig's switches are coarser than the rule codes — `check_naming`
        # covers naming_001 *and* naming_002 — so `--select naming_001` needs a
        # second pass over the findings.
        keep_selected_rules(linter_report, selected)
        for violation in tree_rule_findings(
            selected, env, project_dir, migrations_dir, overrides_dir
        ):
            linter_report.add_violation(violation)
        baseline_diff = apply_baseline(
            linter_report, baseline=baseline, write=write_baseline, project_dir=project_dir
        )
        gate = compute_gate(
            threshold=threshold,
            selected=selected,
            escalations=severity_escalations(env, project_dir, selected),
            baseline_active=baseline_diff is not None,
        )
        report = _convert_linter_report(
            linter_report,
            schema_name=env,
            baseline=None if baseline_diff is None else baseline_diff.summary(),
            gate=gate.to_dict(),
        )
        if format_type == "json":
            emit(report.to_dict(), output, console)
        elif format_type == "table":
            format_lint_report(report, format_type="table", console=console)
        else:
            formatted = format_lint_report(report, format_type="csv", console=console)
            if output:
                save_report(report, output)
                console.print(f"[green]✅ Report saved to: {verbatim(output.absolute())}[/green]")
            else:
                # print(), not console.print(): Rich wraps long lines at the
                # terminal width, which breaks a CSV row.
                print(formatted)

        _print_gate_notice(gate, format_type)
        if baseline_diff is not None:
            _print_baseline_note(baseline_diff, format_type, wrote=write_baseline)
        found = [v.severity.value for v in report.violations]
        new_since_baseline = baseline_diff is not None and bool(baseline_diff.new)
        # A rule that did not run has established nothing, so it is not a pass:
        # the gate reads the severity its registry entry declares (#245).
        unrun = unrun_reaches([s.code for s in linter_report.skipped], threshold)
        if should_fail(found, threshold) or new_since_baseline or unrun:
            raise typer.Exit(FINDINGS)  # success-signal: lint found violations
    except typer.Exit:
        raise
    except FileNotFoundError as e:
        if not is_json(format_type):
            console.print("\n💡 Tip: Make sure schema files exist in db/schema/")
        fail(e, json_mode=is_json(format_type), output_file=output)
    # Reason: lint's --output is its report path; the boundary cannot know that, so lint routes the envelope itself
    except Exception as e:
        # The one error boundary: an envelope in JSON mode, the Rich rendering otherwise.
        fail(e, json_mode=is_json(format_type), output_file=output)


def _passed_explicitly(ctx: typer.Context, name: str) -> bool:
    """Whether the operator typed this option, rather than inheriting its default.

    Compared by member name: Typer vendors its own click, so the
    ``ParameterSource`` a Typer context returns is not the ``click.core`` one
    and an identity test silently answers "no" for every option.
    """
    source = ctx.get_parameter_source(name)
    return source is not None and source.name == "COMMANDLINE"


def _resolve_threshold(
    ctx: typer.Context,
    *,
    fail_on: str | None,
    fail_on_error: bool,
    fail_on_warning: bool,
) -> Threshold:
    """The one severity that decides this run's exit code.

    ``--fail-on-error`` / ``--fail-on-warning`` are aliases for two of
    ``--fail-on``'s four values, so passing both a threshold and an alias states
    the gate twice — possibly two different ways. That is a usage error, not a
    precedence puzzle to resolve silently.
    """
    given_aliases = [
        flag
        for flag, name in (
            ("--fail-on-error", "fail_on_error"),
            ("--fail-on-warning", "fail_on_warning"),
        )
        if _passed_explicitly(ctx, name)
    ]
    if fail_on is None:
        return threshold_from_aliases(fail_on_error=fail_on_error, fail_on_warning=fail_on_warning)
    if given_aliases:
        error_console.print(
            f"[red]❌ Error: --fail-on and {verbatim(', '.join(given_aliases))} both set the gate; "
            "pass one[/red]"
        )
        raise typer.Exit(USAGE)
    return parse_threshold(fail_on)


def _print_gate_notice(gate: Gate, format_type: str) -> None:
    """Say, on the summary, when nothing this run selected could have failed it.

    A threshold no selected rule can reach passes whatever the findings: under
    ``--fail-on-error`` with no rule emitting at ``error``, real findings sit
    behind a green tick (#247). ``--fail-on never`` is the same fact deliberately
    chosen, so it is stated rather than warned about.
    """
    if format_type != "table" or gate.reachable or gate.reason is None:
        return
    style = "dim" if gate.threshold is Threshold.NEVER else "yellow"
    console.print(f"\n[{style}]{verbatim(gate.reason)}[/{style}]")


def _print_baseline_note(diff: Any, format_type: str, *, wrote: bool) -> None:
    """One human line about the baseline — only when something happened, never in JSON/CSV."""
    if format_type != "table":
        return
    if wrote:
        console.print(
            f"[green]✅ Baseline written: {verbatim(diff.known)} finding(s) recorded[/green]"
        )
    elif diff.new or diff.fixed:
        console.print(
            f"[cyan]Baseline: {verbatim(diff.known)} known, {len(diff.new)} new, "
            f"{len(diff.fixed)} fixed{verbatim(' (file tightened)' if diff.fixed else '')}[/cyan]"
        )


def _emit_rule_catalogue(format_type: str, output: Path | None) -> None:
    """Print the rule registry: `confiture lint --list-rules`.

    A report mode — it never consults the schema and always exits 0, so it works
    in a project that does not lint cleanly (or at all).
    """

    if is_json(format_type):
        emit(
            {
                "version": "1",
                "status": "ok",
                "rules": [rule.to_dict() for rule in LINT_RULES],
                "hints": [],
            },
            output,
            console,
        )
        return

    table = Table(title="confiture lint rules", show_lines=False)
    table.add_column("Code", style="cyan")
    table.add_column("Family", style="magenta")
    table.add_column("Severity")
    table.add_column("Default")
    table.add_column("Description")
    for rule in LINT_RULES:
        table.add_row(
            rule.code,
            rule.family,
            rule.severity,
            "on" if rule.default_on else "opt-in",
            rule.title + (f" (needs {rule.requires_config})" if rule.requires_config else ""),
        )
    console.print(table)
    console.print(
        "\n[dim]Select with --select <family|code>[,…]; skip with --ignore. "
        "`default` selects every rule marked on.[/dim]"
    )
    aliases = ", ".join(
        f"{old.upper()} → {new}" for old, new in sorted(LEGACY_CODE_ALIASES.items())
    )
    console.print(f"[dim]Deprecated selectors, accepted for one minor: {verbatim(aliases)}.[/dim]")
