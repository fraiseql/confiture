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

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import pglast.parser

from confiture.core.ddl_walk import constant_text, tview_calls, tview_query_tree, walk_nodes
from confiture.core.linting.inventory import (
    Inventory,
    SchemaObject,
    group_definitions,
    kept,
    object_from_statement,
    split_names,
)
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
    built = {(obj.file, obj.offset) for obj in map(kept, group_definitions(inventory.objects))}
    findings: list[TreeWalkFinding] = []
    for parsed in files:
        for obj, root, line_at in _definitions(parsed, inventory, built, unread):
            findings.extend(_walks(parsed, obj, root, line_at, trees))
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


_LineAt = Callable[[int | None], int]


def _definitions(
    parsed: ParsedFile,
    inventory: Inventory,
    built: set[tuple[str | None, int]],
    unread: list[str],
) -> Iterator[tuple[SchemaObject, Any, _LineAt]]:
    """Each view, materialized view and TVIEW the build keeps: its query, and how to place a node."""
    text = parsed.text
    for raw in parsed.statements:
        obj = object_from_statement(text, raw)
        if obj is not None and obj.kind in ("view", "matview", "tview"):
            if (parsed.label, parsed.base + obj.offset) in built:
                obj.file = parsed.label
                yield obj, raw.stmt.query, lambda at: _line(text, at)
            continue
        if obj is not None:
            continue
        for call in tview_calls(raw.stmt):
            if call.action == "drop" or call.name is None or call.written is None:
                continue
            tview = next(
                (
                    o
                    for o in inventory.find_all(("tview",), call.schema, call.name)
                    if o.file == parsed.label
                ),
                None,
            )
            if tview is None:
                continue
            written = call.written
            try:
                root = tview_query_tree(written)
            except pglast.parser.ParseError, IndexError:
                # Not read, so not judged: tree_walks() names it as unread.
                unread.append(f"{tview.qualified} (its query does not parse)")
                continue
            first = _line(text, call.written_at)
            yield tview, root, lambda at, w=written, f=first: f + w.count("\n", 0, at or 0)


def _walks(
    parsed: ParsedFile, obj: SchemaObject, root: Any, line_at: _LineAt, trees: list[Tree]
) -> Iterator[TreeWalkFinding]:
    nodes = list(walk_nodes(root))
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
                parsed,
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
                parsed,
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
    code: str, parsed: ParsedFile, obj: SchemaObject, tree: Tree, line: int, says: str
) -> TreeWalkFinding:
    return TreeWalkFinding(
        code=code,
        object_type=obj.kind,
        object_name=f"{obj.qualified}:{tree.relation.qualified}",
        message=f"{obj.qualified} {says}",
        fix=_FIX.format(tree=tree.relation.qualified, path=tree.path),
        file=parsed.label,
        line=line,
    )


def _line(text: str, location: int | None) -> int:
    if location is None or location < 0:
        return 1
    return text.count("\n", 0, min(location, len(text))) + 1
