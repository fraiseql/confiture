"""Statically extract SQL from Confiture Python migrations.

Parses a ``.py`` migration with the stdlib :mod:`ast` module and returns
every SQL string we can resolve from ``self.execute(...)`` and
``self.execute_file(...)`` calls. Calls whose argument can't be statically
resolved produce structured warnings, never silent passes.

The extractor never imports or executes the migration file. It calls
:func:`ast.parse` on the text and walks the resulting tree.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

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
    """A SQL fragment statically extracted from a Python migration."""

    sql: str
    source_file: Path
    source_line: int
    kind: ExtractionKind
    sql_file: Path | None = None


class WarningKind(Enum):
    """Reasons the extractor refused to extract a call's SQL."""

    DYNAMIC_EXECUTE = "dynamic_execute"
    DYNAMIC_EXECUTE_FILE = "dynamic_execute_file"
    DYNAMIC_READ_TEXT = "dynamic_read_text"
    UNRESOLVED_FSTRING = "unresolved_fstring"
    EXECUTE_FILE_MISSING = "execute_file_missing"
    EXECUTE_FILE_ESCAPED = "execute_file_escaped"
    SYNTAX_ERROR = "syntax_error"


@dataclass(frozen=True)
class ExtractionWarning:
    """A structured signal that a call could not be statically analyzed."""

    kind: WarningKind
    source_file: Path
    source_line: int
    message: str


@dataclass(frozen=True)
class ExtractionResult:
    """Result of parsing a single ``.py`` migration."""

    snippets: list[ExtractedSQL]
    warnings: list[ExtractionWarning]


def _is_execute_call(node: ast.Call) -> str | None:
    """Return ``"execute"`` / ``"execute_file"`` for self.<method> calls, else None."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    if not isinstance(func.value, ast.Name) or func.value.id not in _RECEIVER_NAMES:
        return None
    if func.attr in {"execute", "execute_file"}:
        return func.attr
    return None


def _resolve_string_arg(node: ast.expr) -> tuple[str | None, bool]:
    """Statically resolve a string-typed AST expression.

    Returns ``(value, is_fstring)``. ``value`` is None when the expression
    cannot be resolved to a literal string; ``is_fstring`` is True when the
    expression originated from an f-string (even if fully static).
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value, False
        return None, False
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                return None, True
        return "".join(parts), True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, left_fstring = _resolve_string_arg(node.left)
        right, right_fstring = _resolve_string_arg(node.right)
        if left is not None and right is not None:
            return left + right, left_fstring or right_fstring
        return None, left_fstring or right_fstring
    return None, False


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


_PROJECT_ROOT_ANCHORS = ("pyproject.toml", ".git", "db")


def _resolve_project_root(migration_path: Path) -> Path:
    """Walk up from the migration file to find a project root anchor."""
    start = migration_path.parent.resolve()
    for ancestor in (start, *start.parents):
        for anchor in _PROJECT_ROOT_ANCHORS:
            if (ancestor / anchor).exists():
                return ancestor
    return start


def _resolve_sql_path(
    raw: str,
    migration_path: Path,
    project_root: Path,
    source_line: int,
    call_desc: str | None = None,
) -> tuple[Path | None, ExtractionWarning | None]:
    """Resolve a literal SQL-file path against the project boundary.

    The single boundary for every shape that names a file on disk —
    ``execute_file(...)`` and ``execute(Path(...).read_text())`` alike. Keeping
    one implementation is the point: a second resolution path would be a
    path-traversal regression against the v0.8.4 hardening, so the read_text
    shape routes here rather than reading the file itself.

    Args:
        raw: The literal path as written in the migration.
        migration_path: The migration being analyzed (warning provenance, and
            the fallback resolution base).
        project_root: Confinement boundary; anything resolving outside is refused.
        source_line: Line of the call, for the warning.
        call_desc: How to name the call in warnings. Defaults to the
            ``execute_file(...)`` wording.

    Returns:
        ``(resolved_path, None)`` or ``(None, warning)``.
    """
    described = call_desc or f"execute_file({raw!r})"
    raw_path = Path(raw)
    candidate = raw_path if raw_path.is_absolute() else Path.cwd() / raw_path
    if not candidate.exists():
        # Fall back to resolution relative to the migration file's parent.
        fallback = migration_path.parent / raw_path
        if fallback.exists():
            candidate = fallback
    resolved = candidate.resolve()
    root = project_root.resolve()
    if not resolved.is_relative_to(root):
        return None, ExtractionWarning(
            kind=WarningKind.EXECUTE_FILE_ESCAPED,
            source_file=migration_path,
            source_line=source_line,
            message=(f"{described} resolves outside project_root ({root}); refusing to read"),
        )
    if not resolved.is_file():
        return None, ExtractionWarning(
            kind=WarningKind.EXECUTE_FILE_MISSING,
            source_file=migration_path,
            source_line=source_line,
            message=f"{described} not found on disk (looked at {resolved})",
        )
    return resolved, None


