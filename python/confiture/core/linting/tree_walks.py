"""How a TVIEW's chain walks a pg_treekey tree (#676): ``treekey_001`` and ``treekey_002``.

A tree is a table whose ltree path pg_treekey maintains, declared by a
``treekey.manage_path(table, pk_col, parent_fk_col[, path_col])`` call in the tree;
each column argument is an ``attname``, matched exactly, as pg_treekey matches it.
pg_tviews follows a TVIEW's query through the plain views it reads
(:mod:`~confiture.core.linting.tview_reads`, routines not followed: a function's
tables reach pg_tviews through ``function_reads``) to decide which rows a write
refreshes. What it does with each spelling of a walk over a managed tree, measured
on pg_tviews 0.1.0-beta.26 (PostgreSQL 18.6, 2026-10-10):

======================================================  ==================================  =============
Spelling                                                pg_tviews                           Rule
======================================================  ==================================  =============
``a.path @> n.path``                                    mapped                              none
the path unnested (scalar subquery, ``IN``, ``= ANY``,  mapped (a seq scan without a GIN    none
CTE, plain ``LATERAL``)                                 index)
the path unnested ``WITH ORDINALITY``                   **refused** at create               ``treekey_002``
``WITH RECURSIVE`` reading the tree                     ``all_keys``: refused (``error``),  ``treekey_001``
                                                        rebuilt in full (``full_refresh``),
                                                        **stale** (``warn``)
======================================================  ==================================  =============

``treekey_001`` reports a recursive CTE that reads a tree — itself, or through a CTE
of the same ``WITH RECURSIVE`` it reads, or a plain view — on a TVIEW's chain,
unless the policy a write to that tree meets is ``full_refresh`` (the TVIEW's
``uncascaded_tables`` entry for it, else its ``uncascaded_policy``). One finding per
walk, where the CTE is written, naming every TVIEW that reaches it.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from confiture.core.ddl_walk import constant_text, uncascaded_policy_for, walk_nodes
from confiture.core.linting.inventory import Inventory, SchemaObject, split_names
from confiture.core.linting.tview_reads import (
    Holder,
    Path,
    Query,
    ReadGraph,
    Target,
    key,
    spelled,
)
from confiture.core.schema_identity import identifier_identity
from confiture.core.schema_model import RelationName, TView
from confiture.core.sql_lexer import ParsedFile, name_parts

#: The name a finding of each code carries.
RULE_NAMES = {
    "treekey_001": "View Walks A Tree Recursively",
    "treekey_002": "View Unnests A Tree Path",
}

#: ``manage_path``'s parameters, by name and position; ``path_col`` defaults to ``path``.
_PARAMETERS = ("table_ref", "pk_col", "parent_fk_col", "path_col")
_DEFAULT_PATH = "path"
_TREEKEY_SCHEMA = "treekey"
_PATH_FUNCTIONS = frozenset({"unnest", "string_to_array"})
_BUILTIN_SCHEMAS = (None, "pg_catalog")
#: The parts of a schema-qualified table name.
_QUALIFIED = 2

_FIX = (
    "Walk the ancestors with treekey.register_ancestry('{tree}', …), which generates "
    "a correlated @> view, or write the subquery yourself: WHERE a.{path} @> n.{path}."
)


@dataclass(frozen=True)
class Tree:
    """A table pg_treekey maintains a path on, and the two columns a walk names."""

    relation: RelationName
    parent_fk: str
    path: str


@dataclass(frozen=True)
class TreeWalkFinding:
    """One view walking one tree in one spelling, where the walk is written."""

    code: str
    object_type: str
    object_name: str
    message: str
    fix: str
    file: str | None
    line: int


@dataclass(frozen=True)
class TreeWalks:
    """The findings, and what could not be read (a degraded rule)."""

    findings: list[TreeWalkFinding]
    unread: list[str]


def tree_walks(files: Sequence[ParsedFile], inventory: Inventory) -> TreeWalks:
    """Every walk of a tree the tree's views make, in file order.

    A ``manage_path`` call whose table or columns are not constants, and a TVIEW
    query the parser rejects, are named in :attr:`TreeWalks.unread`.
    """
    trees: list[Tree] = []
    unread: list[str] = []
    for parsed in files:
        for raw in parsed.statements:
            for tree in _managed(raw.stmt):
                if tree is None:
                    unread.append(f"a treekey.manage_path() call in {parsed.label or 'the schema'}")
                else:
                    trees.append(tree)
    if not trees:
        return TreeWalks([], unread)
    graph = ReadGraph.read(files, inventory)
    tviews = [target for target in graph.targets if target.family == "tview"]
    findings = _Walks(graph, trees).findings(tviews)
    for holder in graph.holders.values():
        if holder.obj.kind not in ("view", "matview", "tview"):
            continue
        for query in holder.queries:
            findings.extend(_walks(holder.obj, query, trees))
    unread.extend(graph.unread(graph.targets, routines=False))
    return TreeWalks(
        sorted(findings, key=lambda f: (f.file or "", f.line, f.code, f.object_name)),
        sorted(unread),
    )


def tree_walk_findings(files: Sequence[ParsedFile], inventory: Inventory) -> list[TreeWalkFinding]:
    """:func:`tree_walks`' findings alone."""
    return tree_walks(files, inventory).findings


