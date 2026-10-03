"""One read of DDL: the files it came from in, statements, objects and the model out.

Every reader of a schema tree — ``drift``, ``migrate diff``, the seam's
``parse_schema``, ``squash``'s check, the signature and body checkers — reads it
through :func:`read_segments`, so a tree is parsed once and every reader agrees on
what it declares:

- each file is **parsed once, on its own** (``sql_lexer.parse_file``), its
  ``COPY … FROM stdin`` data blanked, never stripped: a build bundle that seeds
  inline reads (#561), and every object and column is placed in the file that
  wrote it, at the line in that file;
- a rejected statement is ``DIFFER_400`` naming the file and the line in it.

A tree has two models, deliberately. :attr:`SchemaRead.model` is what the tree
*writes* — a partition keeps only the columns written on it, because a migration
generated from it adds a column to the parent and PostgreSQL passes it down.
:attr:`SchemaRead.catalogued` is what PostgreSQL *holds* once the tree is applied —
each child with its parents' columns (``inventory.inherit_columns``) — the model a
reader compares with a live database.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable
from dataclasses import dataclass, replace
from functools import cached_property
from pathlib import Path
from typing import Any

import pglast.parser

from confiture.core.ddl_objects import (
    OBJECT_KEYWORD,
    Collapsed,
    Declared,
    declared_objects,
    declared_triggers,
)
from confiture.core.linting.duplicates import WINS_TEXT, CreateFlags, wins
from confiture.core.linting.inventory import (
    Inventory,
    SchemaObject,
    build_inventory,
    group_definitions,
    inherit_columns,
    kept,
    schema_model,
)
from confiture.core.linting.quoted_names import QuotedName, quoted_names, quoted_trigger_names
from confiture.core.parser_info import parse_error_line
from confiture.core.schema_model import Coverage, SchemaModel, qualified_name, trigger_ref
from confiture.core.sql_lexer import ParsedFile, blank_copy_blocks, parse_file
from confiture.exceptions import SchemaError
from confiture.models.warnings import BuildWarning


@dataclass(frozen=True)
class Segment:
    """One piece of a tree's DDL: the file it is (``None`` for text handed in), and its text.

    ``label`` is how a finding names the file — relative to the project where there
    is one; the file's own spelling when it is not given.
    """

    file: Path | None
    text: str
    label: str | None = None

    @property
    def name(self) -> str | None:
        """How a finding names this piece: its label, its file, or nothing for text."""
        if self.label is not None:
            return self.label
        return None if self.file is None else str(self.file)

    @property
    def piece(self) -> str:
        """The text as it is joined: ending in exactly the newline it has, or one added."""
        return self.text if self.text.endswith("\n") else self.text + "\n"


def joined(segments: Iterable[Segment]) -> str:
    """*segments*' text, joined the one way: each piece ends in a newline, nothing between."""
    return "".join(segment.piece for segment in segments)


@dataclass(frozen=True)
class Definition:
    """One ``CREATE`` statement the model holds, and where it is written.

    Attributes:
        obj: The lint inventory's entry for it — the object as written.
        statement: The statement as pglast returned it; its locations index
            into :attr:`source`'s text.
        file: The file it is written in, or ``None`` for DDL handed in as text.
        line: The line of that file its ``CREATE`` begins on.
        source: The file as it was parsed.
    """

    obj: SchemaObject
    statement: Any
    file: Path | None
    line: int
    source: ParsedFile


@dataclass(frozen=True)
class SchemaRead:
    """One parse of a tree, and everything the readers of a tree ask of it.

    Attributes:
        segments: The files read, in read order.
        files: Each of them as ``sql_lexer.parse_file`` parsed it, in the same order.
        inventory: The lint inventory of the tree.
        declared: ``ddl_objects``' account of the objects compared by definition
            (views, routines, triggers, …) and of the definitions it folded.
    """

    segments: tuple[Segment, ...]
    files: tuple[ParsedFile, ...]
    inventory: Inventory
    declared: Declared

    @cached_property
    def model(self) -> SchemaModel:
        """The schema the tree writes, triggers included."""
        return self._with_triggers(schema_model(self.inventory))

    @cached_property
    def catalogued(self) -> SchemaModel:
        """The schema PostgreSQL holds once the tree is applied: children hold their parents' columns."""
        return self._with_triggers(schema_model(inherit_columns(self.inventory)))

    @cached_property
    def warnings(self) -> list[BuildWarning]:
        """Two definitions of one object, resolved the way the build resolves them (``DIFFER_402``)."""
        return duplicate_warnings(self.inventory, self.declared.collapsed)

    @cached_property
    def quoted(self) -> list[QuotedName]:
        """Every name the tree gives that needs quotes, which confiture refuses (``DIFFER_403``)."""
        triggers = declared_triggers(self.declared.objects)
        return [*quoted_names(self.inventory), *quoted_trigger_names(triggers)]

    @cached_property
    def definitions(self) -> tuple[Definition, ...]:
        """The statement, file and line of each object the model holds, in source order.

        An inventory entry knows where its statement's first token is in the tree
        (``offset``), and each file where it starts (``base``), so the file is the
        last that starts at or before it, and the statement the last in that file.
        """
        bases = [parsed.base for parsed in self.files]
        starts = [[raw.stmt_location or 0 for raw in parsed.statements] for parsed in self.files]
        found: list[Definition] = []
        for obj in sorted(
            (kept(group) for group in group_definitions(self.inventory.objects)),
            key=lambda o: o.offset,
        ):
            at = bisect.bisect_right(bases, obj.offset) - 1
            source = self.files[at]
            raw = source.statements[bisect.bisect_right(starts[at], obj.offset - source.base) - 1]
            found.append(Definition(obj, raw, self.segments[at].file, obj.statement_line, source))
        return tuple(found)

    def _with_triggers(self, model: SchemaModel) -> SchemaModel:
        triggers = declared_triggers(self.declared.objects)
        # A tree says what it declares in every section: silence is absence.
        return replace(
            model, triggers={trigger_ref(t): t for t in triggers}, coverage=Coverage.every()
        )


