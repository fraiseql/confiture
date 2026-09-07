"""Statically extract SQL from Confiture Python migrations.

Parses a ``.py`` migration with the stdlib :mod:`ast` module and returns
every SQL string that can be resolved from ``self.execute(...)`` and
``self.execute_file(...)`` calls. Calls whose argument can't be statically
resolved produce structured warnings that say *why*, never silent passes.

What "can be resolved" means is defined once, in
:mod:`confiture.core.idempotency.static_eval`: literals, names bound once in
the scope that reads them, ``__file__`` path arithmetic, static f-strings,
pure string operations, one-line reader helpers, and file reads through the
project-root-confined resolver shared with the runtime.

The extractor never imports or executes the migration file.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from confiture.core.idempotency.static_eval import (
    REMEDIES,
    ModuleModel,
    PathV,
    Refusal,
    Str,
    Unknown,
)
from confiture.core.sql_path import find_project_root

_RECEIVER_NAMES = frozenset({"self", "cls"})


def is_migration_file(path: Path) -> bool:
    """Match the Confiture .py migration naming convention.

    Migrations start with a digit (timestamp YYYYMMDDHHmmSS or numeric
    NNN_ prefix). Files starting with ``_`` (e.g. ``__init__.py``,
    ``_helpers.py``) are excluded — those are package machinery, not
    migrations.
    """
    if not path.is_file() or path.suffix != ".py":
        return False
    if path.name.startswith("_"):
        return False
    return path.stem[:1].isdigit()


class ExtractionKind(Enum):
    """How a SQL snippet was extracted."""

    INLINE = "inline"
    INLINE_FSTRING = "fstring"
    FILE = "file"


@dataclass(frozen=True)
class ExtractedSQL:
    """A SQL fragment statically extracted from a Python migration.

    Attributes:
        sql: The text the migration hands to ``execute``.
        source_file: The migration.
        source_line: The line of the ``self.execute`` / ``self.execute_file``
            call — what the user greps for, and what the 0.12.1 contract pins.
        kind: How the text was obtained: a literal, an f-string, or a file.
        sql_file: The file read, for ``FILE`` snippets.
        resolved_via: Names walked to reach the text, in resolution order
            (``("DDL",)`` for the #213 shape; ``()`` for a literal at the
            call site). Added in 0.46.0.
        definition_line: Where the first of those names is bound, so a
            finding can point at the constant as well as the call. Added in
            0.46.0.
    """

    sql: str
    source_file: Path
    source_line: int
    kind: ExtractionKind
    sql_file: Path | None = None
    resolved_via: tuple[str, ...] = ()
    definition_line: int | None = None


class WarningKind(Enum):
    """Reasons the extractor refused to extract a call's SQL."""

    DYNAMIC_EXECUTE = "dynamic_execute"
    DYNAMIC_EXECUTE_FILE = "dynamic_execute_file"
    DYNAMIC_READ_TEXT = "dynamic_read_text"
    UNRESOLVED_FSTRING = "unresolved_fstring"
    EXECUTE_FILE_MISSING = "execute_file_missing"
    EXECUTE_FILE_ESCAPED = "execute_file_escaped"
    SYNTAX_ERROR = "syntax_error"
    UNPARSEABLE_SQL = "unparseable_sql"


@dataclass(frozen=True)
class ExtractionWarning:
    """A structured signal that a call could not be statically analyzed.

    Attributes:
        kind: The category, stable across releases (its value is JSON-visible).
        source_file: The migration.
        source_line: The line of the call.
        message: What was refused and why, naming the construct and line.
        reason_code: The evaluator's :class:`~static_eval.Refusal` value, or
            ``""`` for a syntax error. Added in 0.46.0; remedies key on it.
        remedy: The rewrite that makes the call readable. Added in 0.46.0.
    """

    kind: WarningKind
    source_file: Path
    source_line: int
    message: str
    reason_code: str = ""
    remedy: str = ""


@dataclass(frozen=True)
class ExtractionResult:
    """Result of parsing a single ``.py`` migration."""

    snippets: list[ExtractedSQL]
    warnings: list[ExtractionWarning]


def _first_sql_argument(call: ast.Call, *, kwarg_name: str) -> ast.expr | None:
    """Return the SQL/path argument for an execute / execute_file call.

    Prefers positional arg 0; falls back to keyword ``kwarg_name`` (``sql``
    for ``execute``, ``path`` for ``execute_file``).
    """
    if call.args:
        return call.args[0]
    for kw in call.keywords:
        if kw.arg == kwarg_name:
            return kw.value
    return None


def _snippet(value: Str, *, arg: ast.expr, call: ast.Call, path: Path, trace) -> ExtractedSQL:
    if value.from_file is not None:
        kind = ExtractionKind.FILE
    elif value.is_fstring or isinstance(arg, ast.JoinedStr):
        kind = ExtractionKind.INLINE_FSTRING
    else:
        kind = ExtractionKind.INLINE
    return ExtractedSQL(
        sql=value.text,
        source_file=path,
        source_line=call.lineno,
        kind=kind,
        sql_file=value.from_file,
        resolved_via=trace.names,
        definition_line=trace.definition_line,
    )


