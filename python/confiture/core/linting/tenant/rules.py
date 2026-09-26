"""The ``tenant`` rules, and the one classification of the tables they all read.

Each rule of the family is a function of a :class:`TenantTree`: every table's
:class:`~.scope.TenantScopes`, decided once per lint from the tables the tree
declares, ``db/project.yaml``'s ``tenancy:`` block and the ``tenant-global``
directives written in the files — and, for the rule that reads views, the
inventory and the files themselves.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from confiture.core import sql_lexer
from confiture.core.linting.tenant import inserts, keys, scope, views

if TYPE_CHECKING:
    from confiture.config.project import TenancyConfig
    from confiture.core.linting.inventory import Inventory, SchemaObject

#: ``(file label, text)`` per schema file.
Sources = Sequence[tuple[str | None, str]]


@dataclass(frozen=True)
class TenantTree:
    """What the family reads: every table's scope, the inventory, the files."""

    scopes: scope.TenantScopes
    inventory: Inventory
    sources: Sources


@dataclass(frozen=True)
class TenantRule:
    """What a rule is called in a finding, what it judges, and how it finds."""

    name: str
    #: The ``object_type`` of its findings.
    kind: str
    findings: Callable[[TenantTree], Iterable[scope.TenancyFinding]]


#: The rules of the family, by code.
RULES: dict[str, TenantRule] = {
    "tenant_001": TenantRule(
        "Tenant Insert",
        "function",
        lambda tree: inserts.insert_findings(tree.scopes, tree.inventory, tree.sources),
    ),
    "tenant_002": TenantRule(
        "Tenant Discriminator", "table", lambda tree: scope.table_findings(tree.scopes)
    ),
    "tenant_003": TenantRule(
        "Tenant View",
        "view",
        lambda tree: views.view_findings(tree.scopes, tree.inventory, tree.sources),
    ),
    "tenant_004": TenantRule(
        "Tenant Foreign Key", "table", lambda tree: keys.foreign_key_findings(tree.scopes)
    ),
    "tenant_005": TenantRule(
        "Tenant Unique Key", "table", lambda tree: keys.unique_key_findings(tree.scopes)
    ),
}


def declarations(sources: Iterable[tuple[str | None, str]]) -> scope.Declarations:
    """``(file, statement line)`` of every ``tenant-global`` directive, with its reason."""
    return {
        (label, directive.statement_line): directive.argument
        for label, text in sources
        for directive in sql_lexer.directives(text)
        if directive.name == scope.GLOBAL_DIRECTIVE and directive.statement_line is not None
    }


def tree(inventory: Inventory, tenancy: TenancyConfig, sources: Sources) -> TenantTree:
    """What every rule of the family reads, the tables classified once."""
    return TenantTree(scopes(inventory.tables, tenancy, sources), inventory, sources)


def scopes(
    tables: Iterable[SchemaObject],
    tenancy: TenancyConfig,
    sources: Sources,
) -> scope.TenantScopes:
    """Every table's scope, the directives in *sources* read.

    Args:
        tables: The tables the tree declares, ``ALTER``s folded in.
        tenancy: ``db/project.yaml``'s ``tenancy`` block.
        sources: ``(file label, text)`` per schema file — the text the tables
            were read from, so a directive and its statement share a line.
    """
    return scope.classify(tables, tenancy, declarations(sources), _locator(sources))


def _locator(
    sources: Sources,
) -> Callable[[int], tuple[str | None, int]]:
    """``(file, line)`` of a line of *sources* concatenated, each ended by a newline.

    The inventory reads the files as one text laid out that way
    (``SchemaLinter._assemble_parse_text``), so a statement's line in it is a
    line in one file.
    """
    starts: list[int] = []
    first = 1
    for _, text in sources:
        starts.append(first)
        first += text.count("\n") + (1 if text and not text.endswith("\n") else 0)

    def locate(line: int) -> tuple[str | None, int]:
        at = bisect_right(starts, line) - 1
        if at < 0:
            return None, line
        return sources[at][0], line - starts[at] + 1

    return locate
