"""Static evaluation of what ``self.execute(...)`` / ``self.execute_file(...)`` receive.

The idempotency gate can only judge SQL it has read. A Python migration hands
its SQL to ``execute`` as an expression, and before 0.46.0 only three shapes
were read — a literal, a static f-string, a literal concatenation — so a
``CREATE TABLE`` hoisted into a module constant was invisible to the gate
(#213). This module evaluates the expression instead, for every form that is
a *pure function of the migration file's own text*, and refuses everything
else with the reason.

**Never imports, never executes.** ``ast`` supplies the tree, ``symtable``
supplies the interpreter's own scoping decisions, and the only side effect
is reading a SQL file that the shared resolver has confined to the project
root.

The grammar
===========

Values are ``Str`` (text, possibly read from a file), ``PathV`` (a path, made
concrete only when read), ``Seq`` (for ``*parts`` and ``.join``), or
``Unknown`` (a refusal carrying a :class:`Refusal` code and a sentence).

============================================== ======================================================
Expression                                     Value
============================================== ======================================================
``"…"``                                        ``Str``
``f"… {x} …"``                                 ``Str`` when every placeholder is a ``Str`` with no
                                               conversion and no format spec
``a + b``                                      ``Str`` when both sides are
``p / q``                                      ``PathV`` when ``p`` is one
``__file__``                                   this migration's path
``NAME``                                       scope lookup, below
``self.NAME`` / ``cls.NAME``                   class-attribute lookup, below
``p.parent``, ``p.parents[N]``                 ``PathV``
``Path(...)``, ``pathlib.Path(...)``           ``PathV`` joined from ``Str``/``PathV``/``*Seq`` args
``p.resolve()``, ``p.absolute()``              the same ``PathV``
``p.joinpath(...)``                            ``PathV``
``p.read_text(...)``                           ``Str`` from the file the shared resolver names
``s.replace/strip/lstrip/rstrip/upper/lower``  ``Str`` (static arguments only)
``s.format(...)``, ``sep.join(seq)``           ``Str`` (static arguments only)
``dedent(s)``, ``textwrap.dedent(s)``          ``Str``
``str(p)``                                     ``Str``
``(a, b)``, ``[a, b]``                         ``Seq``
``f(...)``, ``self.m(...)``                    a one-line reader helper, below
============================================== ======================================================

**Scope lookup** — a name resolves when it is bound *exactly once* in the
scope that reads it, by a plain assignment, at the top level of that scope,
to an expression in this grammar, and no other scope can rebind it at
runtime. Which scope reads it is decided by :mod:`symtable`, the compiler's
own analysis, so parameters, loop and ``with`` targets, comprehension
targets, walrus bindings, imports and nested ``def``\\ s all count as
bindings without anyone maintaining a list. A ``global NAME`` plus an
assignment in any function refuses the module constant. A class attribute of
the same name does **not** shadow a module name inside a method — Python
does not look there either.

**Class-attribute lookup** — ``self.NAME`` resolves when ``NAME`` is bound
once in the class body and nothing anywhere in the file assigns
``self.NAME`` / ``cls.NAME`` or calls ``setattr`` on ``self``.

**Reader helpers** — a module-level ``def`` (or a method reached through
``self``) whose body is an optional docstring plus one ``return <expr>``;
no decorators. Parameters are bound from the call, ``*parts`` becomes a
``Seq``, defaults evaluate in the helper's own scope.

Depth is capped at :data:`MAX_DEPTH` names-or-helpers; cycles are refused.
Under-resolving is a warning the CLI shows with the reason; over-resolving
would be a wrong verdict, which is why every rule here errs toward refusal.
"""

from __future__ import annotations

import ast
import symtable
import textwrap
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from confiture.core.sql_path import resolve_sql_file

MAX_DEPTH = 8
"""Names and helpers a single argument may resolve through before refusal."""

_RECEIVER_NAMES = frozenset({"self", "cls"})
_PATH_CTORS = frozenset({"Path"})
_PATH_MODULES = frozenset({"pathlib"})
_PURE_STR_METHODS = frozenset(
    {"replace", "strip", "lstrip", "rstrip", "upper", "lower", "format", "join"}
)
"""``str`` methods that are total functions of static inputs (D9). A whitelist,
not a blacklist: anything else on a string is refused by name."""


class Refusal(str, Enum):
    """Why an expression was not evaluated. Stable codes; remedies key on them."""

    PARAMETER = "parameter"
    OTHER_BINDING = "bound_by_statement"
    MULTIPLE_BINDINGS = "multiple_bindings"
    CONDITIONAL_BINDING = "conditional_binding"
    GLOBAL_REBIND = "global_rebind"
    UNBOUND = "unbound"
    ATTRIBUTE_STORE = "attribute_store"
    NOT_CLASS_ATTRIBUTE = "not_class_attribute"
    NON_STRING = "non_string"
    FSTRING_DYNAMIC = "fstring_dynamic"
    FSTRING_FORMAT = "fstring_format"
    UNSUPPORTED_CALL = "unsupported_call"
    UNSUPPORTED = "unsupported_expression"
    HELPER_SHAPE = "helper_shape"
    HELPER_ARGUMENTS = "helper_arguments"
    DEPTH = "depth"
    CYCLE = "cycle"
    SUBSCRIPT = "subscript"
    READ_TEXT_RECEIVER = "read_text_receiver"
    FILE_MISSING = "file_missing"
    FILE_ESCAPED = "file_escaped"
    SCOPE_UNAVAILABLE = "scope_unavailable"


# --------------------------------------------------------------------------- #
# Values                                                                        #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Str:
    """A string the migration will hand to ``execute``.

    Attributes:
        text: The value.
        from_file: The file it was read from, when the whole value is one
            ``read_text()`` (possibly through pure string operations).
        is_fstring: Whether an f-string contributed to it — the
            ``ExtractionKind.INLINE_FSTRING`` provenance older callers expect.
    """

    text: str
    from_file: Path | None = None
    is_fstring: bool = False


@dataclass(frozen=True)
class PathV:
    """A path expression, kept symbolic until something reads it.

    Relative paths stay relative so the shared resolver can try the project
    root first; ``.resolve()`` in the migration is therefore a no-op here.
    """

    path: Path


