"""Objects defined more than once in one build (#218): ``build_001`` / ``build_002``.

``confiture build`` concatenates files in order. A second ``CREATE OR REPLACE``
silently replaces the first, a second ``CREATE TABLE IF NOT EXISTS`` is a
no-op, and a second plain ``CREATE`` fails the build at that statement — none
of which the author asked for. ``build_001`` reports every definition of the
same object with its file, offset and line and says which one the database
ends up with; ``build_002`` reports a routine whose overloads live in
different files, which is legal but is how the first kind of mistake starts.

The identity of an object is :func:`~confiture.core.linting.inventory.object_key`
— ``(kind, schema, name, signature)``, an unqualified name being the ``public``
schema, so ``f()`` and ``public.f()`` are one object and ``tenant.f()`` another.
The rules that report a property of an object once group by that same key, so a
duplicate can never silence a finding it does not cover.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pglast

from confiture.core.linting.inventory import (
    SchemaObject,
    build_inventory,
    label_for,
    object_key,
)
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity


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
) -> tuple[list[SchemaObject], list[SchemaObject], list[str]]:
    """Inventory each file on its own, so every object knows its file.

    Returns the objects, the ``CREATE SCHEMA`` declarations and the files
    pglast rejected, each in file order — a file that cannot be parsed is
    reported, never silently skipped.
    """
    objects: list[SchemaObject] = []
    schemas: list[SchemaObject] = []
    unparseable: list[str] = []
    for path in files:
        label = _label(path, root)
        try:
            inventory = build_inventory(path.read_text(encoding="utf-8"))
        except pglast.parser.ParseError:
            unparseable.append(label)
            continue
        for obj in (*inventory.objects, *inventory.schemas):
            obj.file = label
        objects.extend(inventory.objects)
        schemas.extend(inventory.schemas)
    return objects, schemas, unparseable


_label = label_for


#: What makes two ``CREATE`` statements definitions of the same object. The
#: inventory's answer, not one of this module's own: the rules that report a
#: property of an object once (LINT-10) must group exactly as ``build_001`` does,
#: or a duplicate would silence a documentation finding it did not cover.
_key = object_key


def _definition(obj: SchemaObject) -> Definition:
    return Definition(file=obj.file, offset=obj.offset, line=obj.line)


def _wins(group: Sequence[SchemaObject]) -> str:
    later = group[1:]
    if all(obj.replace for obj in later):
        return "last"
    if all(obj.if_not_exists for obj in later):
        return "first"
    return "conflict"


def find_duplicates(objects: Sequence[SchemaObject]) -> list[Duplicate]:
    """``build_001`` per object defined more than once, ``build_002`` per split overload family."""
    by_key: dict[tuple[str, str, str, str | None], list[SchemaObject]] = defaultdict(list)
    for obj in objects:
        by_key[_key(obj)].append(obj)

    findings: list[Duplicate] = []
    findings.extend(
        Duplicate(
            rule_id="build_001",
            kind=group[0].kind,
            identity=group[0].identity,
            definitions=tuple(_definition(obj) for obj in group),
            wins=_wins(group),
        )
        for group in by_key.values()
        if len(group) > 1
    )

    routines: dict[tuple[str, str, str], list[SchemaObject]] = defaultdict(list)
    for key, group in by_key.items():
        if key[0] in ("function", "procedure"):
            routines[key[:3]].append(group[0])
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


_WINS_TEXT = {
    "last": "the last definition wins (CREATE OR REPLACE)",
    "first": "the first definition wins (later ones are IF NOT EXISTS no-ops)",
    "conflict": "a later plain CREATE fails the build at that statement",
}


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
            severity, name = RuleSeverity.WARNING, "Duplicate Definition"
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
