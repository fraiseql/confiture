"""Scoping: bindings, ``symtable``-driven scope collection and name lookup."""

from __future__ import annotations

import ast
import symtable
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from confiture.core.idempotency.static_eval.values import (
    _RECEIVER_NAMES,
    MAX_DEPTH,
    Refusal,
    Seq,
    Str,
    Trace,
    Unknown,
    Value,
)

if TYPE_CHECKING:
    from confiture.core.idempotency.static_eval.evaluator import ModuleModel


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
    table: symtable.SymbolTable | None  # None once scope pairing has failed
    parent: _Scope | None
    bindings: dict[str, list[_Binding]] = field(default_factory=dict)
    env: dict[str, Value] = field(default_factory=dict)

    @property
    def display(self) -> str:
        if self.kind == "module":
            return "module scope"
        if isinstance(self.node, ast.ClassDef):
            return f"class {self.node.name}"
        if isinstance(self.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return f"{self.node.name}()"
        if isinstance(self.node, ast.Lambda):
            return "a lambda"
        return "a comprehension"

    def enclosing_class(self) -> _Scope | None:
        scope: _Scope | None = self
        while scope is not None:
            if scope.kind == "class":
                return scope
            scope = scope.parent
        return None


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
# PEP 709 (Python 3.12) inlines list, set and dict comprehensions into the
# enclosing scope: ``symtable`` emits no child table for them, and their
# targets are symbols of the enclosing table. Generator expressions keep their
# own table on every version. The walker still gives an inlined comprehension
# its own ``_Scope`` — a comprehension target is a binding the evaluator
# refuses — but pairs that scope with the *enclosing* table instead of
# consuming a symtable child that does not exist.
_INLINED_COMPREHENSIONS: tuple[type[ast.AST], ...] = (
    (ast.ListComp, ast.SetComp, ast.DictComp) if sys.version_info >= (3, 12) else ()
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
        for kinds, handler in self._STATEMENT_HANDLERS:
            if isinstance(stmt, kinds):
                handler(self, stmt, top_level)
                return
        self._type_alias(stmt, top_level)

    def _store(
        self, target: ast.expr, kind: str, lineno: int, *, top_level: bool, **extra: Any
    ) -> None:
        """Every name ``target`` binds, and the attribute it stores to if it is one."""
        stored = _attribute_store(target)
        if stored is not None:
            self.attribute_stores.add(stored)
        for name in _store_names(target):
            self.add(name.id, kind, lineno, top_level=top_level, **extra)

    def _assign(self, stmt: ast.Assign, top_level: bool) -> None:
        simple = len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name)
        for target in stmt.targets:
            self._store(
                target,
                "assign" if isinstance(target, ast.Name) else "unpack",
                stmt.lineno,
                top_level=top_level,
                value=stmt.value,
                simple=simple,
            )

    def _ann_assign(self, stmt: ast.AnnAssign, top_level: bool) -> None:
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

    def _aug_assign(self, stmt: ast.AugAssign, top_level: bool) -> None:
        self._store(stmt.target, "augassign", stmt.lineno, top_level=top_level)

    def _for(self, stmt: ast.For | ast.AsyncFor, top_level: bool) -> None:
        self._store(stmt.target, "for", stmt.lineno, top_level=top_level)
        self.statements(stmt.body, top_level=False)
        self.statements(stmt.orelse, top_level=False)

    def _block(self, stmt: ast.While | ast.If, _top_level: bool) -> None:
        self.statements(stmt.body, top_level=False)
        self.statements(stmt.orelse, top_level=False)

    def _with(self, stmt: ast.With | ast.AsyncWith, top_level: bool) -> None:
        for item in stmt.items:
            if item.optional_vars is not None:
                self._store(item.optional_vars, "with", stmt.lineno, top_level=top_level)
        self.statements(stmt.body, top_level=False)

    def _try(self, stmt: Any, top_level: bool) -> None:
        self.statements(stmt.body, top_level=False)
        for handler in stmt.handlers:
            if handler.name:
                self.add(handler.name, "except", handler.lineno, top_level=top_level)
            self.statements(handler.body, top_level=False)
        self.statements(stmt.orelse, top_level=False)
        self.statements(stmt.finalbody, top_level=False)

    def _import(self, stmt: ast.Import | ast.ImportFrom, top_level: bool) -> None:
        for alias in stmt.names:
            if alias.name == "*":
                continue
            self.add(
                alias.asname or alias.name.split(".")[0],
                "import",
                stmt.lineno,
                top_level=top_level,
            )

    def _def(self, stmt: ast.FunctionDef | ast.AsyncFunctionDef, top_level: bool) -> None:
        self.add(stmt.name, "def", stmt.lineno, top_level=top_level, node=stmt)

    def _class(self, stmt: ast.ClassDef, top_level: bool) -> None:
        self.add(stmt.name, "class", stmt.lineno, top_level=top_level, node=stmt)

    def _global(self, stmt: ast.Global, top_level: bool) -> None:
        for name in stmt.names:
            self.add(name, "global", stmt.lineno, top_level=top_level)

    def _nonlocal(self, stmt: ast.Nonlocal, top_level: bool) -> None:
        for name in stmt.names:
            self.add(name, "nonlocal", stmt.lineno, top_level=top_level)

    def _delete(self, stmt: ast.Delete, top_level: bool) -> None:
        for target in stmt.targets:
            for name in _store_names(target):
                self.add(name.id, "del", stmt.lineno, top_level=top_level)

    def _match(self, stmt: ast.Match, top_level: bool) -> None:
        for case in stmt.cases:
            for name in _pattern_captures(case.pattern):
                self.add(name, "match", case.pattern.lineno, top_level=top_level)
            self.statements(case.body, top_level=False)

    def _type_alias(self, stmt: ast.stmt, top_level: bool) -> None:
        # `type X = ...` (3.12+); the node is absent from 3.11's stubs.
        type_alias = getattr(ast, "TypeAlias", None)
        if type_alias is not None and isinstance(stmt, type_alias):
            alias_name = getattr(stmt, "name", None)
            if isinstance(alias_name, ast.Name):
                self.add(alias_name.id, "typealias", stmt.lineno, top_level=top_level)

    # Statement node types → the method that records their bindings, in the
    # order the ``elif`` chain used to try them.
    _STATEMENT_HANDLERS: tuple[tuple[tuple[type, ...], Any], ...] = (
        ((ast.Assign,), _assign),
        ((ast.AnnAssign,), _ann_assign),
        ((ast.AugAssign,), _aug_assign),
        ((ast.For, ast.AsyncFor), _for),
        ((ast.While, ast.If), _block),
        ((ast.With, ast.AsyncWith), _with),
        (tuple(t for t in (ast.Try, getattr(ast, "TryStar", None)) if t is not None), _try),
        ((ast.Import, ast.ImportFrom), _import),
        ((ast.FunctionDef, ast.AsyncFunctionDef), _def),
        ((ast.ClassDef,), _class),
        ((ast.Global,), _global),
        ((ast.Nonlocal,), _nonlocal),
        ((ast.Delete,), _delete),
        ((ast.Match,), _match),
    )

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


def _parameter_defaults(args: ast.arguments, params: list[str]) -> dict[str, ast.expr]:
    """Each parameter's default expression, positional and keyword-only."""
    defaults: dict[str, ast.expr] = {}
    if args.defaults:
        defaults.update(zip(params[len(params) - len(args.defaults) :], args.defaults, strict=True))
    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        if default is not None:
            defaults[arg.arg] = default
    return defaults


class _ScopeLookupMixin:
    """Methods :class:`~confiture.core.idempotency.static_eval.evaluator.ModuleModel` mixes in."""

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
        self: ModuleModel,
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
        defaults = _parameter_defaults(args, params)

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
        bound = self._bind_keywords(call, env, (*params, *kwonly), scope, ctx, name=name)
        if bound is not None:
            return bound
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

    def _bind_keywords(
        self: ModuleModel,
        call: ast.Call,
        env: dict[str, Value],
        accepted: tuple[str, ...],
        scope: _Scope,
        ctx: _Context,
        *,
        name: str,
    ) -> Unknown | None:
        """Bind the call's keywords into ``env``; the refusal when one cannot be."""
        for keyword in call.keywords:
            if keyword.arg is None:
                return Unknown(Refusal.HELPER_ARGUMENTS, f"`{name}(**...)` is not static")
            if keyword.arg in env or keyword.arg not in accepted:
                return Unknown(
                    Refusal.HELPER_ARGUMENTS,
                    f"`{name}()` got an unexpected keyword `{keyword.arg}`",
                )
            value = self._eval(keyword.value, scope, ctx)
            if isinstance(value, Unknown):
                return value
            env[keyword.arg] = value
        return None

    def _lookup_free(self: ModuleModel, name: str, scope: _Scope, ctx: _Context) -> Value:
        """A free variable: the nearest enclosing function that binds it, or unbound."""
        enclosing = scope.parent
        while enclosing is not None:
            if enclosing.kind == "function" and enclosing.table is not None:
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

    def _lookup_name(self: ModuleModel, name: str, scope: _Scope, ctx: _Context) -> Value:
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
        assert scope.table is not None  # scopes_ok guarantees a paired table
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
            return self._lookup_free(name, scope, ctx)
        return self._module_binding(name, ctx)

    def _module_binding(self: ModuleModel, name: str, ctx: _Context) -> Value:
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

    def _global_rebinding_site(self: ModuleModel, name: str) -> str:
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Global) and name in stmt.names:
                        return f"{node.name}() at line {stmt.lineno}"
        return "a function"

    def _single_binding(self: ModuleModel, name: str, scope: _Scope, ctx: _Context) -> Value | None:
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

    def _lookup_class_attribute(
        self: ModuleModel, name: str, scope: _Scope, ctx: _Context
    ) -> Value:
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