def _managed(stmt: Any) -> Iterator[Tree | None]:
    """Each tree a ``SELECT treekey.manage_path(…)`` declares; ``None`` for one it cannot read."""
    if type(stmt).__name__ != "SelectStmt":
        return
    for node in walk_nodes(stmt):
        if type(node).__name__ != "FuncCall":
            continue
        schema, name = split_names(node.funcname)
        if name != "manage_path" or schema not in (None, _TREEKEY_SCHEMA):
            continue
        yield _tree(_arguments(node))


def _arguments(node: Any) -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    for at, arg in enumerate(node.args or ()):
        if type(arg).__name__ == "NamedArgExpr":
            found[str(arg.name)] = constant_text(arg.arg)
        elif at < len(_PARAMETERS):
            found[_PARAMETERS[at]] = constant_text(arg)
    return found


def _tree(arguments: dict[str, str | None]) -> Tree | None:
    table = arguments.get("table_ref")
    parent_fk = arguments.get("parent_fk_col")
    path = arguments.get("path_col", _DEFAULT_PATH)
    parts = name_parts(table) if table is not None else None
    if not parts or len(parts) > _QUALIFIED or parent_fk is None or path is None:
        return None
    schema = identifier_identity(parts[0]) if len(parts) == _QUALIFIED else None
    return Tree(RelationName(schema, identifier_identity(parts[-1])), parent_fk, path)


def _walks(obj: SchemaObject, query: Query, trees: list[Tree]) -> Iterator[TreeWalkFinding]:
    nodes = list(walk_nodes(query.root))
    line_at = query.line_at
    local = {n.ctename for n in nodes if type(n).__name__ == "CommonTableExpr"}
    read = {
        RelationName(n.schemaname, n.relname).identity
        for n in nodes
        if type(n).__name__ == "RangeVar" and not (n.schemaname is None and n.relname in local)
    }
    for tree in trees:
        if tree.relation.identity not in read:
            continue
        unnest = _path_unnest(nodes, tree.path)
        if unnest is not None:
            location, function = unnest
            yield _finding(
                "treekey_002",
                query,
                obj,
                tree,
                line_at(location),
                f"takes {tree.relation.qualified}.{tree.path} apart with {function}(…): "
                "pg_tviews cannot always link a write to the rows it changes (in a CTE it "
                "refuses the view as unlinked, fraiseql/pg_tviews#196)",
            )


def _path_unnest(nodes: list[Any], path: str) -> tuple[int | None, str] | None:
    """Where ``unnest`` or ``string_to_array`` takes *path* as an argument, or ``None``."""
    for node in nodes:
        if type(node).__name__ != "FuncCall":
            continue
        schema, name = split_names(node.funcname)
        if (
            name in _PATH_FUNCTIONS
            and schema in _BUILTIN_SCHEMAS
            and any(_names_column(arg, path) is not None for arg in node.args or ())
        ):
            return node.location, name
    return None


def _names_column(root: Any, column: str) -> int | None:
    """Where *root* first names *column* (as PostgreSQL holds it), or ``None``."""
    for node in walk_nodes(root):
        if type(node).__name__ == "ColumnRef" and getattr(node.fields[-1], "sval", None) == column:
            return node.location
    return None


