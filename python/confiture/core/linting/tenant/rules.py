"""The ``tenant`` rules, and the one classification of the tables they all read.

Each rule of the family is a function of a :class:`TenantTree`: every table's
:class:`~.scope.TenantScopes`, decided once per lint from the tables the tree
declares, ``db/project.yaml``'s ``tenancy:`` block and the ``tenant-global``
directives written in the files — and, for the rule that reads views, the
inventory and the files themselves.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from confiture.core import sql_lexer
from confiture.core.linting.inventory import inherit_columns
from confiture.core.linting.tenant import inserts, keys, scope, views
from confiture.core.sql_lexer import ParsedFile

if TYPE_CHECKING:
    from confiture.config.project import TenancyConfig
    from confiture.core.linting.inventory import Inventory, SchemaObject


@dataclass(frozen=True)
class TenantTree:
    """What the family reads: every table's scope, the inventory, the files."""

    scopes: scope.TenantScopes
    inventory: Inventory
    files: Sequence[ParsedFile]


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
        lambda tree: inserts.insert_findings(tree.scopes, tree.inventory, tree.files),
    ),
    "tenant_002": TenantRule(
        "Tenant Discriminator", "table", lambda tree: scope.table_findings(tree.scopes)
    ),
    "tenant_003": TenantRule(
        "Tenant View",
        "view",
        lambda tree: views.view_findings(tree.scopes, tree.inventory, tree.files),
    ),
    "tenant_004": TenantRule(
        "Tenant Foreign Key", "table", lambda tree: keys.foreign_key_findings(tree.scopes)
    ),
    "tenant_005": TenantRule(
        "Tenant Unique Key", "table", lambda tree: keys.unique_key_findings(tree.scopes)
    ),
}


def declarations(files: Iterable[ParsedFile]) -> scope.Declarations:
    """``(file, statement line)`` of every ``tenant-global`` directive, with its reason."""
    return {
        (parsed.label, directive.statement_line): directive.argument
        for parsed in files
        for directive in sql_lexer.directives(parsed.text)
        if directive.name == scope.GLOBAL_DIRECTIVE and directive.statement_line is not None
    }


def tree(inventory: Inventory, tenancy: TenancyConfig, files: Sequence[ParsedFile]) -> TenantTree:
    """What every rule of the family reads, the tables classified once.

    A table reads with the columns PostgreSQL gives it through ``INHERITS`` or
    ``PARTITION OF`` (#467): a child of a tenant table carries the discriminator.
    """
    held = inherit_columns(inventory)
    return TenantTree(scopes(held.tables, tenancy, files), held, files)


def scopes(
    tables: Iterable[SchemaObject],
    tenancy: TenancyConfig,
    files: Sequence[ParsedFile],
) -> scope.TenantScopes:
    """Every table's scope, the directives in *files* read.

    Args:
        tables: The tables the tree declares, ``ALTER``s folded in.
        tenancy: ``db/project.yaml``'s ``tenancy`` block.
        files: The schema files the tables were read from, so a directive and
            its statement share a line.
    """
    return scope.classify(tables, tenancy, declarations(files))
