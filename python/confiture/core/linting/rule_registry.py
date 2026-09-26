"""The catalogue of rules ``confiture lint`` can run, and how to select them (#150).

A rule is selected by its code or its family, never by a flag of its own:
per-rule flags multiply naming styles and give no way to *turn a rule off*.

This module is the single backing store: :func:`resolve_selection` turns
``--select`` / ``--ignore`` into the exact set of rule codes a run will apply,
``lint --list-rules`` enumerates :data:`LINT_RULES`, and the three legacy flags
are re-expressed as ``--select default,<family>`` rather than as branches in the
command body.

**Only rules that can actually emit a violation are listed**, and every switch
``LintConfig`` carries belongs to one of them: a switch with no rule behind it
would dispatch work that nothing reports.
``tests/unit/linting/test_every_switch_has_a_rule.py`` is what keeps the
catalogue and the dispatch agreeing in that direction, as
``test_every_rule_is_registered.py`` does in the other.
"""

from __future__ import annotations

import textwrap
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from confiture.exceptions import ConfigurationError

#: Selector meaning "everything that runs by default". Not a family — it exists
#: so the legacy flags stay expressible: ``--replica-safe`` is exactly
#: ``--select default,replica``, i.e. the usual lint *plus* one family.
DEFAULT_SELECTOR = "default"

#: The notice a file pglast rejected produces. Named here rather than beside its
#: constructor because two modules need it and one of them (``schema_linter``)
#: cannot import the other without a cycle.
UNPARSEABLE_RULE_ID = "UNPARSEABLE"

#: The code each class of ``plpgsql_check`` finding is reported under (#354).
#: ``body_001`` keeps "the body raises on its first call"; each artefact of how the
#: analysis is done is a code of its own, so a baseline entry for one never absorbs
#: the other and ``--select`` / ``--ignore`` choose between them.
BODY_CLASS_CODES: dict[str, str] = {
    "real": "body_001",
    "temp_table": "body_003",
    "record": "body_004",
    "dblink": "body_005",
}

#: The ``body`` codes that are artefacts rather than failures.
ARTEFACT_CODES = frozenset(BODY_CLASS_CODES.values()) - {BODY_CLASS_CODES["real"]}

#: Retired rule ids that still resolve, lower-cased. ``GEN001``–``GEN004`` are
#: ``tree_001``–``tree_004`` under the ids a pipeline may have typed, so they
#: stay accepted *selectors* — it costs one mapping — while every emitted
#: ``rule_id`` is the ``tree_*`` code and no published JSON schema names the old
#: ids.
LEGACY_CODE_ALIASES: dict[str, str] = {
    "gen001": "tree_001",
    "gen002": "tree_002",
    "gen003": "tree_003",
    "gen004": "tree_004",
}


@dataclass(frozen=True)
class LintRule:
    """One rule ``confiture lint`` can apply.

    Attributes:
        code: Stable rule identifier, as it appears in violation output.
        family: Selector group. Usually the code's prefix — with one exception:
            ``sec_001`` (``security``) and ``sec_002`` (``security-definer``)
            are unrelated rules that happen to share a prefix, and
            ``sec_002``'s family is named after its flag,
            ``--check-security-definer``.
        title: One-line description, shown by ``--list-rules``.
        severity: Severity the rule emits *by default*. ``sec_002`` and
            ``replica_001`` can be escalated by configuration.
        default_on: Whether a plain ``confiture lint`` applies it.
        legacy_flag: The rule's own per-rule flag, kept as an alias, or None.
        requires_config: Configuration the rule additionally needs before it can
            report anything — selecting it is necessary, not sufficient.
        requires_db: Whether the rule answers from a database rather than from
            the files. Such a rule can be *selected* and still not run — no
            server, an unreachable one, a missing extension — so it reports a
            :class:`~confiture.core.linting.schema_linter.RuleStatus` instead of
            an empty finding list, and ``--list-rules`` says so before the run
            rather than after it.
        escalates_to: The severity the rule emits when ``escalated_by`` holds,
            or None when :attr:`severity` is the only severity it ever emits.
            The gate reads this to answer whether a threshold is reachable for
            *this* project rather than in general.
        escalated_by: The configuration that raises the severity, named the way
            an operator would set it.
        enabled_by: A ``db/project.yaml`` block that turns the rule on by default
            when the project declares it (``tenancy``): the rule describes the
            project, so declaring the project once is the switch, and ``--ignore``
            still narrows it.
    """

    code: str
    family: str
    title: str
    severity: str
    default_on: bool
    legacy_flag: str | None = None
    requires_config: str | None = None
    escalates_to: str | None = None
    escalated_by: str | None = None
    requires_db: bool = False
    enabled_by: str | None = None

    def to_dict(self) -> dict[str, object]:
        """JSON shape for ``lint --list-rules --format json``."""
        return {
            "code": self.code,
            "family": self.family,
            "title": self.title,
            "severity": self.severity,
            "default_on": self.default_on,
            "legacy_flag": self.legacy_flag,
            "requires_config": self.requires_config,
            "escalates_to": self.escalates_to,
            "escalated_by": self.escalated_by,
            "requires_db": self.requires_db,
            "enabled_by": self.enabled_by,
        }


