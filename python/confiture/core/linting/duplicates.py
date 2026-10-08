"""Objects defined more than once in one build (#218): ``build_001`` / ``build_002``.

``confiture build`` concatenates files in order. A second ``CREATE OR REPLACE``
silently replaces the first, a second ``CREATE TABLE IF NOT EXISTS`` is a
no-op, and a second plain ``CREATE`` fails the build at that statement — none
of which the author asked for. ``build_001`` reports every definition of the
same object with its file, offset and line and says which one the database
ends up with; ``build_002`` reports a routine whose overloads live in
different files, which is legal but is how the first kind of mistake starts.

The identity of an object is what
:func:`~confiture.core.linting.inventory.group_definitions` groups on —
``(kind, schema, name, signature)``, an unqualified name being the ``public``
schema, so ``f()`` and ``public.f()`` are one object and ``tenant.f()`` another.
The rules that report a property of an object once group through that same
function, so a duplicate can never silence a finding it does not cover.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

import pglast

from confiture.core.linting.inventory import (
    KIND_KEYWORD,
    NameCollision,
    SchemaObject,
    files_alone,
    group_definitions,
    label_for,
    object_key,
)
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity
from confiture.core.sql_lexer import ParsedFile, Rejected, blank_copy_blocks, parse_file


@dataclass(frozen=True)
class Definition:
    """One ``CREATE`` of the object: where it is."""

    file: str | None
    offset: int
    line: int


@dataclass(frozen=True)
class Duplicate:
    """One finding: an object with several definitions, or an overload family split up.

    ``wins`` is ``last`` when every later definition is ``CREATE OR REPLACE``,
    ``first`` when every later one is ``IF NOT EXISTS`` (a no-op), ``conflict``
    when a later plain ``CREATE`` would fail the build, and ``n/a`` for
    ``build_002``.
    """

    rule_id: str
    kind: str
    identity: str
    definitions: tuple[Definition, ...]
    wins: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "kind": self.kind,
            "identity": self.identity,
            "definitions": [asdict(d) for d in self.definitions],
            "wins": self.wins,
        }


def inventory_files(
    files: Iterable[Path], root: Path | None = None
) -> tuple[list[SchemaObject], list[SchemaObject], list[Rejected]]:
    """Inventory each file on its own, so every object knows its file."""
    return inventory_texts((_label(path, root), path.read_text(encoding="utf-8")) for path in files)


def inventory_texts(
    sources: Iterable[tuple[str | None, str]],
) -> tuple[list[SchemaObject], list[SchemaObject], list[Rejected]]:
    """The same, for text already read — one ``(label, text)`` pair per file.

    Returns the objects, the ``CREATE SCHEMA`` declarations and the files
    pglast rejected, each in file order — a file that cannot be parsed is
    reported, never silently skipped. Each file is parsed once, its ``COPY``
    data blanked (``sql_lexer.parse_file``): a seed file is read, not rejected.
    """
    files: list[ParsedFile] = []
    unparseable: list[Rejected] = []
    base = 0
    for label, text in sources:
        try:
            files.append(parse_file(text, label, base))
        except pglast.parser.ParseError as exc:
            if label is not None:
                unparseable.append(Rejected(label=label, text=blank_copy_blocks(text), error=exc))
        base += len(text) + 1
    objects, schemas = files_alone(files)
    return objects, schemas, unparseable


_label = label_for


#: What makes two ``CREATE`` statements definitions of the same object. The
#: inventory's answer, not one of this module's own: the rules that report a
#: property of an object once must group exactly as ``build_001`` does,
#: or a duplicate would silence a documentation finding it did not cover.
_group = group_definitions


def _family(obj: SchemaObject) -> tuple[str, str | None, str]:
    """The overload family a routine belongs to: its identity minus the signature."""
    return object_key(obj)[:3]


def _definition(obj: SchemaObject) -> Definition:
    return Definition(file=obj.file, offset=obj.offset, line=obj.line)


class Created(Protocol):
    """A definition, as far as :func:`wins` needs to know it.

    ``SchemaObject`` satisfies this structurally; :class:`CreateFlags` exists
    for a caller whose own model does not carry the two flags.
    """

    replace: bool
    if_not_exists: bool


@dataclass(frozen=True)
class CreateFlags:
    """How a ``CREATE`` was written, for a reader that keeps its own model.

    ``SchemaDiffer`` builds ``Table`` / ``EnumType`` / ``Sequence`` rather than
    ``SchemaObject``, and needs the same answer about the same tree.
    """

    replace: bool = False
    if_not_exists: bool = False


def wins(group: Sequence[Created]) -> str:
    """Which definition of one object a build keeps, given them in source order.

    ``last`` when every later definition is ``CREATE OR REPLACE``, ``first``
    when every later one is ``IF NOT EXISTS`` (a no-op), ``conflict`` when a
    later plain ``CREATE`` would fail the build at that statement.

    The one answer to that question. ``build_001`` reports it and
    ``SchemaDiffer`` chooses which definition to compare by it, so the diff
    reads the tree the build produces rather than the last statement in the
    file.
    """
    later = group[1:]
    if all(obj.replace for obj in later):
        return "last"
    if all(obj.if_not_exists for obj in later):
        return "first"
    return "conflict"


_wins = wins


def find_duplicates(objects: Sequence[SchemaObject]) -> list[Duplicate]:
    """``build_001`` per object defined more than once, ``build_002`` per split overload family."""
    groups = _group(objects)

    findings: list[Duplicate] = []
    findings.extend(
        Duplicate(
            rule_id="build_001",
            kind=group[0].kind,
            identity=group[0].identity,
            definitions=tuple(_definition(obj) for obj in group),
            wins=_wins(group),
        )
        for group in groups
        if len(group) > 1
    )

    routines: dict[tuple[str, str | None, str], list[SchemaObject]] = defaultdict(list)
    for group in groups:
        first = group[0]
        if first.kind in ("function", "procedure"):
            routines[_family(first)].append(first)
    for family in routines.values():
        files = {obj.file for obj in family}
        if len(family) > 1 and len(files) > 1:
            findings.append(
                Duplicate(
                    rule_id="build_002",
                    kind=family[0].kind,
                    identity=family[0].qualified,
                    definitions=tuple(_definition(obj) for obj in family),
                    wins="n/a",
                )
            )
    findings.sort(key=lambda d: (d.definitions[0].file or "", d.definitions[0].offset, d.rule_id))
    return findings


def _where(definition: Definition) -> str:
    place = f"line {definition.line}, offset {definition.offset}"
    return f"{definition.file} ({place})" if definition.file else place


#: What each :func:`wins` verdict means, in the words every reporter uses.
WINS_TEXT = {
    "last": "the last definition wins (CREATE OR REPLACE)",
    "first": "the first definition wins (later ones are IF NOT EXISTS no-ops)",
    "conflict": "a later plain CREATE fails the build at that statement",
}

_WINS_TEXT = WINS_TEXT


def duplicate_violations(duplicates: Iterable[Duplicate]) -> list[LintViolation]:
    """Render findings as lint violations: ``build_001`` warnings, ``build_002`` info."""
    violations: list[LintViolation] = []
    for dup in duplicates:
        places = "; ".join(_where(d) for d in dup.definitions)
        if dup.rule_id == "build_001":
            message = (
                f"{dup.kind.capitalize()} '{dup.identity}' is defined {len(dup.definitions)} "
                f"times in one build: {places} — {_WINS_TEXT[dup.wins]}"
            )
            severity, name = RuleSeverity.ERROR, "Duplicate Definition"
            fix = "Keep one definition, or make the later file an explicit ALTER."
        else:
            message = (
                f"Overloads of '{dup.identity}' are split across files: {places} — "
                "keep a routine's overloads together so a later file cannot shadow one by accident"
            )
            severity, name = RuleSeverity.INFO, "Split Overloads"
            fix = "Move the overloads into one file."
        violations.append(
            LintViolation(
                rule_id=dup.rule_id,
                rule_name=name,
                severity=severity,
                object_type=dup.kind,
                object_name=dup.identity,
                message=message,
                file_path=dup.definitions[0].file,
                line_number=dup.definitions[0].line,
                suggested_fix=fix,
            )
        )
    return violations


def name_collision_violations(collisions: Iterable[NameCollision]) -> list[LintViolation]:
    """``build_005`` (a create PostgreSQL skips), ``build_006`` (one it refuses): a taken name."""
    violations: list[LintViolation] = []
    for clash in collisions:
        line = f"line {clash.taken_line}"
        taken = f"{clash.taken_file} ({line})" if clash.taken_file else line
        noun = _noun(clash.kind)
        if clash.sqlstate is None:
            rule_id, severity, name = "build_005", RuleSeverity.WARNING, "Object Not Created"
            outcome = f"PostgreSQL skips this statement, so the {noun} it describes is never built"
            fix = f"Give the {noun} its own name, or delete the statement if the first is the one meant."
        else:
            rule_id, severity, name = "build_006", RuleSeverity.ERROR, "Name Taken"
            outcome = (
                f"PostgreSQL refuses this statement ({clash.sqlstate}), and the build stops at it"
            )
            fix = f"Give the {noun} its own name."
        violations.append(
            LintViolation(
                rule_id=rule_id,
                rule_name=name,
                severity=severity,
                object_type=clash.kind,
                object_name=clash.name,
                message=(
                    f"{noun.capitalize()} '{clash.name}': its schema already holds "
                    f"{_a(_noun(clash.taken_by))} of that name ({taken}) — {outcome}"
                ),
                file_path=clash.file,
                line_number=clash.line,
                suggested_fix=fix,
            )
        )
    return violations


def _noun(kind: str) -> str:
    """What a finding calls a kind: ``materialized view``, ``tview`` as ``table``."""
    if kind in ("index", "constraint"):
        return kind
    return KIND_KEYWORD.get(kind, kind.upper()).lower()


def _a(noun: str) -> str:
    """*noun* with its indefinite article: ``an index``, ``a table``."""
    return f"{'an' if noun[0] in 'aeiou' else 'a'} {noun}"