@dataclass(frozen=True)
class Seq:
    """A tuple/list of values — ``*parts`` in a helper, or ``sep.join(seq)``."""

    items: tuple[Value, ...]


@dataclass(frozen=True)
class Unknown:
    """A refusal: the expression is not a pure function of the file's text.

    Attributes:
        code: The :class:`Refusal` category.
        reason: One sentence a person can act on, naming the name or
            construct and, where it exists, the line.
        hint: How the extractor should classify the warning — ``"fstring"``,
            ``"read_text"``, ``"file_missing"`` or ``"file_escaped"``; ``None``
            for a plain dynamic argument.
    """

    code: Refusal
    reason: str
    hint: str | None = None


Value = Str | PathV | Seq | Unknown


@dataclass(frozen=True)
class Trace:
    """Provenance of one evaluation: the names walked, in resolution order."""

    names: tuple[str, ...] = ()
    definition_line: int | None = None


# --------------------------------------------------------------------------- #
# Scope model                                                                   #
# --------------------------------------------------------------------------- #


@dataclass
class _Binding:
    form: str
    lineno: int
    value: ast.expr | None
    simple: bool
    top_level: bool
    node: ast.AST | None = None  # the def/class statement, for helper lookup


_FORM_TEXT = {
    "assign": "a plain assignment",
    "unpack": "tuple unpacking",
    "annassign": "an annotated assignment",
    "annotation": "an annotation without a value",
    "augassign": "an augmented assignment",
    "for": "a `for` target",
    "with": "a `with ... as` target",
    "except": "an `except ... as` name",
    "import": "an import",
    "def": "a `def`",
    "class": "a `class`",
    "global": "a `global` declaration",
    "nonlocal": "a `nonlocal` declaration",
    "del": "a `del`",
    "match": "a `match` capture",
    "walrus": "a `:=` assignment",
    "typealias": "a `type` alias",
    "parameter": "a parameter",
    "comprehension": "a comprehension target",
}


@dataclass
class _Scope:
    kind: str  # "module" | "class" | "function"
    node: ast.AST | None
    table: symtable.SymbolTable
    parent: _Scope | None
    bindings: dict[str, list[_Binding]] = field(default_factory=dict)
    env: dict[str, Value] = field(default_factory=dict)

    @property
    def display(self) -> str:
        if self.kind == "module":
            return "module scope"
        if self.kind == "class":
            return f"class {self.table.get_name()}"
        name = self.table.get_name()
        if name in {"listcomp", "setcomp", "dictcomp", "genexpr"}:
            return "a comprehension"
        if name == "lambda":
            return "a lambda"
        return f"{name}()"

    def enclosing_class(self) -> _Scope | None:
        scope: _Scope | None = self
        while scope is not None:
            if scope.kind == "class":
                return scope
            scope = scope.parent
        return None


class _ScopeMismatch(Exception):
    """The AST's nested scopes and symtable's children did not line up."""


def _store_names(target: ast.expr) -> list[ast.Name]:
    """Every ``Name`` bound by an assignment target (tuples, lists, stars)."""
    if isinstance(target, ast.Name):
        return [target]
    if isinstance(target, ast.Starred):
        return _store_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[ast.Name] = []
        for element in target.elts:
            names.extend(_store_names(element))
        return names
    return []


def _attribute_store(target: ast.expr) -> str | None:
    """``self.X`` / ``cls.X`` as an assignment target → ``"X"``."""
    if isinstance(target, ast.Starred):
        return _attribute_store(target.value)
    if (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id in _RECEIVER_NAMES
    ):
        return target.attr
    return None