LINT_RULES: tuple[LintRule, ...] = (
    LintRule(
        code=UNPARSEABLE_RULE_ID,
        family="parse",
        # A file PostgreSQL's own parser rejects is a finding everywhere else in
        # confiture — `IDEM_UNPARSEABLE` fails `--fail-on-unanalyzable`,
        # `PFLIGHT_UNPARSEABLE` forces `window_safe: false`, `migrate diff` exits
        # on `DIFFER_400`. Lint grades it `error` for the same reason: at `info`
        # it would sit below every `--fail-on` threshold but `info`, and a build
        # lint had not read would pass the gate (#274). Registering it is also
        # what lets `compute_gate` see it, and what gives a project with a
        # deliberately non-SQL file the `--ignore UNPARSEABLE` it needs.
        title="Every file in the build parses",
        severity="error",
        default_on=True,
    ),
    LintRule(
        code="naming_001",
        family="naming",
        title="Table names should be snake_case",
        severity="warning",
        default_on=True,
    ),
    LintRule(
        code="naming_002",
        family="naming",
        title="Column names should be snake_case",
        severity="warning",
        default_on=True,
    ),
    LintRule(
        code="pk_001",
        family="pk",
        title="Every table should declare a primary key",
        severity="warning",
        default_on=True,
    ),
    LintRule(
        code="doc_001",
        family="doc",
        title="Every table should carry a COMMENT",
        severity="info",
        default_on=True,
    ),
    LintRule(
        code="doc_002",
        family="doc",
        title="Every function and procedure should carry a COMMENT (per overload)",
        severity="info",
        default_on=True,
    ),
    LintRule(
        code="doc_003",
        family="doc",
        title="Every view and materialized view should carry a COMMENT",
        severity="info",
        default_on=True,
    ),
    LintRule(
        code="doc_004",
        family="doc",
        title="Every composite type, enum and domain should carry a COMMENT",
        severity="info",
        default_on=True,
    ),
    LintRule(
        code="doc_005",
        family="doc",
        title="A COMMENT says something the object's own name does not",
        severity="info",
        default_on=False,
    ),
    LintRule(
        code="build_001",
        family="build",
        title="An object is defined more than once in one build",
        severity="error",
        default_on=True,
    ),
    LintRule(
        code="build_002",
        family="build",
        title="A routine's overloads are split across files",
        severity="info",
        default_on=True,
    ),
    LintRule(
        code="build_003",
        family="build",
        title="A body references an object the build does not create",
        severity="warning",
        default_on=True,
    ),
    LintRule(
        code="build_004",
        family="build",
        title="A statement needs, when it runs, an object the build creates later",
        severity="error",
        default_on=True,
    ),
    LintRule(
        code="sec_001",
        family="security",
        title="Columns that look like secrets should not be plain text",
        severity="warning",
        default_on=True,
    ),
    LintRule(
        code="sec_003",
        family="security",
        title="No credential is written as a literal in the tree (a seed row, a role password)",
        severity="warning",
        default_on=True,
    ),
    LintRule(
        code="qual_001",
        family="qual",
        title="Routines are created schema-qualified",
        severity="warning",
        default_on=True,
    ),
    LintRule(
        code="qual_002",
        family="qual",
        title="Relations and types are created schema-qualified",
        severity="warning",
        default_on=False,
    ),
    LintRule(
        code="acl_001",
        family="acl",
        title="Every CREATE TABLE has a matching GRANT",
        # A missing GRANT is a table the application cannot read once deployed.
        # The catalogue states the severity the rule emits, because `--fail-on`
        # is chosen by reading it.
        severity="error",
        default_on=False,
        requires_config="acls.lint_enabled: true",
    ),
    LintRule(
        code="tenant_001",
        family="tenant",
        title="Function INSERTs carry the FK a tenant-scoped view requires",
        severity="warning",
        default_on=False,
        legacy_flag="--check-tenant-isolation",
    ),
    LintRule(
        code="tenant_002",
        family="tenant",
        title="A table carries the tenant discriminator NOT NULL, or is declared global",
        severity="warning",
        default_on=False,
        enabled_by="tenancy",
    ),
    LintRule(
        code="tenant_003",
        family="tenant",
        title="A view reading tenant data publishes the discriminator as a plain column, "
        "or is declared global",
        severity="warning",
        default_on=False,
        enabled_by="tenancy",
    ),
    LintRule(
        code="tenant_004",
        family="tenant",
        title="A foreign key between tenant tables carries the discriminator on both sides",
        severity="warning",
        default_on=False,
        enabled_by="tenancy",
    ),
    LintRule(
        code="tenant_005",
        family="tenant",
        title="A tenant table's primary key and unique keys lead with the discriminator",
        severity="warning",
        default_on=False,
        enabled_by="tenancy",
    ),
    LintRule(
        code="replica_001",
        family="replica",
        title="Migrations stay forward-compatible with streaming replicas",
        severity="warning",
        default_on=False,
        legacy_flag="--replica-safe",
        escalates_to="error",
        escalated_by="infrastructure.replicas declared, without migration.allow_unsafe_under_replication",
    ),
    LintRule(
        code="func_001",
        family="func",
        title="Every function and procedure signature is defined exactly once",
        severity="error",
        default_on=False,
        requires_config="function_coverage.enabled: true",
    ),
    LintRule(
        code="own_001",
        family="own",
        title="Every created relation is paired with an ALTER … OWNER TO",
        severity="error",
        default_on=False,
        requires_config="ownership.lint_enabled: true",
    ),
    LintRule(
        code="own_002",
        family="own",
        # Graded by the finding, not by configuration: an `ALTER … OWNER TO`
        # wrapped in an `IF EXISTS` guard is a `warning`, a bare one an `error`.
        # The declaration is the ceiling, because that is what the gate needs to
        # answer "can `--fail-on error` fire here"; the title states the floor.
        title="No bare ALTER … OWNER TO on an object the migration did not create (guarded: warning)",
        severity="error",
        default_on=False,
        requires_config="an ownership: block",
    ),
    LintRule(
        code="tree_001",
        family="tree",
        title="No two files in one directory share a numeric prefix",
        severity="error",
        # On by default (#384): two files on one prefix load in an order their
        # names after the prefix decide, which no reader of either can see — the
        # defect build_001 reports once it bites. The rest of the family stays
        # opt-in: it is about naming, and this one is about order.
        default_on=True,
    ),
    LintRule(
        code="tree_002",
        family="tree",
        title="A numbered file carries a verb after its prefix",
        severity="warning",
        default_on=False,
    ),
    LintRule(
        code="tree_003",
        family="tree",
        title="Prefixes within one directory are contiguous",
        severity="warning",
        default_on=False,
    ),
    LintRule(
        code="tree_004",
        family="tree",
        title="Every file in the overrides mirror has a counterpart in the tree",
        severity="warning",
        default_on=False,
        requires_config="--overrides-dir <path>",
    ),
    LintRule(
        code="tree_005",
        family="tree",
        title="No two sibling entries share a numeric prefix",
        severity="warning",
        default_on=False,
    ),
    LintRule(
        code="tree_006",
        family="tree",
        title="An entry's prefix extends its parent's",
        severity="warning",
        default_on=False,
    ),
    LintRule(
        code="tree_007",
        family="tree",
        title="An entry numbered like its siblings, or none of them numbered",
        severity="warning",
        default_on=False,
    ),
    LintRule(
        code="tree_008",
        family="tree",
        title="No status word in a file or directory name the build reads",
        severity="info",
        default_on=False,
        requires_config="lint.status_words (optional; four words are the default)",
    ),
    LintRule(
        code="body_001",
        family="body",
        title="A plpgsql body resolves against the schema it is built into",
        severity="warning",
        default_on=False,
        requires_config="a writable maintenance server carrying plpgsql_check (--server-url)",
        requires_db=True,
    ),
    LintRule(
        code="body_003",
        family="body",
        title="Analysis artefact: a body names a TEMP table only a running body creates",
        severity="warning",
        default_on=False,
        requires_config="a writable maintenance server carrying plpgsql_check (--server-url)",
        requires_db=True,
    ),
    LintRule(
        code="body_004",
        family="body",
        title="Analysis artefact: plpgsql_check cannot follow a RECORD variable's assignment",
        severity="warning",
        default_on=False,
        requires_config="a writable maintenance server carrying plpgsql_check (--server-url)",
        requires_db=True,
    ),
    LintRule(
        code="body_005",
        family="body",
        title="Analysis artefact: a body calls dblink, which the analysed database lacks",
        severity="warning",
        default_on=False,
        requires_config="a writable maintenance server carrying plpgsql_check (--server-url)",
        requires_db=True,
    ),
    LintRule(
        code="body_002",
        family="body",
        title="A plpgsql body carries no unused variable or shadowed declaration",
        severity="info",
        default_on=False,
        requires_config="a writable maintenance server carrying plpgsql_check (--server-url)",
        requires_db=True,
    ),
    LintRule(
        code="sec_002",
        family="security-definer",
        title="SECURITY DEFINER routines pin search_path (CVE-2018-1058)",
        severity="warning",
        default_on=False,
        legacy_flag="--check-security-definer",
        requires_config="security_lint.enabled: true",
        escalates_to="error",
        escalated_by="security_lint.severity: error",
    ),
)


