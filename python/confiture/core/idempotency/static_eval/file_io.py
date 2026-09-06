"""Reading a SQL file the shared resolver confines to the project root."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

from confiture.core.idempotency.static_eval.scope import _Context, _Scope
from confiture.core.idempotency.static_eval.values import PathV, Refusal, Str, Unknown, Value
from confiture.core.sql_path import resolve_sql_file

if TYPE_CHECKING:
    from confiture.core.idempotency.static_eval.evaluator import ModuleModel


class _FileIOMixin:
    """Methods :class:`~confiture.core.idempotency.static_eval.evaluator.ModuleModel` mixes in."""

    def read_file(self: ModuleModel, value: Str | PathV, *, described: str) -> Str | Unknown:
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

    def _eval_read_text(
        self: ModuleModel, node: ast.Call, func: ast.Attribute, scope: _Scope, ctx: _Context
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