def _read_text_literal_path(node: ast.expr) -> tuple[str | None, bool]:
    """Recognise ``Path("<literal>").read_text()`` inside ``self.execute(...)`` (#185).

    Migrations that keep their SQL in a file but call ``execute`` rather than
    ``execute_file`` were reported as unanalyzable dynamic SQL, so the
    idempotency gate passed them without ever reading the statements. Exactly
    one shape is recognised — ``Path`` (or ``pathlib.Path``) applied to a string
    **literal**, with ``read_text()`` taking no positional arguments:

        self.execute(Path("db/schema/fn.sql").read_text())
        self.execute(Path("db/schema/fn.sql").read_text(encoding="utf-8"))

    Anything else (a variable, a ``/``-joined expression, a module constant) is
    reported rather than evaluated. Evaluating user expressions to find a path
    is a different and much larger commitment than matching a literal, and
    ``execute_file`` already covers those cases with full resolution.

    Returns:
        ``(literal_path, is_read_text_call)``. The second element is True for
        any ``….read_text(...)`` call, so the caller can tell "path shape we
        will not resolve" apart from "not a path shape at all".
    """
    if not isinstance(node, ast.Call):
        return None, False
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "read_text":
        return None, False
    if node.args:  # read_text() takes only keywords (encoding/errors)
        return None, True

    receiver = func.value
    if not isinstance(receiver, ast.Call) or len(receiver.args) != 1:
        return None, True
    ctor = receiver.func
    is_path_ctor = (isinstance(ctor, ast.Name) and ctor.id == "Path") or (
        isinstance(ctor, ast.Attribute) and ctor.attr == "Path"
    )
    if not is_path_ctor:
        return None, True

    arg = receiver.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value, True
    return None, True


def _extract_read_text_file(
    raw: str,
    migration_path: Path,
    project_root: Path,
    source_line: int,
) -> tuple[ExtractedSQL | None, ExtractionWarning | None]:
    """Resolve and read a literal ``Path(...).read_text()`` target.

    Deliberately routes through :func:`_resolve_sql_path`, so this shape gets
    ``execute_file``'s project-root confinement and its
    ``EXECUTE_FILE_ESCAPED`` / ``EXECUTE_FILE_MISSING`` signals — same boundary,
    same vocabulary, one implementation.
    """
    resolved, warn = _resolve_sql_path(
        raw,
        migration_path,
        project_root,
        source_line,
        call_desc=f"execute(Path({raw!r}).read_text())",
    )
    if warn is not None:
        return None, warn
    assert resolved is not None
    return (
        ExtractedSQL(
            sql=resolved.read_text(encoding="utf-8"),
            source_file=migration_path,
            source_line=source_line,
            kind=ExtractionKind.FILE,
            sql_file=resolved,
        ),
        None,
    )