def families() -> tuple[str, ...]:
    """Every family name, in registry order, without duplicates."""
    seen: list[str] = []
    for rule in LINT_RULES:
        if rule.family not in seen:
            seen.append(rule.family)
    return tuple(seen)


def default_codes(declared: frozenset[str] = frozenset()) -> frozenset[str]:
    """The rule codes a plain ``confiture lint`` applies.

    Args:
        declared: The ``db/project.yaml`` blocks the project declares; a rule
            :attr:`~LintRule.enabled_by` one of them is on by default.
    """
    return frozenset(
        rule.code for rule in LINT_RULES if rule.default_on or rule.enabled_by in declared
    )


def _expand(token: str, *, option: str, declared: frozenset[str] = frozenset()) -> frozenset[str]:
    """Resolve one selector token to rule codes.

    Args:
        token: A rule code, a family name, or :data:`DEFAULT_SELECTOR`.
        option: The flag the token came from, for the error message.

    Returns:
        The codes the token names.

    Raises:
        ConfigurationError: The token matches no rule and no family. Selecting
            nothing silently would let a typo switch a rule off, so an
            unknown selector is loud and lists what is valid.
    """
    key = token.strip().lower()
    if not key:
        return frozenset()
    key = LEGACY_CODE_ALIASES.get(key, key)
    if key == DEFAULT_SELECTOR:
        return default_codes(declared)
    # Keyed on the folded code and answering with the registry's own spelling:
    # selection is case-insensitive, and `UNPARSEABLE` is the one upper-case
    # code — which would otherwise resolve to a set holding `unparseable`,
    # matching no finding's `rule_id`.
    by_code = {rule.code.lower(): rule.code for rule in LINT_RULES}
    if key in by_code:
        return frozenset({by_code[key]})
    matched = frozenset(rule.code for rule in LINT_RULES if rule.family == key)
    if matched:
        return matched
    raise ConfigurationError(
        f"Unknown lint rule or family in {option}: {token!r}",
        error_code="CONFIG_010",
        resolution_hint=(
            f"Families: {', '.join(families())}, {DEFAULT_SELECTOR}. "
            f"Codes: {', '.join(rule.code for rule in LINT_RULES)}. "
            f"Deprecated aliases: {', '.join(sorted(a.upper() for a in LEGACY_CODE_ALIASES))}. "
            "Run `confiture lint --list-rules` for the full table."
        ),
    )


