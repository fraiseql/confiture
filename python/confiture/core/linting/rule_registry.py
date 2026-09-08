"""The catalogue of rules ``confiture lint`` can run, and how to select them (#150).

Before 0.42.0 every opt-in rule arrived as its own flag: ``--replica-safe``
(0.19.0), ``--check-tenant-isolation``, ``--check-security-definer`` (0.28.0).
Three flags, two naming styles, and no way to *turn a rule off* — #150's
prediction, filed when there was one of them.

This module is the single backing store: :func:`resolve_selection` turns
``--select`` / ``--ignore`` into the exact set of rule codes a run will apply,
``lint --list-rules`` enumerates :data:`LINT_RULES`, and the three legacy flags
are re-expressed as ``--select default,<family>`` rather than as branches in the
command body.

**Only rules that can actually emit a violation are listed.** ``LintConfig``
also carries ``check_indexes`` and ``check_constraints``; the first computes and
discards, the second has no implementation at all. Listing them would move the
existing over-claim into a new, more authoritative place.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from confiture.exceptions import ConfigurationError

#: Selector meaning "everything that runs by default". Not a family — it exists
#: so the legacy flags stay expressible: ``--replica-safe`` is exactly
#: ``--select default,replica``, i.e. the usual lint *plus* one family.
DEFAULT_SELECTOR = "default"

#: Retired rule ids that still resolve, lower-cased. The file-tree rules emitted
#: ``GEN001``–``GEN004`` from a namespace ``confiture lint`` could not reach;
#: folding them in as ``tree_001``–``tree_004`` renamed ids a pipeline may have
#: typed, so the old spelling stays an accepted *selector* for one minor — it
#: costs one mapping — while the emitted ``rule_id`` is the new code from 1.4.0
#: on. Nothing published ever carried the old ids: ``lint-unified``, the only
#: command that emitted them, has no JSON schema.
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
            are unrelated rules that happen to share a prefix, and the flag
            that shipped ``sec_002`` named the latter.
        title: One-line description, shown by ``--list-rules``.
        severity: Severity the rule emits *by default*. ``sec_002`` and
            ``replica_001`` can be escalated by configuration.
        default_on: Whether a plain ``confiture lint`` applies it.
        legacy_flag: The pre-0.42.0 per-rule flag, kept as an alias, or None.
        requires_config: Configuration the rule additionally needs before it can
            report anything — selecting it is necessary, not sufficient.
        escalates_to: The severity the rule emits when ``escalated_by`` holds,
            or None when :attr:`severity` is the only severity it ever emits.
            The gate reads this to answer whether a threshold is reachable for
            *this* project rather than in general.
        escalated_by: The configuration that raises the severity, named the way
            an operator would set it.
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
        }


LINT_RULES: tuple[LintRule, ...] = (
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
        code="build_001",
        family="build",
        title="An object is defined more than once in one build",
        severity="warning",
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
        code="sec_001",
        family="security",
        title="Columns that look like secrets should not be plain text",
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
        # The rule has always emitted `error`; before 1.4.0 the catalogue said
        # `warning`, which is the entry that was wrong (LINT-01) — no project's
        # exit code moves, because the emission is unchanged.
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
        default_on=False,
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


def default_codes() -> frozenset[str]:
    """The rule codes a plain ``confiture lint`` applies."""
    return frozenset(rule.code for rule in LINT_RULES if rule.default_on)


def _expand(token: str, *, option: str) -> frozenset[str]:
    """Resolve one selector token to rule codes.

    Args:
        token: A rule code, a family name, or :data:`DEFAULT_SELECTOR`.
        option: The flag the token came from, for the error message.

    Returns:
        The codes the token names.

    Raises:
        ConfigurationError: The token matches no rule and no family. Selecting
            nothing silently is precisely the failure this replaces, so an
            unknown selector is loud and lists what is valid.
    """
    key = token.strip().lower()
    if not key:
        return frozenset()
    key = LEGACY_CODE_ALIASES.get(key, key)
    if key == DEFAULT_SELECTOR:
        return default_codes()
    by_code = {rule.code: rule for rule in LINT_RULES}
    if key in by_code:
        return frozenset({key})
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


def _expand_all(tokens: Iterable[str], *, option: str) -> frozenset[str]:
    codes: set[str] = set()
    for token in tokens:
        for part in str(token).split(","):
            codes |= _expand(part, option=option)
    return frozenset(codes)


def resolve_selection(
    select: Sequence[str] | None,
    ignore: Sequence[str],
) -> frozenset[str]:
    """The exact rule codes one ``confiture lint`` invocation applies.

    Args:
        select: ``--select`` values (each may be comma-separated). ``None`` or
            empty means the default set, i.e. pre-0.42.0 behaviour.
        ignore: ``--ignore`` values, removed after selection.

    Returns:
        The selected rule codes. Selecting a rule is necessary but not always
        sufficient — see :attr:`LintRule.requires_config`.

    Raises:
        ConfigurationError: An unknown code or family appeared in either option.
    """
    selected = _expand_all(select, option="--select") if select else default_codes()
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
        default = "on" if rule.default_on else "off"
        title = rule.title.replace("|", "\\|")
        lines.append(f"| `{rule.code}` | {rule.family} | {rule.severity} | {default} | {title} |")
    return "\n".join(lines)
