"""The evaluator: :class:`ModuleModel` walks one migration file and evaluates expressions."""

from __future__ import annotations

import ast
import symtable
import textwrap
from collections.abc import Iterator
from pathlib import Path

from confiture.core.idempotency.static_eval.file_io import _FileIOMixin
from confiture.core.idempotency.static_eval.scope import (
    _INLINED_COMPREHENSIONS,
    _BindingCollector,
    _Context,
    _Scope,
    _ScopeLookupMixin,
    _store_names,
)
from confiture.core.idempotency.static_eval.str_methods import _StrMethodsMixin
from confiture.core.idempotency.static_eval.values import (
    _PURE_STR_METHODS,
    _RECEIVER_NAMES,
    MAX_DEPTH,
    PathV,
    Refusal,
    Seq,
    Str,
    Trace,
    Unknown,
    Value,
    _expected_table_name,
    _is_dedent,
    _is_path_constructor,
    _ScopeMismatch,
)


class ModuleModel(_ScopeLookupMixin, _StrMethodsMixin, _FileIOMixin):
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
        top: symtable.SymbolTable | None
        try:
            top = symtable.symtable(text, str(path), "exec")
        except SyntaxError:
            # ast.parse accepted it, so this is a symtable-only complaint
            # (e.g. `nonlocal` at module level). Every name lookup will
            # refuse; every call is still found.
            self.scopes_ok = False
            top = None
        self.module = _Scope("module", self.tree, top, None)
        self._build(self.module)
        if top is not None:
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

        children = (
            list(scope.table.get_children()) if self.scopes_ok and scope.table is not None else []
        )
        with_own_table = [n for n in nested if not isinstance(n, _INLINED_COMPREHENSIONS)]
        if self.scopes_ok and len(children) != len(with_own_table):
            self.scopes_ok = False
        index = 0
        for child_node in nested:
            table: symtable.SymbolTable | None = scope.table
            if isinstance(child_node, _INLINED_COMPREHENSIONS):
                # Inlined (PEP 709): its names live in the enclosing table.
                pass
            elif self.scopes_ok:
                candidate = children[index]
                index += 1
                expected = _expected_table_name(child_node)
                if candidate.get_name() == expected and candidate.get_lineno() == child_node.lineno:
                    table = candidate
                else:
                    # Pairing failed: from here on every name lookup refuses
                    # (SCOPE_UNAVAILABLE), but the walk continues so that every
                    # call is still found — an unpaired file must never become
                    # a silent pass.
                    self.scopes_ok = False
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

    @staticmethod
    def enclosing_function(scope: _Scope) -> str | None:
        """The name of the nearest enclosing ``def`` of ``scope``, or ``None`` at module/class level."""
        current: _Scope | None = scope
        while current is not None:
            if current.kind == "function" and isinstance(
                current.node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                return current.node.name
            current = current.parent
        return None

    def evaluate(self, expr: ast.expr, scope: _Scope) -> tuple[Value, Trace]:
        """Evaluate ``expr`` as read from ``scope``. Never raises."""
        ctx = _Context()
        value = self._eval(expr, scope, ctx)
        return value, ctx.trace()

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