def _pattern_captures(pattern: ast.pattern) -> list[str]:
    names: list[str] = []
    for node in ast.walk(pattern):
        if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names.append(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.append(node.rest)
    return names


_SCOPE_NODES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


class _BindingCollector:
    """Collect every binding a scope's statements make, without entering nested scopes."""

    def __init__(self) -> None:
        self.bindings: dict[str, list[_Binding]] = {}
        self.attribute_stores: set[str] = set()
        self.setattr_on_self = False

    def add(
        self,
        name: str,
        form: str,
        lineno: int,
        *,
        value: ast.expr | None = None,
        simple: bool = False,
        top_level: bool,
        node: ast.AST | None = None,
    ) -> None:
        self.bindings.setdefault(name, []).append(
            _Binding(
                form=form,
                lineno=lineno,
                value=value,
                simple=simple,
                top_level=top_level,
                node=node,
            )
        )

    def statements(self, stmts: list[ast.stmt], *, top_level: bool) -> None:
        for stmt in stmts:
            self.statement(stmt, top_level=top_level)

    def statement(self, stmt: ast.stmt, *, top_level: bool) -> None:
        self.expressions_in(stmt, top_level=top_level)
        if isinstance(stmt, ast.Assign):
            simple = len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name)
            for target in stmt.targets:
                stored = _attribute_store(target)
                if stored is not None:
                    self.attribute_stores.add(stored)
                for name in _store_names(target):
                    self.add(
                        name.id,
                        "assign" if isinstance(target, ast.Name) else "unpack",
                        stmt.lineno,
                        value=stmt.value,
                        simple=simple,
                        top_level=top_level,
                    )
        elif isinstance(stmt, ast.AnnAssign):
            stored = _attribute_store(stmt.target)
            if stored is not None:
                self.attribute_stores.add(stored)
            if isinstance(stmt.target, ast.Name):
                self.add(
                    stmt.target.id,
                    "annassign" if stmt.value is not None else "annotation",
                    stmt.lineno,
                    value=stmt.value,
                    simple=stmt.value is not None,
                    top_level=top_level,
                )
        elif isinstance(stmt, ast.AugAssign):
            stored = _attribute_store(stmt.target)
            if stored is not None:
                self.attribute_stores.add(stored)
            for name in _store_names(stmt.target):
                self.add(name.id, "augassign", stmt.lineno, top_level=top_level)
        elif isinstance(stmt, (ast.For, ast.AsyncFor)):
            stored = _attribute_store(stmt.target)
            if stored is not None:
                self.attribute_stores.add(stored)
            for name in _store_names(stmt.target):
                self.add(name.id, "for", stmt.lineno, top_level=top_level)
            self.statements(stmt.body, top_level=False)
            self.statements(stmt.orelse, top_level=False)
        elif isinstance(stmt, (ast.While, ast.If)):
            self.statements(stmt.body, top_level=False)
            self.statements(stmt.orelse, top_level=False)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            for item in stmt.items:
                if item.optional_vars is not None:
                    stored = _attribute_store(item.optional_vars)
                    if stored is not None:
                        self.attribute_stores.add(stored)
                    for name in _store_names(item.optional_vars):
                        self.add(name.id, "with", stmt.lineno, top_level=top_level)
            self.statements(stmt.body, top_level=False)
        elif isinstance(stmt, ast.Try) or (
            hasattr(ast, "TryStar") and isinstance(stmt, ast.TryStar)
        ):
            self.statements(stmt.body, top_level=False)
            for handler in stmt.handlers:
                if handler.name:
                    self.add(handler.name, "except", handler.lineno, top_level=top_level)
                self.statements(handler.body, top_level=False)
            self.statements(stmt.orelse, top_level=False)
            self.statements(stmt.finalbody, top_level=False)
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                self.add(
                    alias.asname or alias.name.split(".")[0],
                    "import",
                    stmt.lineno,
                    top_level=top_level,
                )
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.add(stmt.name, "def", stmt.lineno, top_level=top_level, node=stmt)
        elif isinstance(stmt, ast.ClassDef):
            self.add(stmt.name, "class", stmt.lineno, top_level=top_level, node=stmt)
        elif isinstance(stmt, ast.Global):
            for name in stmt.names:
                self.add(name, "global", stmt.lineno, top_level=top_level)
        elif isinstance(stmt, ast.Nonlocal):
            for name in stmt.names:
                self.add(name, "nonlocal", stmt.lineno, top_level=top_level)
        elif isinstance(stmt, ast.Delete):
            for target in stmt.targets:
                for name in _store_names(target):
                    self.add(name.id, "del", stmt.lineno, top_level=top_level)
        elif isinstance(stmt, ast.Match):
            for case in stmt.cases:
                for name in _pattern_captures(case.pattern):
                    self.add(name, "match", case.pattern.lineno, top_level=top_level)
                self.statements(case.body, top_level=False)
        else:
            # `type X = ...` (3.12+); the node is absent from 3.11's stubs.
            type_alias = getattr(ast, "TypeAlias", None)
            if type_alias is not None and isinstance(stmt, type_alias):
                alias_name = getattr(stmt, "name", None)
                if isinstance(alias_name, ast.Name):
                    self.add(alias_name.id, "typealias", stmt.lineno, top_level=top_level)

    def expressions_in(self, stmt: ast.stmt, *, top_level: bool) -> None:
        """Walrus bindings and ``setattr(self, …)`` in a statement's expressions.

        Comprehensions are entered (a walrus inside one binds in the enclosing
        function); lambdas and nested defs are not.
        """
        stack: list[ast.AST] = [stmt]
        while stack:
            node = stack.pop()
            for child in ast.iter_child_nodes(node):
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
                ):
                    continue
                if isinstance(child, ast.NamedExpr) and isinstance(child.target, ast.Name):
                    self.add(child.target.id, "walrus", child.lineno, top_level=top_level)
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == "setattr"
                    and child.args
                    and isinstance(child.args[0], ast.Name)
                    and child.args[0].id in _RECEIVER_NAMES
                ):
                    self.setattr_on_self = True
                stack.append(child)

    def parameters(self, args: ast.arguments, lineno: int) -> None:
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            self.add(arg.arg, "parameter", lineno, top_level=True)
        for arg in (args.vararg, args.kwarg):
            if arg is not None:
                self.add(arg.arg, "parameter", lineno, top_level=True)


@dataclass
class _Context:
    """Per-evaluation state: depth, cycle guard, provenance."""

    depth: int = 0
    in_progress: set[tuple[int, str]] = field(default_factory=set)
    helpers: set[int] = field(default_factory=set)
    names: list[str] = field(default_factory=list)
    definition_line: int | None = None

    def trace(self) -> Trace:
        return Trace(names=tuple(self.names), definition_line=self.definition_line)


