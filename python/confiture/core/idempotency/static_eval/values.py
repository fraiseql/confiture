"""Values the static evaluator produces, its refusal codes and their remedies."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

MAX_DEPTH = 8
"""Names and helpers a single argument may resolve through before refusal."""
_RECEIVER_NAMES = frozenset({"self", "cls"})
_PATH_CTORS = frozenset({"Path"})
_PATH_MODULES = frozenset({"pathlib"})
_PURE_STR_METHODS = frozenset(
    {"replace", "strip", "lstrip", "rstrip", "upper", "lower", "format", "join"}
)
"""``str`` methods that are total functions of static inputs. A whitelist,
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


REMEDIES: dict[Refusal, str] = {
    Refusal.PARAMETER: (
        "Give each SQL text the parameter can carry its own module constant, or read it "
        "with self.execute_file(<path>)."
    ),
    Refusal.OTHER_BINDING: (
        'Bind the SQL once with a plain assignment (NAME = "…") at module scope, or read '
        "it with self.execute_file(<path>)."
    ),
    Refusal.MULTIPLE_BINDINGS: (
        "Bind the SQL once: give each value its own constant instead of reassigning the name."
    ),
    Refusal.CONDITIONAL_BINDING: (
        "Move the assignment out of the block so the value is unconditional, or give each "
        "branch its own constant."
    ),
    Refusal.GLOBAL_REBIND: (
        "Drop the `global` reassignment; a constant the gate can read is never reassigned."
    ),
    Refusal.UNBOUND: "Define the name in this file as a module constant; only this file is read.",
    Refusal.ATTRIBUTE_STORE: (
        "Keep the SQL in the class body and never assign self.<name>, or hoist it to a "
        "module constant."
    ),
    Refusal.NOT_CLASS_ATTRIBUTE: (
        "Bind the attribute once in the class body, or hoist the SQL to a module constant."
    ),
    Refusal.NON_STRING: "Pass a string; the analyzer reads SQL text, not other literals.",
    Refusal.FSTRING_DYNAMIC: (
        "Parameterise at the DDL level, or hoist the static parts into module constants "
        "and execute one constant per statement."
    ),
    Refusal.FSTRING_FORMAT: (
        "Drop the conversion or format spec; a plain {name} over a static string resolves."
    ),
    Refusal.UNSUPPORTED_CALL: (
        "Only Path(...), .read_text(), dedent() and the str methods replace/strip/upper/"
        "lower/format/join are resolved; move the SQL into a constant or a file read."
    ),
    Refusal.UNSUPPORTED: (
        "Build the SQL from literals, constants, +, f-strings and Path arithmetic; "
        "anything else is not read."
    ),
    Refusal.HELPER_SHAPE: (
        "Reduce the helper to a single `return <expression>` with no decorators, or read "
        "the file with self.execute_file(<path>) at the call site."
    ),
    Refusal.HELPER_ARGUMENTS: "Call the helper with exactly the arguments its signature declares.",
    Refusal.DEPTH: (
        f"Flatten the chain: fewer than {MAX_DEPTH} names or helpers between the call and the text."
    ),
    Refusal.CYCLE: "Break the self-reference; a constant cannot be defined in terms of itself.",
    Refusal.SUBSCRIPT: "Index with a literal, or give each entry its own constant.",
    Refusal.READ_TEXT_RECEIVER: (
        "Build the path from Path(__file__) and module constants, or use self.execute_file(<path>)."
    ),
    Refusal.FILE_MISSING: "Create the file or fix the path; the message lists every base tried.",
    Refusal.FILE_ESCAPED: "Keep SQL files inside the project root.",
    Refusal.SCOPE_UNAVAILABLE: (
        "The file uses a construct the scope analysis could not pair with the AST; move the "
        "SQL into a module constant."
    ),
}
"""What rewrite makes a refused call readable, per :class:`Refusal`.

Lives next to the codes so a new code cannot ship without one — the guard
test enumerates the enum and asserts a remedy for every member. Under
``--fail-on-unanalyzable`` these lines are what the person fixing the
migration sees.
"""


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


class _ScopeMismatch(Exception):
    """A scope-creating node this module does not know how to name."""