class _Walks:
    """``treekey_001``: each recursive walk of a tree on a TVIEW's chain, once per site."""

    def __init__(self, graph: ReadGraph, trees: list[Tree]) -> None:
        self.graph = graph
        self.trees = trees
        self._through: dict[tuple[str, Tree], bool] = {}

    def findings(self, tviews: list[Target]) -> list[TreeWalkFinding]:
        sites: dict[tuple[int, int, Tree], list[tuple[Target, Path, str | None]]] = {}
        placed: dict[tuple[int, int, Tree], tuple[Holder, Query, int]] = {}
        for target in tviews:
            declared = target.declared or TView(target.obj.name)
            for holder, path in self.graph.chain(target, routines=False):
                for query in holder.queries:
                    for location, tree in self._recursive_reads(query):
                        policy = uncascaded_policy_for(declared, tree.relation)
                        if policy == "full_refresh":
                            continue
                        site = (id(holder), location, tree)
                        sites.setdefault(site, []).append((target, path, policy))
                        placed[site] = (holder, query, location)
        return [
            _recursive_finding(*placed[site], site[2], reached) for site, reached in sites.items()
        ]

    def _recursive_reads(self, query: Query) -> Iterator[tuple[int, Tree]]:
        """``(where, tree)`` for each recursive CTE that reads a tree, itself or by a sibling.

        Measured on pg_tviews 0.1.0-beta.26: a tree read in the recursive CTE, or in
        a CTE of the same ``WITH RECURSIVE`` it reads, is ``all_keys``; one read by a
        sibling the recursive CTE never reads is read as any CTE is.
        """
        nodes = list(walk_nodes(query.root))
        local = {n.ctename for n in nodes if type(n).__name__ == "CommonTableExpr"}
        for node in nodes:
            clause = (
                getattr(node, "withClause", None) if type(node).__name__ == "SelectStmt" else None
            )
            if clause is None or not clause.recursive:
                continue
            ctes = {cte.ctename: cte for cte in clause.ctes or ()}
            reads = {name: _relations(cte.ctequery) for name, cte in ctes.items()}
            for name, cte in ctes.items():
                if (None, name) not in reads[name]:
                    continue
                reached = _closure(name, reads, ctes)
                for tree in self.trees:
                    if any(self._reads_tree(rv, tree, local) for n in reached for rv in reads[n]):
                        yield cte.location, tree

    def _reads_tree(self, relation: tuple[str | None, str], tree: Tree, local: set[str]) -> bool:
        """Whether *relation* is *tree*, or a plain view that reads it, through views."""
        schema, name = relation
        if schema is None and name in local:
            return False
        if _names(relation, tree.relation):
            return True
        return any(
            self._view_reads_tree(view, tree) for view in self.graph.views_named(schema, name)
        )

    def _view_reads_tree(self, holder: Holder, tree: Tree) -> bool:
        cached = (key(holder.obj), tree)
        if cached not in self._through:
            self._through[cached] = False
            self._through[cached] = any(
                self._reads_tree(relation, tree, set())
                for query in holder.queries
                for relation in _relations(query.root)
            )
        return self._through[cached]


def _relations(root: Any) -> set[tuple[str | None, str]]:
    """``(schema, name)`` of every relation *root* names, as the parser holds them."""
    return {
        (node.schemaname, node.relname)
        for node in walk_nodes(root)
        if type(node).__name__ == "RangeVar"
    }


def _closure(name: str, reads: dict[str, set[tuple[str | None, str]]], ctes: dict) -> set[str]:
    """The CTEs of one ``WITH`` clause *name* reads, transitively, itself included."""
    reached, pending = {name}, [name]
    while pending:
        for schema, other in reads[pending.pop()]:
            if schema is None and other in ctes and other not in reached:
                reached.add(other)
                pending.append(other)
    return reached


def _names(relation: tuple[str | None, str], table: RelationName) -> bool:
    """Whether *relation* names *table*: a missing schema on either side matches any."""
    schema, name = relation
    return name == table.name and (schema is None or table.schema is None or schema == table.schema)


def _recursive_finding(
    holder: Holder,
    query: Query,
    location: int,
    tree: Tree,
    reached: list[tuple[Target, Path, str | None]],
) -> TreeWalkFinding:
    names = list(dict.fromkeys(spelled(target.obj) for target, _, _ in reached))
    subject = (
        names[0] + " reads" if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]} read"
    )
    _target, first_path, _policy = reached[0]
    through = (
        f" through {' → '.join(spelled(step.obj) for step in first_path)}" if first_path else ""
    )
    refused = list(dict.fromkeys(spelled(t.obj) for t, _, p in reached if p != "warn"))
    stale = list(dict.fromkeys(spelled(t.obj) for t, _, p in reached if p == "warn"))
    outcomes = []
    if refused:
        outcomes.append(
            f"pg_tviews refuses {_listed(refused)} at create, since it cannot trace a write to "
            "the tree through a recursive walk (all_keys, fraiseql/pg_tviews#183)"
        )
    if stale:
        outcomes.append(
            f"under the warn policy a write to the tree leaves {_listed(stale)}'s rows stale"
        )
    tree_name = tree.relation.qualified
    return TreeWalkFinding(
        code="treekey_001",
        object_type=holder.obj.kind,
        object_name=f"{holder.obj.qualified}:{tree_name}",
        message=f"{subject} {tree_name} in a WITH RECURSIVE{through}: {'; '.join(outcomes)}",
        fix=(
            f"Walk the ancestors with a correlated a.{tree.path} @> n.{tree.path} "
            f"(treekey.register_ancestry('{tree_name}', …) generates it); or declare "
            f'"uncascaded_tables": {{"{tree_name}": "full_refresh"}} in the TVIEW\'s options, '
            'and every write to the tree rebuilds it; or "uncascaded_policy": "full_refresh" '
            "for the whole TVIEW."
        ),
        file=query.file,
        line=query.line_at(location),
    )


def _listed(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _finding(
    code: str, query: Query, obj: SchemaObject, tree: Tree, line: int, says: str
) -> TreeWalkFinding:
    return TreeWalkFinding(
        code=code,
        object_type=obj.kind,
        object_name=f"{obj.qualified}:{tree.relation.qualified}",
        message=f"{obj.qualified} {says}",
        fix=_FIX.format(tree=tree.relation.qualified, path=tree.path),
        file=query.file,
        line=line,
    )