def _emit_execute_warning(
    node: ast.Call,
    path: Path,
    is_fstring: bool,
) -> ExtractionWarning:
    if is_fstring:
        return ExtractionWarning(
            kind=WarningKind.UNRESOLVED_FSTRING,
            source_file=path,
            source_line=node.lineno,
            message=(
                "self.execute() called with an f-string containing "
                "non-literal parts; SQL was not scanned"
            ),
        )
    return ExtractionWarning(
        kind=WarningKind.DYNAMIC_EXECUTE,
        source_file=path,
        source_line=node.lineno,
        message="self.execute() called with a non-literal argument; SQL was not scanned",
    )


def extract_sql_from_python_migration(
    path: Path,
    *,
    project_root: Path | None = None,
) -> ExtractionResult:
    """Statically extract SQL from a Confiture Python migration.

    Args:
        path: The ``.py`` migration file to parse.
        project_root: Boundary directory for ``execute_file`` resolution.
            Paths that resolve outside this root are rejected with an
            ``EXECUTE_FILE_ESCAPED`` warning. Defaults to the nearest
            ancestor of ``path`` containing ``pyproject.toml``, ``.git``,
            or ``db/``; falls back to ``path.parent`` if no anchor is found.

    Returns:
        :class:`ExtractionResult` with one snippet per resolvable call.

    Never raises on syntactically invalid input — returns a SYNTAX_ERROR
    warning and an empty snippet list instead.
    """
    snippets: list[ExtractedSQL] = []
    warnings: list[ExtractionWarning] = []
    effective_root = project_root if project_root is not None else _resolve_project_root(path)

    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        warnings.append(
            ExtractionWarning(
                kind=WarningKind.SYNTAX_ERROR,
                source_file=path,
                source_line=exc.lineno or 0,
                message=f"Could not parse migration: {exc.msg}",
            )
        )
        return ExtractionResult(snippets=snippets, warnings=warnings)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        method = _is_execute_call(node)
        if method is None:
            continue
        kwarg_name = "sql" if method == "execute" else "path"
        first = _first_sql_argument(node, kwarg_name=kwarg_name)
        if first is None:
            continue
        value, is_fstring = _resolve_string_arg(first)

        if method == "execute":
            if value is not None:
                snippets.append(
                    ExtractedSQL(
                        sql=value,
                        source_file=path,
                        source_line=node.lineno,
                        kind=(
                            ExtractionKind.INLINE_FSTRING if is_fstring else ExtractionKind.INLINE
                        ),
                    )
                )
                continue
            literal, is_read_text = _read_text_literal_path(first)
            if literal is not None:
                snippet, warn = _extract_read_text_file(literal, path, effective_root, node.lineno)
                if warn is not None:
                    warnings.append(warn)
                else:
                    assert snippet is not None
                    snippets.append(snippet)
            elif is_read_text:
                warnings.append(
                    ExtractionWarning(
                        kind=WarningKind.DYNAMIC_READ_TEXT,
                        source_file=path,
                        source_line=node.lineno,
                        message=(
                            "self.execute(...read_text()) with a non-literal path; SQL file was "
                            "not scanned. Use self.execute_file(<path>) — it resolves computed "
                            "paths and is analyzed."
                        ),
                    )
                )
            else:
                warnings.append(_emit_execute_warning(node, path, is_fstring))
        else:  # method == "execute_file"
            if value is None:
                warnings.append(
                    ExtractionWarning(
                        kind=WarningKind.DYNAMIC_EXECUTE_FILE,
                        source_file=path,
                        source_line=node.lineno,
                        message=(
                            "self.execute_file() called with a non-literal path; "
                            "SQL file was not scanned"
                        ),
                    )
                )
                continue
            resolved, warn = _resolve_sql_path(value, path, effective_root, node.lineno)
            if warn is not None:
                warnings.append(warn)
                continue
            assert resolved is not None
            snippets.append(
                ExtractedSQL(
                    sql=resolved.read_text(encoding="utf-8"),
                    source_file=path,
                    source_line=node.lineno,
                    kind=ExtractionKind.FILE,
                    sql_file=resolved,
                )
            )

    snippets.sort(key=lambda s: s.source_line)
    return ExtractionResult(snippets=snippets, warnings=warnings)
