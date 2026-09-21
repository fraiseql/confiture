"""Which lint rules a run applies, and the findings of the rules that read a tree of files.

``confiture lint`` resolves ``--select`` / ``--ignore`` and the three legacy flags
into one set of codes (#150), turns that set into ``LintConfig``'s switches, and
runs the rules that read the DDL tree or the migrations tree rather than the
built schema — ``replica_001``, ``sec_002``, ``func_001``, ``own_001``/``own_002``,
``tree_001``–``tree_004``. Each such rule reads the files the environment's build
reads (LINT-08), and a rule whose configuration is absent has nothing to report.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from confiture.config.environment import DEFAULT_STATUS_WORDS, Environment
from confiture.core import builder as _core_builder
from confiture.core.connection import load_config as _lc
from confiture.core.linting.baseline import Baseline, BaselineDiff, identity
from confiture.core.linting.gate import (
    Threshold,
)
from confiture.core.linting.inventory import label_for
from confiture.core.linting.libraries.generate import TREE_RULE_CODES, tree_violations
from confiture.core.linting.libraries.security_definer import Sec002SecurityDefinerSearchPath
from confiture.core.linting.rule_registry import (
    ARTEFACT_CODES,
    DEFAULT_SELECTOR,
    LINT_RULES,
    resolve_selection,
)
from confiture.core.linting.schema_linter import (
    LintConfig as LinterConfig,
)
from confiture.core.linting.schema_linter import LintReport as LinterReport
from confiture.core.linting.schema_linter import (
    LintViolation,
)
from confiture.core.linting.schema_linter import (
    RuleSeverity as _RS,
)
from confiture.core.validation.config_loaders import load_security_lint as _lsl
from confiture.exceptions import ConfiturError


def severity_escalations(env: str, project_dir: Path, selected: frozenset[str]) -> dict[str, str]:
    """Selected rules whose configured severity is above the registry's declaration.

    Reachability that ignored these would tell a project that has escalated
    ``sec_002`` to ``error`` that its ``--fail-on error`` gate cannot fire, one
    sentence before it fires.
    """
    escalations: dict[str, str] = {}
    if "sec_002" in selected:
        cfg = _security_lint_config(env, project_dir)
        if cfg is not None and cfg.severity == "error":
            escalations["sec_002"] = "error"
    if "replica_001" in selected:
        has_replicas, bypass = _replica_policy(env, project_dir)
        if has_replicas and not bypass:
            escalations["replica_001"] = "error"
    return escalations


def linter_config(
    selected: frozenset[str], threshold: Threshold, server_url: str | None = None
) -> LinterConfig:
    """``LintConfig``'s coarse switches, from the exact set of selected codes.

    Its two ``fail_on_*`` booleans decide nothing — the gate does — so they are
    derived from the threshold rather than carried alongside it.
    """
    return LinterConfig(
        enabled=True,
        fail_on_error=threshold.rank <= Threshold.ERROR.rank,
        fail_on_warning=threshold.rank <= Threshold.WARNING.rank,
        check_naming="naming_001" in selected or "naming_002" in selected,
        check_primary_keys="pk_001" in selected,
        check_documentation=any(code.startswith("doc_") for code in selected),
        check_restatements="doc_005" in selected,
        check_duplicates=any(code in selected for code in ("build_001", "build_002")),
        check_references="build_003" in selected,
        check_security="sec_001" in selected,
        check_tenant_isolation="tenant_001" in selected,
        check_acl_coverage="acl_001" in selected,
        check_qualification="qual_001" in selected,
        check_qualification_relations="qual_002" in selected,
        check_bodies="body_001" in selected,
        check_body_warnings="body_002" in selected,
        check_body_classes=selected & ARTEFACT_CODES,
        server_url=server_url,
    )


def tree_rule_findings(
    selected: frozenset[str],
    env: str,
    project_dir: Path,
    migrations_dir: Path,
    overrides_dir: Path | None = None,
) -> list[LintViolation]:
    """The rules that read a tree of files rather than the built schema.

    They are findings like any other — same report, same baseline, same gate —
    and they name their files the way the rest of the report does. Every one of
    them is selected by code here rather than through ``LintConfig``'s coarser
    switches, because they run after ``keep_selected_rules`` has already passed.
    """
    findings: list[LintViolation] = []
    if "replica_001" in selected:
        findings += _replica_findings(env, project_dir, migrations_dir)
    if "sec_002" in selected:
        findings += _security_definer_findings(env, project_dir)
    if "func_001" in selected:
        findings += _function_uniqueness_findings(env, project_dir)
    if selected & {"own_001", "own_002"}:
        findings += _ownership_findings(selected, env, project_dir, migrations_dir)
    if selected & set(TREE_RULE_CODES):
        findings += _ddl_tree_findings(selected, env, project_dir, overrides_dir)
    return [project_relative(v, project_dir) for v in findings]


def _under(path: Path | None, project_dir: Path) -> Path | None:
    """A directory an operator named, read relative to ``--project-dir``.

    ``--migrations-dir`` and ``--overrides-dir`` are project-relative like
    ``--baseline`` is; three rules read the first of them and they must all read
    the same directory.
    """
    if path is None or path.is_absolute():
        return path
    return project_dir / path


def env_ddl_files(env: str, project_dir: Path) -> tuple[list[Path], list[Path]]:
    """``(the files the build reads, the roots it reads them from)``.

    One answer for every rule that walks the DDL tree, so none of them reports a
    file the environment's ``exclude_dirs`` or per-directory ``exclude`` globs
    keep out of the build (LINT-08). A project whose config will not load has no
    build to describe, so it has no tree to lint.
    """
    try:
        builder = _core_builder.SchemaBuilder(env=env, project_dir=project_dir)
        return builder.find_sql_files(), list(builder.include_dirs)
    except (ConfiturError, OSError):
        return [], []


def _ddl_tree_findings(
    selected: frozenset[str], env: str, project_dir: Path, overrides_dir: Path | None
) -> list[LintViolation]:
    """#111: tree_001–tree_004 over the DDL file tree the environment builds."""
    files, roots = env_ddl_files(env, project_dir)
    # A config that will not load has already left `files` empty, so the
    # fallback here is a spelling of "nothing to report", not a second default.
    lint_settings = _env_block(env, project_dir, "lint")
    return tree_violations(
        files,
        selected=selected,
        schema_dirs=roots,
        overrides_dir=_under(overrides_dir, project_dir),
        status_words=(
            DEFAULT_STATUS_WORDS if lint_settings is None else lint_settings.status_words
        ),
    )


