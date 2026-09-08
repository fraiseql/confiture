"""The ``qual`` family: a ``CREATE`` that names no schema (#248).

``CREATE FUNCTION fn_slugify(...)`` does not say where the function goes. The
applying role's ``search_path`` decides that at apply time, so the same file
applied by two roles produces the object in two schemas — and the one that
landed in the wrong place is found by whatever breaks next, not by the build.
``sec_002`` is the caller-side twin of the same hazard (CVE-2018-1058): there
an unqualified *reference* resolves through the caller's path.

``qual_001`` covers routines, ``qual_002`` relations and types. They are two
codes rather than one because the volume differs by an order of magnitude in an
existing project — a schema has a handful of routines and hundreds of tables —
so a project can adopt one and baseline the other.

Both read the object inventory: ``SchemaObject.schema`` is already ``None``
when the author wrote no qualifier, so there is no second parse and no regex.
A ``SET search_path`` in the file does **not** silence either rule; that is
precisely the mechanism which makes the outcome role-dependent. What does
silence one statement is ``-- confiture:unqualified-ok`` written above it, for
a file that is deliberately schema-agnostic — an extension bootstrap, a
template — the way ``-- confiture:secdef-allow-unpinned`` does for ``sec_002``.
"""

from __future__ import annotations

from collections.abc import Container, Iterable, Sequence

from confiture.core.linting.inventory import KIND_KEYWORD, SchemaObject
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity

#: ``(rule code, rule name)`` per inventory kind.
_RULES: dict[str, tuple[str, str]] = {
    "function": ("qual_001", "Unqualified Routine"),
    "procedure": ("qual_001", "Unqualified Routine"),
    "aggregate": ("qual_001", "Unqualified Routine"),
    "table": ("qual_002", "Unqualified Object"),
    "view": ("qual_002", "Unqualified Object"),
    "matview": ("qual_002", "Unqualified Object"),
    "type": ("qual_002", "Unqualified Object"),
    "domain": ("qual_002", "Unqualified Object"),
    "sequence": ("qual_002", "Unqualified Object"),
}

#: The schema named when nothing in the file says which one was meant.
_GUESS = "public"

#: The directive that opts the statement below it out of both rules.
DIRECTIVE = "unqualified-ok"

#: Routines: what ``qual_001`` judges.
ROUTINE_KINDS: frozenset[str] = frozenset(k for k, (c, _) in _RULES.items() if c == "qual_001")

#: Relations and types: what ``qual_002`` judges.
RELATION_KINDS: frozenset[str] = frozenset(k for k, (c, _) in _RULES.items() if c == "qual_002")


def _schema_before(obj: SchemaObject, schemas: Sequence[SchemaObject]) -> str | None:
    """The nearest ``CREATE SCHEMA`` above ``obj`` in ``obj``'s own file.

    A file that declares a schema and then creates things is a file that meant
    them to land there. One declared *after* the object, or in another file, is
    not evidence of anything — a fix that guesses silently is worse than none.
    """
    above = [s.name for s in schemas if s.file == obj.file and s.offset < obj.offset]
    return above[-1] if above else None


def _suggested_fix(obj: SchemaObject, schemas: Sequence[SchemaObject]) -> str:
    schema = _schema_before(obj, schemas)
    if schema is not None:
        return f"Write the name as '{schema}.{obj.name}'"
    return (
        f"Write the name as '{_GUESS}.{obj.name}' — '{_GUESS}' is a guess, "
        "no CREATE SCHEMA precedes it in this file"
    )


def _finding(obj: SchemaObject, schemas: Sequence[SchemaObject]) -> LintViolation:
    code, rule_name = _RULES[obj.kind]
    return LintViolation(
        rule_id=code,
        rule_name=rule_name,
        severity=RuleSeverity.WARNING,
        object_type=obj.kind,
        object_name=obj.identity,
        message=(
            f"{KIND_KEYWORD[obj.kind].capitalize()} '{obj.identity}' is created without a "
            "schema; which schema it lands in is decided at apply time by the applying "
            "role's search_path"
        ),
        file_path=obj.file,
        line_number=obj.line,
        suggested_fix=_suggested_fix(obj, schemas),
    )


def _unqualified(
    obj: SchemaObject,
    kinds: Container[str],
    exempt: Container[tuple[str | None, int]],
) -> bool:
    """A ``CREATE`` with no schema written on it. A temporary table has none to write."""
    if obj.kind not in _RULES or obj.kind not in kinds:
        return False
    if obj.schema is not None or obj.is_temporary:
        return False
    return (obj.file, obj.statement_line) not in exempt


def qualification_findings(
    objects: Iterable[SchemaObject],
    kinds: Container[str],
    *,
    schemas: Sequence[SchemaObject] = (),
    exempt: Container[tuple[str | None, int]] = frozenset(),
) -> list[LintViolation]:
    """One ``qual_*`` finding per ``CREATE`` of a *kinds* object that names no schema.

    In source order. *kinds* is which of :data:`ROUTINE_KINDS` and
    :data:`RELATION_KINDS` the caller selected, so the two codes stay
    independently selectable without the rule reading configuration. *schemas*
    are the ``CREATE SCHEMA`` declarations the same source made, which is what
    the fix suggestion names. *exempt* is the ``(file, statement line)`` of each
    statement carrying the opt-out directive.
    """
    return [_finding(obj, schemas) for obj in objects if _unqualified(obj, kinds, exempt)]
