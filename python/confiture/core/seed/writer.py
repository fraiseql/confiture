"""Seed files written from the schema model: COPY or INSERT, refused at write time when wrong.

A generator hands rows; the model says which table and columns they are for. What
the model can already tell is wrong is refused when the file is written, not one
file into an apply run: a column the table does not have, a column PostgreSQL
fills (``model_facts.writable_columns``), a row that is missing a column or
carries one the file does not write. NOT NULL is not checked — a trigger may fill
a column, and the model does not know what a trigger writes; ``column_facts`` says
which columns are NOT NULL.

Each value becomes PostgreSQL's input text once (:func:`_input_text`), and each
format then writes that text its own way: COPY escapes it
(``copy_formatter.copy_escape``, the one escaper), INSERT quotes it as a literal
— ``E'…'`` when it holds a backslash, so it reads the same whatever
``standard_conforming_strings`` says. Every INSERT value is a literal whatever
the column's type: PostgreSQL types an untyped literal by the column it is
inserted into, exactly as it reads a COPY field.

COPY is what ``seed apply`` loads fastest; INSERT is what a reader can run by
hand. Either way a table's generated key is left out and PostgreSQL fills it —
COPY honours a column's default and identity for every column its list omits.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pglast.stream import maybe_double_quote_name

from confiture.core.model_facts import NotInModelError, table_ref, writable_columns
from confiture.core.schema_model import Column, ObjectRef, SchemaModel, Table
from confiture.core.seed.copy_formatter import copy_escape
from confiture.exceptions import SeedError

#: The two formats a seed is written in.
SeedFormat = Literal["copy", "insert"]

#: Column types whose value is a JSON document.
_JSON_TYPES = frozenset({"json", "jsonb"})

_BACKSLASH = "\\"

#: The one character PostgreSQL text cannot hold, and where psql ends a line.
_NUL = "\x00"


@dataclass(frozen=True)
class SeedFile:
    """A seed file written: where, for which table, which columns, how many rows, how."""

    path: Path
    table: ObjectRef
    columns: tuple[str, ...]
    rows: int
    format: SeedFormat


def _array_text(items: Sequence[object]) -> str:
    """An array literal: every element double-quoted, so no element needs a rule of its own."""
    parts: list[str] = []
    for item in items:
        if item is None:
            parts.append("NULL")
        elif isinstance(item, list | tuple):
            parts.append(_array_text(item))
        else:
            text = _scalar_text(item)
            escaped = text.replace(_BACKSLASH, _BACKSLASH * 2).replace('"', _BACKSLASH + '"')
            parts.append(f'"{escaped}"')
    return "{" + ",".join(parts) + "}"


def _scalar_text(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, bytes | bytearray | memoryview):
        return "\\x" + bytes(value).hex()
    return str(value)


def _input_text(value: object, column: Column, where: str) -> str | None:
    """*value* as the text PostgreSQL's input function for *column* reads; ``None`` is NULL.

    A NUL is refused: PostgreSQL text cannot hold one, and psql ends a line at
    it and reads the next line as that line's rest — a COPY row merged into the
    next, or an INSERT whose next value is read as SQL.
    """
    if value is None:
        return None
    text = _value_text(value, column, where)
    if _NUL in text:
        raise SeedError(
            f"{where} gives {column.name} a NUL character, which PostgreSQL text cannot hold"
        )
    return text


def _value_text(value: object, column: Column, where: str) -> str:
    type_key = column.type_key or ""
    if type_key in _JSON_TYPES:
        return value if isinstance(value, str) else json.dumps(value)
    if isinstance(value, Mapping | list | tuple):
        if not type_key.endswith("[]") or isinstance(value, Mapping):
            raise SeedError(
                f"{where} gives {column.name} a {type(value).__name__}, and {column.name} is "
                f"{column.raw_sql_type}: neither an array nor JSON"
            )
        return _array_text(value)
    return _scalar_text(value)


def _qualified(table: Table) -> str:
    """The table as its schema spells it: a schema only where one was written (#313)."""
    name = maybe_double_quote_name(table.name)
    return f"{maybe_double_quote_name(table.schema)}.{name}" if table.schema else name


def _columns(model: SchemaModel, ref: ObjectRef, names: Sequence[str]) -> list[Column]:
    table = model.tables[ref]
    writable = {column.folded for column in writable_columns(model, ref)}
    found: list[Column] = []
    for name in names:
        column = table.column(name) or next((c for c in table.columns if c.name == name), None)
        if column is None:
            raise SeedError(f"{table.qualified} has no column {name!r}")
        if column.folded not in writable:
            raise SeedError(
                f"PostgreSQL fills {table.qualified}.{column.name} (an identity, generated or "
                "serial column): leave it out of the seed"
            )
        found.append(column)
    return found


def _texts(
    rows: Iterable[Mapping[str, object]], names: Sequence[str], columns: list[Column]
) -> list[list[str | None]]:
    wanted = set(names)
    out: list[list[str | None]] = []
    for number, row in enumerate(rows, 1):
        where = f"row {number}"
        stray = sorted(set(row) - wanted)
        if stray:
            raise SeedError(f"{where} has {stray[0]!r}, which is not among the columns written")
        missing = [name for name in names if name not in row]
        if missing:
            raise SeedError(f"{where} is missing {missing[0]!r}")
        out.append(
            [_input_text(row[name], col, where) for name, col in zip(names, columns, strict=True)]
        )
    return out


def _prepared(
    model: SchemaModel,
    table: ObjectRef | str,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> tuple[ObjectRef, str, list[list[str | None]]]:
    """The table, its header column list and the rows as input text — or a SeedError.

    A table the model lacks is refused as everything else a writer refuses is, so
    a writer raises one class; the lookup that failed is the error's cause.
    """
    try:
        ref = table_ref(model, table)
    except NotInModelError as exc:
        raise SeedError(
            f"the model holds no table {table!r}", resolution_hint=exc.resolution_hint
        ) from exc
    names = list(columns)
    found = _columns(model, ref, names)
    column_list = ", ".join(maybe_double_quote_name(column.folded) for column in found)
    return ref, f"{_qualified(model.tables[ref])} ({column_list})", _texts(rows, names, found)


def _written(
    path: Path, text: str, ref: ObjectRef, columns: Sequence[str], rows: int, fmt: SeedFormat
) -> SeedFile:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
    except OSError as exc:
        raise SeedError(
            f"Cannot write the seed file {path}: {exc}",
            seed_file=str(path),
            resolution_hint="Write to a path whose directory can be created and written to.",
        ) from exc
    return SeedFile(path=path, table=ref, columns=tuple(columns), rows=rows, format=fmt)


def write_copy_seed(
    path: Path | str,
    table: ObjectRef | str,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, object]],
    *,
    model: SchemaModel,
) -> SeedFile:
    """Write *rows* of *table* to *path* as one ``COPY … FROM stdin`` block.

    *columns* are written in the order given, each row a mapping of every one of
    them to its value; ``None`` is NULL. A ``dict`` or ``list`` is JSON for a
    ``json``/``jsonb`` column, and a ``list`` an array for an array column;
    ``bytes`` is ``bytea``. Nothing is written when anything is refused.

    Raises:
        SeedError: a table or column the model does not hold (a table's
            :class:`NotInModelError` is its cause), a column PostgreSQL fills, a
            row missing a column or carrying another, a value the column's type
            cannot take as given, a value holding a NUL, a *path* that cannot be
            written.
    """
    ref, header, texts = _prepared(model, table, columns, rows)
    lines = [f"COPY {header} FROM stdin;"]
    lines += ["\t".join("\\N" if t is None else copy_escape(t) for t in row) for row in texts]
    lines.append("\\.")
    return _written(Path(path), "\n".join(lines) + "\n", ref, columns, len(texts), "copy")


def _literal(text: str | None) -> str:
    if text is None:
        return "NULL"
    quoted = text.replace("'", "''")
    if _BACKSLASH not in text:
        return f"'{quoted}'"
    return "E'" + quoted.replace(_BACKSLASH, _BACKSLASH * 2) + "'"


def write_insert_seed(
    path: Path | str,
    table: ObjectRef | str,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, object]],
    *,
    model: SchemaModel,
) -> SeedFile:
    """Write *rows* of *table* to *path* as one multi-row ``INSERT``.

    The same rows, values and refusals as :func:`write_copy_seed`; every value a
    literal PostgreSQL types by its column.

    Raises:
        SeedError: as :func:`write_copy_seed` does.
    """
    ref, header, texts = _prepared(model, table, columns, rows)
    values = ",\n".join("    (" + ", ".join(_literal(t) for t in row) + ")" for row in texts)
    text = f"INSERT INTO {header} VALUES\n{values};\n" if texts else ""
    return _written(Path(path), text, ref, columns, len(texts), "insert")