def _expand_all(
    tokens: Iterable[str], *, option: str, declared: frozenset[str] = frozenset()
) -> frozenset[str]:
    codes: set[str] = set()
    for token in tokens:
        for part in str(token).split(","):
            codes |= _expand(part, option=option, declared=declared)
    return frozenset(codes)


def resolve_selection(
    select: Sequence[str] | None,
    ignore: Sequence[str],
    *,
    declared: frozenset[str] = frozenset(),
) -> frozenset[str]:
    """The exact rule codes one ``confiture lint`` invocation applies.

    Args:
        select: ``--select`` values (each may be comma-separated). ``None`` or
            empty means the default set, what a plain ``confiture lint`` applies.
        ignore: ``--ignore`` values, removed after selection.
        declared: The ``db/project.yaml`` blocks the project declares, which
            turn their rules on by default.

    Returns:
        The selected rule codes. Selecting a rule is necessary but not always
        sufficient — see :attr:`LintRule.requires_config`.

    Raises:
        ConfigurationError: An unknown code or family appeared in either option.
    """
    selected = (
        _expand_all(select, option="--select", declared=declared)
        if select
        else default_codes(declared)
    )
    excluded = _expand_all(ignore, option="--ignore") if ignore else frozenset()
    return frozenset(selected - excluded)