def _function_uniqueness_findings(env: str, project_dir: Path) -> list[LintViolation]:
    """#136: func_001 — one definition per function signature across the DDL tree."""
    # Reason: CLI start-up: the rule is opt-in, so its import is deferred until it is selected
    from confiture.core.linting.libraries.functions import Func001FunctionUniqueness

    coverage = _env_block(env, project_dir, "function_coverage")
    if coverage is None or not coverage.enabled:
        return []
    files, roots = env_ddl_files(env, project_dir)
    return Func001FunctionUniqueness(coverage=coverage).check(files or roots)


def _ownership_findings(
    selected: frozenset[str], env: str, project_dir: Path, migrations_dir: Path
) -> list[LintViolation]:
    """#124/#137: own_001 and own_002 over the migrations tree."""
    # Reason: CLI start-up: the rules are opt-in, so their import is deferred until one is selected
    from confiture.core.linting.libraries.ownership import (
        Own001OwnershipCoverage,
        Own002BareAlterOwner,
    )

    expectation = _env_block(env, project_dir, "ownership")
    if expectation is None:
        return []
    resolved = _under(migrations_dir, project_dir)
    findings: list[LintViolation] = []
    if "own_001" in selected:
        findings += Own001OwnershipCoverage(expectation=expectation).check(resolved)
    if "own_002" in selected:
        findings += Own002BareAlterOwner(expectation=expectation).check(resolved)
    return findings


def _env_block(env: str, project_dir: Path, attribute: str) -> Any:
    """One optional block of the environment config, or ``None`` when it is absent.

    A rule whose configuration is missing has nothing to report — the same
    contract ``_security_lint_config`` and ``_replica_policy`` keep, and the
    reason each of these rules declares a ``requires_config``.
    """
    try:
        return getattr(Environment.load(env, project_dir=project_dir), attribute)
    except (ConfiturError, OSError):
        return None


def project_relative(violation: LintViolation, project_dir: Path) -> LintViolation:
    """A finding names its file the way the rest of the report does."""
    if violation.file_path is None:
        return violation
    return replace(violation, file_path=label_for(Path(violation.file_path), project_dir))


def _replica_findings(env: str, project_dir: Path, migrations_dir: Path) -> list[LintViolation]:
    """#139: replica-aware forward-compatibility lint over the migrations tree.

    A migration-tree check, distinct from the schema lint — but a finding all
    the same, so it joins the report every other rule writes to instead of
    printing itself to the console and deciding its own exit code.
    """
    # Reason: CLI start-up: importing confiture.core.linting.libraries.replica costs ~28 ms at start (importtime, 2026-09-07); deferred until the command runs
    from confiture.core.linting.libraries.replica import Replica001ForwardCompat

    has_replicas, bypass = _replica_policy(env, project_dir)
    return Replica001ForwardCompat(has_replicas=has_replicas, bypass=bypass).check(
        _under(migrations_dir, project_dir)
    )


def _replica_policy(env: str, project_dir: Path) -> tuple[bool, bool]:
    """``(replicas declared, unsafe DDL allowed anyway)`` — what decides replica_001's severity."""
    try:
        _env = Environment.load(env, project_dir=project_dir)
    # Reason: replica config is optional; any failure reading it means 'no replicas'
    except Exception:
        return False, False
    return bool(_env.infrastructure.replicas), _env.migration.allow_unsafe_under_replication