def read_segments(segments: Iterable[Segment]) -> SchemaRead:
    """Read a tree, given as the files it is made of: each file parsed once, on its own.

    Raises:
        SchemaError: ``DIFFER_400`` when PostgreSQL's parser rejects a statement,
            naming the file and the line in it, in the message and in ``context``.
    """
    pieces = tuple(segments)
    files: list[ParsedFile] = []
    base = 0
    for segment in pieces:
        files.append(_parsed(segment, base))
        base += len(segment.text) + 1
    return SchemaRead(
        segments=pieces,
        files=tuple(files),
        inventory=build_inventory(files),
        declared=declared_objects(files),
    )


def _parsed(segment: Segment, base: int) -> ParsedFile:
    try:
        return parse_file(segment.text, segment.name, base)
    except pglast.parser.ParseError as exc:
        line = parse_error_line(blank_copy_blocks(segment.text), exc)
        at = f"{segment.file}:{line}" if segment.file is not None else f"line {line}"
        raise SchemaError(
            f"Cannot parse the schema ({at}): {exc}",
            error_code="DIFFER_400",
            context={"file": None if segment.file is None else str(segment.file), "line": line},
            resolution_hint="Fix the SQL syntax in the schema; PostgreSQL rejects it as written.",
        ) from exc


def read_text(text: str, file: Path | None = None) -> SchemaRead:
    """Read DDL handed in as one text — *file* the file it is, when it is one."""
    return read_segments([Segment(file, text)])


#: The kinds compared structurally, as a duplicate warning names them.
_DUPLICATE_KINDS: dict[str, str] = {"table": "Table", "type": "Type", "sequence": "Sequence"}


def _structural(obj: SchemaObject) -> bool:
    """A table, an enum or a sequence — what the model holds and is compared structurally."""
    return obj.kind in ("table", "sequence") or (obj.kind == "type" and obj.enum_values is not None)


def duplicate_warnings(
    inventory: Inventory, collapsed: Iterable[Collapsed] = ()
) -> list[BuildWarning]:
    """Say so when one ``(schema, name)`` is defined more than once in one tree.

    Tables, enum types and sequences are read from *inventory*; every object
    compared by definition — a view, a routine, a trigger — from *collapsed*,
    ``ddl_objects.declared_objects``' account of what it folded into one.

    Two definitions of one ``(schema, name)`` collapse into one entry of the
    model (#313). The model keeps the definition a build keeps — a later
    ``IF NOT EXISTS`` is a no-op, a later plain ``CREATE`` fails the build at
    that statement — and the collapse is reported either way. The verdict is
    ``duplicates.wins``, ``build_001``'s own rule. A warning, not a failure: a
    duplicate is ``confiture lint``'s and ``build --fail-on-duplicates``' problem,
    and failing ``--require-migration`` for it would fail the gate for a reason it
    is not about.
    """
    warnings: list[BuildWarning] = []
    for kind in ("table", "type", "sequence"):
        objects = [obj for obj in inventory.objects if obj.kind == kind and _structural(obj)]
        for group in group_definitions(objects):
            if len(group) == 1:
                continue
            verdict = wins(
                [CreateFlags(replace=obj.replace, if_not_exists=obj.if_not_exists) for obj in group]
            )
            first = group[0]
            warnings.append(
                BuildWarning.of(
                    "DIFFER_402",
                    kind=_DUPLICATE_KINDS[kind],
                    identity=qualified_name(first.folded_schema, first.folded_name),
                    count=len(group),
                    outcome=WINS_TEXT[verdict],
                    used="last" if verdict == "last" else "first",
                )
            )
    warnings.extend(
        BuildWarning.of(
            "DIFFER_402",
            kind=OBJECT_KEYWORD[one.kept.ref.kind].capitalize(),
            identity=one.kept.ref.display,
            count=one.count,
            outcome=WINS_TEXT[one.verdict],
            used="last" if one.verdict == "last" else "first",
        )
        for one in collapsed
    )
    return warnings