def render_rule_table() -> str:
    """Render every registered rule as a Markdown table (docs/reference/lint-rules.md).

    Generated from ``LINT_RULES`` so the published rule reference can never drift
    from what ``confiture lint --list-rules`` reports; a test holds the two equal.
    """
    lines = [
        "| Code | Family | Severity | Default | Rule |",
        "|------|--------|----------|:-------:|------|",
    ]
    for rule in LINT_RULES:
        default = (
            "on" if rule.default_on else f"with `{rule.enabled_by}:`" if rule.enabled_by else "off"
        )
        title = rule.title.replace("|", "\\|")
        lines.append(f"| `{rule.code}` | {rule.family} | {rule.severity} | {default} | {title} |")
    return "\n".join(lines)


def _span(codes: Sequence[str]) -> list[str]:
    """``doc_001``, ``doc_002``, ``doc_003`` as ``doc_001–doc_003``; gaps kept apart."""
    spans: list[list[str]] = []
    for code in codes:
        family, number = code.rsplit("_", 1)
        if spans:
            last_family, last_number = spans[-1][-1].rsplit("_", 1)
            if last_family == family and int(last_number) + 1 == int(number):
                spans[-1].append(code)
                continue
        spans.append([code])
    return [span[0] if len(span) == 1 else f"{span[0]}–{span[-1]}" for span in spans]


def _grouped(rules: Iterable[LintRule]) -> list[str]:
    """Rule codes in code order, runs of one family and one requirement spanned."""
    parts: list[str] = []
    ordered = sorted(rules, key=lambda rule: rule.code)
    run: list[LintRule] = []
    for rule in [*ordered, None]:
        if run and (
            rule is None
            or rule.family != run[-1].family
            or rule.requires_config != run[-1].requires_config
            or rule.enabled_by != run[-1].enabled_by
        ):
            spanned = ", ".join(_span([r.code for r in run]))
            needs = run[-1].requires_config or (
                f"on when db/project.yaml declares {run[-1].enabled_by}:"
                if run[-1].enabled_by
                else None
            )
            parts.append(f"{spanned} ({needs})" if needs else spanned)
            run = []
        if rule is not None:
            run.append(rule)
    return parts


def render_help_catalogue(indent: str = "      ", width: int = 84) -> str:
    """The ``lint --help`` paragraphs saying which rules run by default (#430).

    Generated from ``LINT_RULES``, the table ``--list-rules`` prints, so the help
    cannot describe a default-on rule as opt-in again.
    """
    listed = [rule for rule in LINT_RULES if rule.code != UNPARSEABLE_RULE_ID]
    default_on = [rule for rule in listed if rule.default_on]
    failing = [rule for rule in default_on if rule.severity == "error"]
    opt_in = [rule for rule in listed if not rule.default_on]
    paragraphs = [
        f"On by default: {', '.join(_grouped(default_on))}.",
        f"Of those, {', '.join(_grouped(failing))} emit `error`, so a plain lint fails on them.",
        "Opt-in, selected by code or family (`--select tree`), each with the "
        f"configuration it also needs: {', '.join(_grouped(opt_in))}.",
    ]
    return "\n\n".join(
        textwrap.fill(
            p,
            width=width,
            initial_indent=indent,
            subsequent_indent=indent,
            break_on_hyphens=False,
        )
        for p in paragraphs
    )
