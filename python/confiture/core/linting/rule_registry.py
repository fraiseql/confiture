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
    """

    code: str
    family: str
    title: str
    severity: str
    default_on: bool
    legacy_flag: str | None = None
    requires_config: str | None = None

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
        code="sec_001",
        family="security",
        title="Columns that look like secrets should not be plain text",
        severity="warning",
        default_on=True,
    ),
    LintRule(
        code="acl_001",
        family="acl",
        title="Every CREATE TABLE has a matching GRANT",
        severity="warning",
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
    ),
    LintRule(
        code="sec_002",
        family="security-definer",
        title="SECURITY DEFINER routines pin search_path (CVE-2018-1058)",
        severity="warning",
        default_on=False,
        legacy_flag="--check-security-definer",
        requires_config="security_lint.enabled: true",
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
