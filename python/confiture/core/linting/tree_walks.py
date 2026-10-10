"""How a view walks a pg_treekey tree (#676): ``treekey_001`` and ``treekey_002``.

A tree is a table whose ltree path pg_treekey maintains, declared by a
``treekey.manage_path(table, pk_col, parent_fk_col[, path_col])`` call in the tree.
pg_tviews follows a view's dependencies to decide which TVIEW rows a write
refreshes, and how the view walks the tree decides what it can follow:

- ``treekey_001``: a ``WITH RECURSIVE`` whose CTE body names the parent key —
  pg_tviews reads it as ``all_keys``, so every write rebuilds the whole TVIEW
  (fraiseql/pg_tviews#183);
- ``treekey_002``: ``unnest(…)`` or ``string_to_array(…)`` over the path — in a
  CTE pg_tviews refuses the view as unlinked (fraiseql/pg_tviews#196).

Both are judged on every view, materialized view and TVIEW that reads a tree
directly, as ``treekey.lint_views()`` judges the views a database holds: a view
reading a flagged view is not reported again. The spelling pg_tviews traces row
by row is a correlated ``a.path @> n.path``, which ``treekey.register_ancestry()``
generates.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from confiture.core.ddl_walk import constant_text, walk_nodes
from confiture.core.linting.inventory import Inventory, SchemaObject, split_names
from confiture.core.linting.tview_reads import Query, ReadGraph
from confiture.core.schema_identity import identifier_identity
from confiture.core.schema_model import RelationName
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
    findings: list[TreeWalkFinding] = []
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
        recursive = _recursive_walk(nodes, tree.parent_fk)
        if recursive is not None:
            yield _finding(
                "treekey_001",
                query,
                obj,
                tree,
                line_at(recursive),
                f"walks the tree {tree.relation.qualified} with WITH RECURSIVE over "
                f"{tree.parent_fk}: pg_tviews reads it as all_keys, so every write to the tree "
                "rebuilds every row of a TVIEW reading it (fraiseql/pg_tviews#183)",
            )
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


def _recursive_walk(nodes: list[Any], parent_fk: str) -> int | None:
    """Where a ``WITH RECURSIVE`` CTE body names *parent_fk* first, or ``None``."""
    for node in nodes:
        clause = getattr(node, "withClause", None) if type(node).__name__ == "SelectStmt" else None
        if clause is None or not clause.recursive:
            continue
        for cte in clause.ctes or ():
            location = _names_column(cte.ctequery, parent_fk)
            if location is not None:
                return location
    return None


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