class ModuleModel:
    """One parsed migration: its scopes, its bindings, and an evaluator over them.

    Args:
        text: The migration source. Parsed, never imported.
        path: Where that source lives — the value of ``__file__`` and the
            second base for relative file reads. For a staged blob this is
            the path the blob *will* have, not a temp file.
        project_root: The first base for relative file reads and the
            confinement boundary.

    Raises:
        SyntaxError: The text does not parse. The extractor turns this into
            its ``syntax_error`` warning; nothing else can raise.
    """

    def __init__(self, text: str, *, path: Path, project_root: Path) -> None:
        self.path = path
        self.project_root = project_root
        self.tree = ast.parse(text, filename=str(path))
        self._calls: list[tuple[ast.Call, _Scope]] = []
        self._scope_of: dict[int, _Scope] = {}
        self._attribute_stores: set[str] = set()
        self._setattr_on_self = False
        self._global_rebinders: set[str] = set()
        self._nonlocal_rebinders: set[str] = set()
        self.scopes_ok = True
        try:
            top = symtable.symtable(text, str(path), "exec")
        except SyntaxError:
            # ast.parse accepted it, so this is a symtable-only complaint
            # (e.g. `nonlocal` at module level). Evaluate without scopes.
            self.scopes_ok = False
            top = symtable.symtable("", str(path), "exec")
        self.module = _Scope("module", self.tree, top, None)
        try:
            self._build(self.module)
        except _ScopeMismatch:
            self.scopes_ok = False
        self._collect_rebinders(top)

    # -- construction -------------------------------------------------------

    def _build(self, scope: _Scope) -> None:
        """Collect this scope's bindings and calls; pair its nested scopes with symtable's."""
        node = scope.node
        collector = _BindingCollector()
        if isinstance(node, ast.Module):
            body: list[ast.AST] = list(node.body)
            collector.statements(node.body, top_level=True)
        elif isinstance(node, ast.ClassDef):
            body = list(node.body)
            collector.statements(node.body, top_level=True)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = list(node.body)
            collector.parameters(node.args, node.lineno)
            collector.statements(node.body, top_level=True)
        elif isinstance(node, ast.Lambda):
            body = [node.body]
            collector.parameters(node.args, node.lineno)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            body = []
            for index, generator in enumerate(node.generators):
                for name in _store_names(generator.target):
                    collector.add(name.id, "comprehension", node.lineno, top_level=True)
                if index > 0:
                    body.append(generator.iter)
                body.extend(generator.ifs)
            if isinstance(node, ast.DictComp):
                body.extend([node.key, node.value])
            else:
                body.append(node.elt)
        else:  # pragma: no cover — every scope node is listed above
            raise _ScopeMismatch(type(node).__name__)
        scope.bindings = collector.bindings
        self._attribute_stores |= collector.attribute_stores
        self._setattr_on_self = self._setattr_on_self or collector.setattr_on_self

        nested: list[ast.stmt | ast.expr] = []
        for child in body:
            self._walk(child, scope, nested)

        children = scope.table.get_children()
        if len(children) != len(nested):
            raise _ScopeMismatch(f"{scope.display}: {len(nested)} scopes vs {len(children)} tables")
        for child_node, table in zip(nested, children, strict=True):
            expected = _expected_table_name(child_node)
            if table.get_name() != expected or table.get_lineno() != child_node.lineno:
                raise _ScopeMismatch(
                    f"{expected}@{child_node.lineno} vs {table.get_name()}@{table.get_lineno()}"
                )
            kind = "class" if isinstance(child_node, ast.ClassDef) else "function"
            child_scope = _Scope(kind, child_node, table, scope)
            self._scope_of[id(child_node)] = child_scope
            self._build(child_scope)

    def _walk(self, node: ast.AST, scope: _Scope, nested: list[ast.stmt | ast.expr]) -> None:
        """Visit ``node`` in ``scope``, registering nested scopes in symtable's order.

        symtable visits a function's defaults, annotations and decorators —
        and a class's bases and decorators, and a comprehension's first
        iterator — in the *enclosing* scope before entering the nested block,
        so their nested scopes precede the block's own table.
        """
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for expr in (*node.args.defaults, *node.args.kw_defaults):
                if expr is not None:
                    self._walk(expr, scope, nested)
            for arg in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
                node.args.vararg,
                node.args.kwarg,
            ):
                if arg is not None and arg.annotation is not None:
                    self._walk(arg.annotation, scope, nested)
            if node.returns is not None:
                self._walk(node.returns, scope, nested)
            for expr in node.decorator_list:
                self._walk(expr, scope, nested)
            nested.append(node)
            return
        if isinstance(node, ast.ClassDef):
            for expr in (*node.bases, *(kw.value for kw in node.keywords), *node.decorator_list):
                self._walk(expr, scope, nested)
            nested.append(node)
            return
        if isinstance(node, ast.Lambda):
            for expr in (*node.args.defaults, *node.args.kw_defaults):
                if expr is not None:
                    self._walk(expr, scope, nested)
            nested.append(node)
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            self._walk(node.generators[0].iter, scope, nested)
            nested.append(node)
            return
        if isinstance(node, ast.Call):
            self._calls.append((node, scope))
        for child in ast.iter_child_nodes(node):
            self._walk(child, scope, nested)

    def _collect_rebinders(self, table: symtable.SymbolTable) -> None:
        for child in table.get_children():
            if child.get_type() == "function":
                for name in child.get_identifiers():
                    symbol = child.lookup(name)
                    if symbol.is_assigned() and symbol.is_declared_global():
                        self._global_rebinders.add(name)
                    if symbol.is_assigned() and symbol.is_nonlocal():
                        self._nonlocal_rebinders.add(name)
            self._collect_rebinders(child)

    # -- public surface -----------------------------------------------------

    def execute_calls(self) -> Iterator[tuple[ast.Call, _Scope]]:
        """Every ``self.execute`` / ``self.execute_file`` call, in source order, with its scope."""
        for call, scope in sorted(
            self._calls, key=lambda pair: (pair[0].lineno, pair[0].col_offset)
        ):
            func = call.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id in _RECEIVER_NAMES
                and func.attr in {"execute", "execute_file"}
            ):
                yield call, scope

    def evaluate(self, expr: ast.expr, scope: _Scope) -> tuple[Value, Trace]:
        """Evaluate ``expr`` as read from ``scope``. Never raises."""
        ctx = _Context()
        value = self._eval(expr, scope, ctx)
        return value, ctx.trace()

    def read_file(self, value: Str | PathV, *, described: str) -> Str | Unknown:
        """Read the SQL file a value names, through the shared, confined resolver."""
        raw = value.path if isinstance(value, PathV) else Path(value.text)
        resolution = resolve_sql_file(
            raw, migration_file=self.path, project_root=self.project_root, confine=True
        )
        root = self.project_root.resolve()
        if resolution.outcome == "escaped":
            return Unknown(
                Refusal.FILE_ESCAPED,
                f"{described} resolves outside project_root ({root}); refusing to read",
                hint="file_escaped",
            )
        if resolution.outcome == "missing":
            return Unknown(
                Refusal.FILE_MISSING,
                f"{described} not found on disk (looked in the project root {root}, "
                "next to the migration, and the working directory)",
                hint="file_missing",
            )
        assert resolution.path is not None
        return Str(resolution.path.read_text(encoding="utf-8"), from_file=resolution.path)

    # -- evaluation ---------------------------------------------------------

    def _eval(self, node: ast.expr, scope: _Scope, ctx: _Context) -> Value:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                return Str(node.value)
            return Unknown(
                Refusal.NON_STRING, f"a {type(node.value).__name__} literal, not a string"
            )
        if isinstance(node, ast.JoinedStr):
            return self._eval_fstring(node, scope, ctx)
        if isinstance(node, ast.BinOp):
            return self._eval_binop(node, scope, ctx)
        if isinstance(node, ast.Name):
            return self._lookup_name(node.id, scope, ctx)
        if isinstance(node, ast.Attribute):
            return self._eval_attribute(node, scope, ctx)
        if isinstance(node, ast.Subscript):
            return self._eval_subscript(node, scope, ctx)
        if isinstance(node, ast.Call):
            return self._eval_call(node, scope, ctx)
        if isinstance(node, (ast.Tuple, ast.List)):
            items: list[Value] = []
            for element in node.elts:
                if isinstance(element, ast.Starred):
                    inner = self._eval(element.value, scope, ctx)
                    if isinstance(inner, Unknown):
                        return inner
                    if not isinstance(inner, Seq):
                        return Unknown(
                            Refusal.UNSUPPORTED, "`*` on something that is not a sequence"
                        )
                    items.extend(inner.items)
                    continue
                value = self._eval(element, scope, ctx)
                if isinstance(value, Unknown):
                    return value
                items.append(value)
            return Seq(tuple(items))
        return Unknown(Refusal.UNSUPPORTED, f"{type(node).__name__} is not in the static grammar")

    def _eval_fstring(self, node: ast.JoinedStr, scope: _Scope, ctx: _Context) -> Value:
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
                continue
            if not isinstance(value, ast.FormattedValue):
                return Unknown(Refusal.UNSUPPORTED, "unexpected f-string part", hint="fstring")
            placeholder = ast.unparse(value.value)
            if value.conversion != -1 or value.format_spec is not None:
                conversion = f"!{chr(value.conversion)}" if value.conversion != -1 else ""
                spec = f":{ast.unparse(value.format_spec)}" if value.format_spec is not None else ""
                return Unknown(
                    Refusal.FSTRING_FORMAT,
                    f"f-string placeholder `{{{placeholder}{conversion}{spec}}}` uses a "
                    "conversion or format spec",
                    hint="fstring",
                )
            inner = self._eval(value.value, scope, ctx)
            if isinstance(inner, Unknown):
                return Unknown(
                    Refusal.FSTRING_DYNAMIC,
                    f"f-string interpolates `{placeholder}`, which is not static: {inner.reason}",
                    hint="fstring",
                )
            if not isinstance(inner, Str):
                return Unknown(
                    Refusal.FSTRING_DYNAMIC,
                    f"f-string interpolates `{placeholder}`, which is not a string",
                    hint="fstring",
                )
            parts.append(inner.text)
        return Str("".join(parts), is_fstring=True)

    def _eval_binop(self, node: ast.BinOp, scope: _Scope, ctx: _Context) -> Value:
        if isinstance(node.op, ast.Mod):
            return Unknown(Refusal.UNSUPPORTED, "%-formatting is not in the static grammar")
        if not isinstance(node.op, (ast.Add, ast.Div)):
            return Unknown(
                Refusal.UNSUPPORTED, f"`{type(node.op).__name__}` is not in the static grammar"
            )
        left = self._eval(node.left, scope, ctx)
        if isinstance(left, Unknown):
            return left
        right = self._eval(node.right, scope, ctx)
        if isinstance(right, Unknown):
            return right
        if isinstance(node.op, ast.Add):
            if isinstance(left, Str) and isinstance(right, Str):
                return Str(left.text + right.text, is_fstring=left.is_fstring or right.is_fstring)
            return Unknown(Refusal.UNSUPPORTED, "`+` on something that is not two strings")
        if isinstance(left, PathV) and isinstance(right, (Str, PathV)):
            tail = right.text if isinstance(right, Str) else right.path
            return PathV(left.path / tail)
        return Unknown(Refusal.UNSUPPORTED, "`/` needs a Path on the left")

    def _eval_attribute(self, node: ast.Attribute, scope: _Scope, ctx: _Context) -> Value:
        if isinstance(node.value, ast.Name) and node.value.id in _RECEIVER_NAMES:
            return self._lookup_class_attribute(node.attr, scope, ctx)
        base = self._eval(node.value, scope, ctx)
        if isinstance(base, Unknown):
            return base
        if node.attr == "parent" and isinstance(base, PathV):
            return PathV(base.path.parent)
        return Unknown(
            Refusal.UNSUPPORTED, f"attribute `.{node.attr}` is not in the static grammar"
        )

    def _eval_subscript(self, node: ast.Subscript, scope: _Scope, ctx: _Context) -> Value:
        if (
            isinstance(node.value, ast.Attribute)
            and node.value.attr == "parents"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, int)
        ):
            base = self._eval(node.value.value, scope, ctx)
            if isinstance(base, Unknown):
                return base
            if isinstance(base, PathV):
                try:
                    return PathV(base.path.parents[node.slice.value])
                except IndexError:
                    return Unknown(
                        Refusal.UNSUPPORTED, f"`.parents[{node.slice.value}]` is past the root"
                    )
        return Unknown(
            Refusal.SUBSCRIPT,
            f"subscript `{ast.unparse(node)}` is not a static path index",
        )

    def _eval_call(self, node: ast.Call, scope: _Scope, ctx: _Context) -> Value:
        func = node.func
        if _is_path_constructor(func):
            parts = self._eval_args(node, scope, ctx)
            if isinstance(parts, Unknown):
                return parts
            if not parts:
                return Unknown(Refusal.UNSUPPORTED, "`Path()` with no arguments")
            joined: Path | None = None
            for part in parts:
                if isinstance(part, Str):
                    segment = Path(part.text)
                elif isinstance(part, PathV):
                    segment = part.path
                else:
                    return Unknown(
                        Refusal.UNSUPPORTED, "`Path(...)` argument is not a string or path"
                    )
                joined = segment if joined is None else joined / segment
            assert joined is not None
            return PathV(joined)
        if isinstance(func, ast.Name) and func.id == "str" and len(node.args) == 1:
            inner = self._eval(node.args[0], scope, ctx)
            if isinstance(inner, Unknown):
                return inner
            if isinstance(inner, PathV):
                return Str(str(inner.path))
            if isinstance(inner, Str):
                return inner
            return Unknown(Refusal.UNSUPPORTED, "`str()` of something that is not a string or path")
        if _is_dedent(func):
            if len(node.args) != 1 or node.keywords:
                return Unknown(Refusal.UNSUPPORTED_CALL, "`dedent()` takes exactly one argument")
            inner = self._eval(node.args[0], scope, ctx)
            if isinstance(inner, Unknown):
                return inner
            if not isinstance(inner, Str):
                return Unknown(
                    Refusal.UNSUPPORTED_CALL, "`dedent()` of something that is not a string"
                )
            return Str(textwrap.dedent(inner.text), inner.from_file, inner.is_fstring)
        if isinstance(func, ast.Attribute):
            if func.attr == "read_text":
                return self._eval_read_text(node, func, scope, ctx)
            if func.attr in _PURE_STR_METHODS:
                return self._eval_str_method(node, func, scope, ctx)
            if func.attr in {"resolve", "absolute"} and not node.args and not node.keywords:
                base = self._eval(func.value, scope, ctx)
                if isinstance(base, Unknown):
                    return base
                if isinstance(base, PathV):
                    return base
                return Unknown(
                    Refusal.UNSUPPORTED, f"`.{func.attr}()` on something that is not a path"
                )
            if func.attr == "joinpath":
                base = self._eval(func.value, scope, ctx)
                if isinstance(base, Unknown):
                    return base
                parts = self._eval_args(node, scope, ctx)
                if isinstance(parts, Unknown):
                    return parts
                if not isinstance(base, PathV):
                    return Unknown(
                        Refusal.UNSUPPORTED, "`.joinpath()` on something that is not a path"
                    )
                joined = base.path
                for part in parts:
                    if isinstance(part, Str):
                        joined = joined / part.text
                    elif isinstance(part, PathV):
                        joined = joined / part.path
                    else:
                        return Unknown(
                            Refusal.UNSUPPORTED, "`.joinpath()` argument is not a string or path"
                        )
                return PathV(joined)
        if isinstance(func, ast.Name) or (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in _RECEIVER_NAMES
        ):
            return self._eval_helper_call(node, func, scope, ctx)
        return Unknown(
            Refusal.UNSUPPORTED_CALL,
            f"`{ast.unparse(func)}(...)` is not in the static grammar",
        )

    # -- reader helpers -------------------------------------------------------

    def _eval_helper_call(
        self, node: ast.Call, func: ast.Name | ast.Attribute, scope: _Scope, ctx: _Context
    ) -> Value:
        """``f(...)`` for a module-level def, or ``self.m(...)`` for a method.

        The helper must be an optional docstring plus one ``return <expr>``,
        undecorated, without ``**kwargs``. Its parameters are bound from the
        call site; defaults evaluate in the helper's own enclosing scope; the
        body evaluates in the helper's scope with those bindings.
        """
        if isinstance(func, ast.Name):
            name = func.id
            definition = self._top_level_def(self.module, name)
            is_method = False
            not_found = f"`{name}(...)` is not a helper defined in this file"
        else:
            name = func.attr
            owner = scope.enclosing_class()
            definition = self._top_level_def(owner, name) if owner is not None else None
            is_method = True
            not_found = f"`self.{name}(...)` is not a method defined once in the class body"
        if definition is None:
            return Unknown(Refusal.UNSUPPORTED_CALL, not_found)
        if isinstance(definition, ast.AsyncFunctionDef):
            return Unknown(Refusal.HELPER_SHAPE, f"helper `{name}()` is async")
        if definition.decorator_list:
            return Unknown(Refusal.HELPER_SHAPE, f"helper `{name}()` is decorated")
        if definition.args.kwarg is not None:
            return Unknown(Refusal.HELPER_SHAPE, f"helper `{name}()` takes **kwargs")
        body = list(definition.body)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]  # docstring
        if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
            return Unknown(
                Refusal.HELPER_SHAPE,
                f"helper `{name}()` is not a single `return <expression>` (line "
                f"{definition.lineno})",
            )
        if id(definition) in ctx.helpers:
            return Unknown(Refusal.CYCLE, f"`{name}()` is called recursively")
        if ctx.depth >= MAX_DEPTH:
            return Unknown(
                Refusal.DEPTH, f"`{name}()` is more than {MAX_DEPTH} names or helpers deep"
            )
        template = self._scope_of.get(id(definition))
        if template is None:
            return Unknown(
                Refusal.SCOPE_UNAVAILABLE,
                f"`{name}()` could not be resolved: scope analysis is unavailable",
            )
        env = self._bind_arguments(
            definition,
            node,
            scope,
            ctx,
            is_method=is_method,
            name=name,
            enclosing=template.parent or self.module,
        )
        if isinstance(env, Unknown):
            return env
        helper_scope = _Scope(
            "function", definition, template.table, template.parent, template.bindings, env
        )
        ctx.names.append(name)
        if ctx.definition_line is None:
            ctx.definition_line = definition.lineno
        ctx.helpers.add(id(definition))
        ctx.depth += 1
        try:
            return self._eval(body[0].value, helper_scope, ctx)
        finally:
            ctx.depth -= 1
            ctx.helpers.discard(id(definition))

    @staticmethod
    def _top_level_def(
        scope: _Scope | None, name: str
    ) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        if scope is None:
            return None
        bindings = scope.bindings.get(name) or []
        if len(bindings) != 1 or bindings[0].form != "def" or not bindings[0].top_level:
            return None
        node = bindings[0].node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
        return None

    def _bind_arguments(
        self,
        definition: ast.FunctionDef | ast.AsyncFunctionDef,
        call: ast.Call,
        scope: _Scope,
        ctx: _Context,
        *,
        is_method: bool,
        name: str,
        enclosing: _Scope,
    ) -> dict[str, Value] | Unknown:
        args = definition.args
        params = [a.arg for a in (*args.posonlyargs, *args.args)]
        if is_method:
            if not params:
                return Unknown(Refusal.HELPER_SHAPE, f"method `{name}()` has no self parameter")
            params = params[1:]
        kwonly = [a.arg for a in args.kwonlyargs]
        defaults: dict[str, ast.expr] = {}
        if args.defaults:
            defaults.update(
                zip(params[len(params) - len(args.defaults) :], args.defaults, strict=True)
            )
        for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
            if default is not None:
                defaults[arg.arg] = default

        positional = self._eval_args(call, scope, ctx)
        if isinstance(positional, Unknown):
            return positional
        env: dict[str, Value] = dict(zip(params, positional, strict=False))
        extra = positional[len(params) :]
        if args.vararg is not None:
            env[args.vararg.arg] = Seq(tuple(extra))
        elif extra:
            return Unknown(
                Refusal.HELPER_ARGUMENTS,
                f"`{name}()` takes {len(params)} positional argument(s) but {len(positional)} "
                "were given",
            )
        for keyword in call.keywords:
            if keyword.arg is None:
                return Unknown(Refusal.HELPER_ARGUMENTS, f"`{name}(**...)` is not static")
            if keyword.arg in env or keyword.arg not in (*params, *kwonly):
                return Unknown(
                    Refusal.HELPER_ARGUMENTS,
                    f"`{name}()` got an unexpected keyword `{keyword.arg}`",
                )
            value = self._eval(keyword.value, scope, ctx)
            if isinstance(value, Unknown):
                return value
            env[keyword.arg] = value
        for param in (*params, *kwonly):
            if param in env:
                continue
            default = defaults.get(param)
            if default is None:
                return Unknown(
                    Refusal.HELPER_ARGUMENTS, f"`{name}()` is missing argument `{param}`"
                )
            value = self._eval(default, enclosing, ctx)
            if isinstance(value, Unknown):
                return value
            env[param] = value
        return env

    def _eval_read_text(
        self, node: ast.Call, func: ast.Attribute, scope: _Scope, ctx: _Context
    ) -> Value:
        """``<path>.read_text(**kw)`` — the one grammar rule that touches the disk."""
        if node.args:
            return Unknown(
                Refusal.UNSUPPORTED_CALL,
                "`.read_text()` with positional arguments is not in the static grammar "
                "(only encoding=/errors= keywords)",
                hint="read_text",
            )
        receiver = self._eval(func.value, scope, ctx)
        if isinstance(receiver, Unknown):
            return Unknown(
                Refusal.READ_TEXT_RECEIVER,
                f"`.read_text()` receiver `{ast.unparse(func.value)}` is not a static path: "
                f"{receiver.reason}",
                hint="read_text",
            )
        if not isinstance(receiver, PathV):
            return Unknown(
                Refusal.UNSUPPORTED_CALL,
                f"`.read_text()` on `{ast.unparse(func.value)}`, which is not a path",
                hint="read_text",
            )
        return self.read_file(receiver, described=f"execute({ast.unparse(node)})")

    def _eval_str_method(
        self, node: ast.Call, func: ast.Attribute, scope: _Scope, ctx: _Context
    ) -> Value:
        """A whitelisted ``str`` method with static arguments (D9)."""
        method = func.attr
        receiver = self._eval(func.value, scope, ctx)
        if isinstance(receiver, Unknown):
            return receiver
        if not isinstance(receiver, Str):
            return Unknown(
                Refusal.UNSUPPORTED_CALL, f"`.{method}()` on something that is not a string"
            )
        count: int | None = None
        positional = list(node.args)
        if method == "replace" and len(positional) == 3:
            third = positional.pop()
            if not (isinstance(third, ast.Constant) and isinstance(third.value, int)):
                return Unknown(Refusal.UNSUPPORTED_CALL, "`.replace()` count is not an int literal")
            count = third.value
        args: list[Value] = []
        for arg in positional:
            if isinstance(arg, ast.Starred):
                inner = self._eval(arg.value, scope, ctx)
                if isinstance(inner, Unknown):
                    return inner
                if not isinstance(inner, Seq):
                    return Unknown(Refusal.UNSUPPORTED, "`*` on something that is not a sequence")
                args.extend(inner.items)
                continue
            value = self._eval(arg, scope, ctx)
            if isinstance(value, Unknown):
                return value
            args.append(value)
        kwargs: dict[str, str] = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                return Unknown(Refusal.UNSUPPORTED_CALL, f"`.{method}(**...)` is not static")
            value = self._eval(keyword.value, scope, ctx)
            if isinstance(value, Unknown):
                return value
            if not isinstance(value, Str):
                return Unknown(
                    Refusal.UNSUPPORTED_CALL,
                    f"`.{method}()` keyword `{keyword.arg}` is not a string",
                )
            kwargs[keyword.arg] = value.text

        text = receiver.text
        fstring = receiver.is_fstring
        try:
            if method == "join":
                if len(args) != 1 or kwargs or not isinstance(args[0], Seq):
                    return Unknown(
                        Refusal.UNSUPPORTED_CALL, "`.join()` needs one static sequence of strings"
                    )
                parts: list[str] = []
                for item in args[0].items:
                    if not isinstance(item, Str):
                        return Unknown(
                            Refusal.UNSUPPORTED_CALL, "`.join()` sequence holds a non-string"
                        )
                    parts.append(item.text)
                    fstring = fstring or item.is_fstring
                result = text.join(parts)
            else:
                texts: list[str] = []
                for value in args:
                    if not isinstance(value, Str):
                        return Unknown(
                            Refusal.UNSUPPORTED_CALL, f"`.{method}()` argument is not a string"
                        )
                    texts.append(value.text)
                    fstring = fstring or value.is_fstring
                if method == "replace":
                    if len(texts) != 2:
                        return Unknown(Refusal.UNSUPPORTED_CALL, "`.replace()` takes two strings")
                    result = (
                        text.replace(texts[0], texts[1])
                        if count is None
                        else text.replace(texts[0], texts[1], count)
                    )
                elif method in {"strip", "lstrip", "rstrip"}:
                    if len(texts) > 1 or kwargs:
                        return Unknown(
                            Refusal.UNSUPPORTED_CALL, f"`.{method}()` takes at most one string"
                        )
                    result = getattr(text, method)(*texts)
                elif method in {"upper", "lower"}:
                    if texts or kwargs:
                        return Unknown(
                            Refusal.UNSUPPORTED_CALL, f"`.{method}()` takes no arguments"
                        )
                    result = getattr(text, method)()
                else:  # format
                    result = text.format(*texts, **kwargs)
        except (IndexError, KeyError, ValueError) as exc:
            return Unknown(
                Refusal.UNSUPPORTED_CALL, f"`.{method}()` arguments do not fit the template: {exc}"
            )
        return Str(result, receiver.from_file, fstring)

    def _eval_args(self, node: ast.Call, scope: _Scope, ctx: _Context) -> list[Value] | Unknown:
        """Positional arguments, with ``*seq`` splatted. Keywords are the caller's business."""
        values: list[Value] = []
        for arg in node.args:
            if isinstance(arg, ast.Starred):
                inner = self._eval(arg.value, scope, ctx)
                if isinstance(inner, Unknown):
                    return inner
                if not isinstance(inner, Seq):
                    return Unknown(Refusal.UNSUPPORTED, "`*` on something that is not a sequence")
                values.extend(inner.items)
                continue
            value = self._eval(arg, scope, ctx)
            if isinstance(value, Unknown):
                return value
            values.append(value)
        return values

    # -- names --------------------------------------------------------------

    def _lookup_name(self, name: str, scope: _Scope, ctx: _Context) -> Value:
        if name in scope.env:
            return scope.env[name]
        if name == "__file__":
            return Str(str(self.path))
        if not self.scopes_ok:
            return Unknown(
                Refusal.SCOPE_UNAVAILABLE,
                f"`{name}` could not be resolved: scope analysis is unavailable for this file",
            )
        if scope.kind == "module":
            return self._module_binding(name, ctx)
        if scope.kind == "class":
            local = self._single_binding(name, scope, ctx)
            return local if local is not None else self._module_binding(name, ctx)
        try:
            symbol = scope.table.lookup(name)
        except KeyError:
            return self._module_binding(name, ctx)
        if symbol.is_parameter():
            return Unknown(Refusal.PARAMETER, f"`{name}` is a parameter of {scope.display}")
        if symbol.is_local():
            local = self._single_binding(name, scope, ctx)
            if local is not None:
                return local
            return Unknown(Refusal.UNBOUND, f"`{name}` is not defined in this file")
        if symbol.is_free():
            enclosing = scope.parent
            while enclosing is not None:
                if enclosing.kind == "function":
                    try:
                        enclosing_symbol = enclosing.table.lookup(name)
                    except KeyError:
                        enclosing_symbol = None
                    if enclosing_symbol is not None and enclosing_symbol.is_parameter():
                        return Unknown(
                            Refusal.PARAMETER, f"`{name}` is a parameter of {enclosing.display}"
                        )
                    if enclosing_symbol is not None and enclosing_symbol.is_local():
                        local = self._single_binding(name, enclosing, ctx)
                        if local is not None:
                            return local
                enclosing = enclosing.parent
            return Unknown(Refusal.UNBOUND, f"`{name}` is not defined in this file")
        return self._module_binding(name, ctx)

    def _module_binding(self, name: str, ctx: _Context) -> Value:
        if name in self._global_rebinders:
            where = self._global_rebinding_site(name)
            return Unknown(
                Refusal.GLOBAL_REBIND,
                f"`{name}` is reassigned through `global` in {where}, so its value is not fixed",
            )
        if name in self._nonlocal_rebinders:
            return Unknown(
                Refusal.GLOBAL_REBIND,
                f"`{name}` is reassigned through `nonlocal`, so its value is not fixed",
            )
        local = self._single_binding(name, self.module, ctx)
        if local is not None:
            return local
        return Unknown(Refusal.UNBOUND, f"`{name}` is not defined in this file")

    def _global_rebinding_site(self, name: str) -> str:
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Global) and name in stmt.names:
                        return f"{node.name}() at line {stmt.lineno}"
        return "a function"

    def _single_binding(self, name: str, scope: _Scope, ctx: _Context) -> Value | None:
        """The value bound to ``name`` in ``scope``, a refusal, or ``None`` when unbound there."""
        bindings = scope.bindings.get(name)
        if not bindings:
            return None
        if len(bindings) > 1:
            lines = ", ".join(str(b.lineno) for b in bindings)
            return Unknown(
                Refusal.MULTIPLE_BINDINGS,
                f"`{name}` is bound {len(bindings)} times in {scope.display} (lines {lines}); "
                "only a single binding is resolved",
            )
        binding = bindings[0]
        if (
            binding.form not in {"assign", "annassign"}
            or not binding.simple
            or binding.value is None
        ):
            return Unknown(
                Refusal.OTHER_BINDING,
                f"`{name}` is bound by {_FORM_TEXT.get(binding.form, binding.form)} at line "
                f"{binding.lineno}, not by a plain assignment",
            )
        if not binding.top_level:
            return Unknown(
                Refusal.CONDITIONAL_BINDING,
                f"`{name}` is assigned inside a block at line {binding.lineno} "
                "(if/for/while/with/try), so its value is not unconditional",
            )
        key = (id(scope), name)
        if key in ctx.in_progress:
            return Unknown(Refusal.CYCLE, f"`{name}` refers to itself (line {binding.lineno})")
        if ctx.depth >= MAX_DEPTH:
            return Unknown(
                Refusal.DEPTH,
                f"`{name}` is more than {MAX_DEPTH} names or helpers deep; not resolved",
            )
        ctx.names.append(name)
        if ctx.definition_line is None:
            ctx.definition_line = binding.lineno
        ctx.in_progress.add(key)
        ctx.depth += 1
        try:
            return self._eval(binding.value, scope, ctx)
        finally:
            ctx.depth -= 1
            ctx.in_progress.discard(key)

    def _lookup_class_attribute(self, name: str, scope: _Scope, ctx: _Context) -> Value:
        owner = scope.enclosing_class()
        if owner is None:
            return Unknown(
                Refusal.NOT_CLASS_ATTRIBUTE,
                f"`self.{name}` is read outside any class; not a class attribute",
            )
        if self._setattr_on_self:
            return Unknown(
                Refusal.ATTRIBUTE_STORE,
                f"`self.{name}` cannot be trusted: the file calls setattr() on self",
            )
        if name in self._attribute_stores:
            return Unknown(
                Refusal.ATTRIBUTE_STORE,
                f"`self.{name}` is assigned somewhere in the file, so the class attribute "
                "is not its only binding",
            )
        value = self._single_binding(name, owner, ctx)
        if value is None:
            return Unknown(
                Refusal.NOT_CLASS_ATTRIBUTE,
                f"`self.{name}` is not a class attribute bound once in the body of {owner.display}",
            )
        return value


def _expected_table_name(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Lambda):
        return "lambda"
    if isinstance(node, ast.ListComp):
        return "listcomp"
    if isinstance(node, ast.SetComp):
        return "setcomp"
    if isinstance(node, ast.DictComp):
        return "dictcomp"
    if isinstance(node, ast.GeneratorExp):
        return "genexpr"
    raise _ScopeMismatch(type(node).__name__)


def _is_dedent(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id == "dedent"
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "textwrap"
        and func.attr == "dedent"
    )


def _is_path_constructor(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id in _PATH_CTORS
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in _PATH_MODULES
        and func.attr in _PATH_CTORS
    )
