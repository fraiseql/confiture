"""Every file a migration reads: each read site, and the paths it can open (#540, #538).

``evaluate`` answers what SQL a call hands over, so a loop variable is a refusal
there: one call, many texts, no single answer. The question here is which files
a read can open, and a loop over a sequence the file fixes has an answer, one path
per item. So :meth:`file_reads` binds a ``for`` target to each item in turn, and
only here: a target bound once in its scope, over an iterable the grammar
evaluates to a sequence. Anything else evaluates as ``evaluate`` would, and is
refused with the same reason.

Nothing is read from disk: a site's values are the paths, not the files' text.
"""

from __future__ import annotations

import ast
import dataclasses
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from confiture.core.idempotency.static_eval.scope import _Scope
from confiture.core.idempotency.static_eval.values import (
    _RECEIVER_NAMES,
    Refusal,
    Seq,
    Unknown,
    Value,
)

if TYPE_CHECKING:
    from confiture.core.idempotency.static_eval.evaluator import ModuleModel

MAX_FAN_OUT = 256
"""Paths one read site may fan out to before it is refused."""

_READ_METHODS = frozenset({"read_text", "read_bytes"})
_OPEN_MODULES = frozenset({"io", "os", "codecs"})
_LOOPS = (ast.For, ast.AsyncFor)


@dataclass(frozen=True)
class FileReadSite:
    """One call that reads a file, and the paths it can open.

    Attributes:
        call: The call: ``p.read_text()``, ``p.read_bytes()``, ``open(p)``,
            ``p.open()`` or ``self.execute_file(p)``.
        line: The call's line.
        values: One path per file it can open (``PathV``, or a ``Str`` holding
            a path), or a single ``Unknown`` saying why the path is not static.
    """

    call: ast.Call
    line: int
    values: tuple[Value, ...]


def _argument(call: ast.Call, keyword: str) -> ast.expr | None:
    if call.args:
        return call.args[0]
    return next((kw.value for kw in call.keywords if kw.arg == keyword), None)


def _read_target(call: ast.Call) -> ast.expr | None:
    """The expression naming the file ``call`` reads, or ``None`` when it reads none."""
    func = call.func
    if isinstance(func, ast.Name):
        return _argument(call, "file") if func.id == "open" else None
    if not isinstance(func, ast.Attribute):
        return None
    receiver = func.value
    on_self = isinstance(receiver, ast.Name) and receiver.id in _RECEIVER_NAMES
    if func.attr == "execute_file":
        return _argument(call, "path") if on_self else None
    if on_self:
        return None
    if func.attr in _READ_METHODS:
        return receiver
    if func.attr == "open":
        if isinstance(receiver, ast.Name) and receiver.id in _OPEN_MODULES:
            return _argument(call, "file")
        return receiver
    return None


class _FileReadsMixin:
    """Methods :class:`~confiture.core.idempotency.static_eval.evaluator.ModuleModel` mixes in."""

    def file_reads(self: ModuleModel) -> Iterator[FileReadSite]:
        """Every read site in the file, in source order, with the paths it can open."""
        for call, scope in sorted(
            self._calls, key=lambda pair: (pair[0].lineno, pair[0].col_offset)
        ):
            target = _read_target(call)
            if target is None:
                continue
            values = self._fan_out(target, scope, self._enclosing_loops(call, scope))
            if len(values) > MAX_FAN_OUT:
                values = [
                    Unknown(
                        Refusal.DEPTH,
                        f"the loops around line {call.lineno} name more than "
                        f"{MAX_FAN_OUT} files; not enumerated",
                    )
                ]
            yield FileReadSite(call=call, line=call.lineno, values=tuple(values))

    def _enclosing_loops(
        self: ModuleModel, call: ast.Call, scope: _Scope
    ) -> list[ast.For | ast.AsyncFor]:
        """The ``for`` loops of ``scope`` whose body holds ``call``, outermost first."""
        if self._parents is None:
            self._parents = {
                id(child): parent
                for parent in ast.walk(self.tree)
                for child in ast.iter_child_nodes(parent)
            }
        loops: list[ast.For | ast.AsyncFor] = []
        child: ast.AST = call
        parent = self._parents.get(id(child))
        while parent is not None and parent is not scope.node:
            if isinstance(parent, _LOOPS) and any(child is stmt for stmt in parent.body):
                loops.append(parent)
            child, parent = parent, self._parents.get(id(parent))
        return loops[::-1]

    def _fan_out(
        self: ModuleModel, target: ast.expr, scope: _Scope, loops: list[ast.For | ast.AsyncFor]
    ) -> list[Value]:
        if not loops:
            value, _trace = self.evaluate(target, scope)
            return [value]
        loop, inner = loops[0], loops[1:]
        items = self._loop_items(loop, scope)
        if items is None:
            return self._fan_out(target, scope, inner)
        name, values = items
        fanned: list[Value] = []
        for item in values:
            bound = dataclasses.replace(scope, env={**scope.env, name: item})
            fanned.extend(self._fan_out(target, bound, inner))
        return fanned

    def _loop_items(
        self: ModuleModel, loop: ast.For | ast.AsyncFor, scope: _Scope
    ) -> tuple[str, tuple[Value, ...]] | None:
        """``(target, items)`` when ``loop`` binds one name, once, over a static sequence."""
        if not isinstance(loop.target, ast.Name):
            return None
        name = loop.target.id
        bindings = scope.bindings.get(name, [])
        if len(bindings) != 1 or bindings[0].form != "for" or name in scope.env:
            return None
        iterable, _trace = self.evaluate(loop.iter, scope)
        if not isinstance(iterable, Seq):
            return None
        return name, iterable.items