def _warning(
    refusal: Unknown, *, arg: ast.expr, call: ast.Call, path: Path, method: str
) -> ExtractionWarning:
    """Turn an evaluator refusal into the extractor's warning vocabulary.

    The seven kinds are a JSON-visible contract and stay as they were; the
    message now carries the evaluator's reason, and ``reason_code`` its
    category.
    """
    if refusal.hint == "file_missing":
        kind, message = WarningKind.EXECUTE_FILE_MISSING, refusal.reason
    elif refusal.hint == "file_escaped":
        kind, message = WarningKind.EXECUTE_FILE_ESCAPED, refusal.reason
    elif method == "execute_file":
        kind = WarningKind.DYNAMIC_EXECUTE_FILE
        message = (
            f"self.execute_file() path was not resolved statically — {refusal.reason}; "
            "SQL file was not scanned"
        )
    elif refusal.hint == "fstring" or isinstance(arg, ast.JoinedStr):
        kind = WarningKind.UNRESOLVED_FSTRING
        message = (
            f"self.execute() f-string was not resolved statically — {refusal.reason}; "
            "SQL was not scanned"
        )
    elif refusal.hint == "read_text":
        kind = WarningKind.DYNAMIC_READ_TEXT
        message = (
            f"self.execute(...read_text()) path was not resolved statically — "
            f"{refusal.reason}; SQL file was not scanned. Build the path from "
            "Path(__file__) and module constants, or use self.execute_file(<path>)."
        )
    else:
        kind = WarningKind.DYNAMIC_EXECUTE
        message = (
            f"self.execute() argument was not resolved statically — {refusal.reason}; "
            "SQL was not scanned"
        )
    return ExtractionWarning(
        kind=kind,
        source_file=path,
        source_line=call.lineno,
        message=message,
        reason_code=refusal.code.value,
        remedy=REMEDIES[refusal.code],
    )


def extract_sql_from_python_source(
    text: str,
    *,
    path: Path,
    project_root: Path | None = None,
) -> ExtractionResult:
    """Statically extract SQL from the source of a Confiture Python migration.

    The primitive: takes the text rather than reading it, so a staged blob or
    a file at a git ref is analyzed as the file it *will be* — ``__file__``
    and migration-relative reads resolve against ``path``, not a temp file.

    Args:
        text: The migration source. Parsed, never imported.
        path: Where that source lives (or will live).
        project_root: Boundary directory for file reads; paths that resolve
            outside it are refused with ``EXECUTE_FILE_ESCAPED``. Defaults to
            the nearest ancestor of ``path`` carrying ``pyproject.toml``,
            ``.git`` or ``db/``.

    Returns:
        :class:`ExtractionResult` with one snippet per resolvable call and one
        warning per call that was not.

    Never raises on syntactically invalid input — returns a SYNTAX_ERROR
    warning and an empty snippet list instead.
    """
    snippets: list[ExtractedSQL] = []
    warnings: list[ExtractionWarning] = []
    effective_root = project_root if project_root is not None else find_project_root(path)

    try:
        model = ModuleModel(text, path=path, project_root=effective_root)
    except SyntaxError as exc:
        warnings.append(
            ExtractionWarning(
                kind=WarningKind.SYNTAX_ERROR,
                source_file=path,
                source_line=exc.lineno or 0,
                message=f"Could not parse migration: {exc.msg}",
                remedy="Fix the Python; nothing in this file was read.",
            )
        )
        return ExtractionResult(snippets=snippets, warnings=warnings)

    for call, scope in model.execute_calls():
        assert isinstance(call.func, ast.Attribute)  # execute_calls() filtered on it
        method = call.func.attr
        kwarg_name = "sql" if method == "execute" else "path"
        first = _first_sql_argument(call, kwarg_name=kwarg_name)
        if first is None:
            continue
        value, trace = model.evaluate(first, scope)

        if method == "execute_file" and isinstance(value, (Str, PathV)):
            value = model.read_file(value, described=f"execute_file({ast.unparse(first)})")
        if isinstance(value, Str):
            snippets.append(_snippet(value, arg=first, call=call, path=path, trace=trace))
        elif isinstance(value, Unknown):
            warnings.append(_warning(value, arg=first, call=call, path=path, method=method))
        else:
            # A path or a sequence where SQL text was expected — e.g.
            # ``self.execute(Path(...))`` without the read.
            not_text = Unknown(
                Refusal.UNSUPPORTED,
                f"`{ast.unparse(first)}` evaluates to a {type(value).__name__.lower()}, not SQL text",
            )
            warnings.append(_warning(not_text, arg=first, call=call, path=path, method=method))

    snippets.sort(key=lambda s: s.source_line)
    return ExtractionResult(snippets=snippets, warnings=warnings)


def extract_sql_from_python_migration(
    path: Path,
    *,
    project_root: Path | None = None,
) -> ExtractionResult:
    """Statically extract SQL from a Confiture Python migration on disk.

    Reads ``path`` and delegates to :func:`extract_sql_from_python_source`;
    see it for the arguments and the contract.
    """
    return extract_sql_from_python_source(
        path.read_text(encoding="utf-8"), path=path, project_root=project_root
    )