def _security_definer_findings(env: str, project_dir: Path) -> list[LintViolation]:
    """#161: sec_002 — SECURITY DEFINER / search_path over the env's schema DDL.

    Findings join the report, so `lint --format json` carries them and
    `--baseline` can absorb them (LINT-03). They used to print straight to the
    console, which in a machine-output mode meant printing *into* the payload.
    """
    sec_cfg = _security_lint_config(env, project_dir)
    if sec_cfg is None:
        return []
    severity = _RS.ERROR if sec_cfg.severity == "error" else _RS.WARNING
    ddl_paths, roots = env_ddl_files(env, project_dir)
    return Sec002SecurityDefinerSearchPath(
        apply_to=sec_cfg.apply_to, ignore=sec_cfg.ignore, severity=severity
    ).check(ddl_paths or roots or [Path("db/schema")])


def _security_lint_config(env: str, project_dir: Path) -> Any:
    """The env's ``security_lint:`` block, or ``None`` when absent or disabled."""
    try:
        cfg_path = (project_dir or Path.cwd()) / "db" / "environments" / f"{env}.yaml"
        if not cfg_path.exists():
            return None
        cfg = _lsl(_lc(cfg_path), cfg_path, require=False)
    # Reason: security config is optional; any failure reading it means 'defaults'
    except Exception:
        return None
    return cfg if cfg is not None and cfg.enabled else None


def apply_baseline(
    linter_report: LinterReport, *, baseline: Path | None, write: bool, project_dir: Path
) -> Any:
    """Keep only the findings the baseline does not know; write or tighten the file (#219).

    Returns the ``BaselineDiff`` (``None`` without ``--baseline``). ``--write-baseline``
    records every current finding and leaves nothing to report; otherwise findings
    the file knows are dropped from the report, identities no longer found are
    removed from the file (D12), and what remains is new.
    """
    if baseline is None:
        return None

    path = baseline if baseline.is_absolute() else project_dir / baseline
    buckets = (linter_report.errors, linter_report.warnings, linter_report.info)
    current = [v for bucket in buckets for v in bucket]
    if write:
        Baseline.from_violations(current).write(path)
        for bucket in buckets:
            bucket[:] = []
        return BaselineDiff(known=len({identity(v) for v in current}))
    known = Baseline.load(path)
    diff = known.diff(current)
    if diff.fixed:
        known.without(diff.fixed).write(path)
    new_identities = {identity(v) for v in diff.new}
    for bucket in buckets:
        bucket[:] = [v for v in bucket if identity(v) in new_identities]
    return diff


def keep_selected_rules(linter_report: LinterReport, selected: frozenset[str]) -> None:
    """Drop findings whose rule was deselected (#150), in place.

    Only rules the registry knows are filtered. A violation carrying an
    unregistered code — a rule added to the linter without registering it, or a
    consumer's own — is passed through rather than silently swallowed: it could
    not have been selected, and dropping it would turn "I forgot to register my
    rule" into "my rule stopped reporting".
    """

    known = {rule.code for rule in LINT_RULES}
    for bucket in (linter_report.errors, linter_report.warnings, linter_report.info):
        bucket[:] = [v for v in bucket if v.rule_id in selected or v.rule_id not in known]
    # `degraded` is a claim about a rule, so a rule nobody selected makes no
    # claim. The linter reports per family — `check_documentation` is one switch
    # over four codes — so this is where `--select doc_002` narrows it, exactly
    # as it narrows that switch's findings above.
    linter_report.degraded[:] = [
        status
        for status in linter_report.degraded
        if status.code in selected or status.code not in known
    ]


def resolve_lint_rules(
    *,
    select: list[str] | None,
    ignore: list[str] | None,
    replica_safe: bool,
    check_tenant_isolation: bool,
    check_security_definer: bool,
) -> frozenset[str]:
    """The rule codes this invocation applies, legacy flags folded in.

    Each legacy flag means "the defaults *plus* this family", which is what it
    did when it was a branch of its own. Expressing them as selectors keeps one
    dispatch path — the point of #150 — and makes them exactly equivalent to the
    ``--select`` form they are documented as aliasing.

    Raises:
        ConfigurationError: An unknown code or family was named.
    """

    aliases = [
        rule_family
        for enabled, rule_family in (
            (replica_safe, "replica"),
            (check_tenant_isolation, "tenant"),
            (check_security_definer, "security-definer"),
        )
        if enabled
    ]
    effective = list(select or [])
    if aliases:
        # A bare legacy flag keeps the default rules; combined with --select it
        # extends whatever that selected, rather than re-adding the defaults.
        effective = (effective or [DEFAULT_SELECTOR]) + aliases
    return resolve_selection(effective or None, ignore or ())
