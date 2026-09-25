"""Where a schema is read from: DDL text, files, a project's build, or a live database.

Each source ends in the one model (``core/schema_model.py``): DDL through the lint
inventory (``inventory.build_inventory``), a database through ``live_catalog.read``.
Files are read in the order ``confiture build`` reads them, because the model is
order-aware — a later ``ALTER`` or ``DROP`` folds into what an earlier file
created (#301) — so a directory read here and the same directory built are one
schema.

A comparison of two sources is ``SchemaDiffer.compare``'s, over their DDL text:
views, routines and triggers are compared as the whole statements that create
them, which the model does not hold, so two models could not be compared for
them at all.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pglast.parser

from confiture.core.builder import SchemaBuilder, files_under
from confiture.core.connection import Connection, connection_for
from confiture.core.ddl_objects import declared_objects
from confiture.core.differ import SchemaDiffer, duplicate_warnings
from confiture.core.linting.inventory import (
    Inventory,
    SchemaObject,
    build_inventory,
    group_definitions,
    kept,
    schema_model,
    with_triggers,
)
from confiture.core.live_catalog import read, user_schemas
from confiture.core.parser_info import parse_error_line
from confiture.core.schema_change import SchemaDiff
from confiture.core.schema_model import SchemaModel
from confiture.core.sql_lexer import blank_copy_blocks
from confiture.exceptions import SchemaError
from confiture.models.warnings import BuildWarning

#: DDL text (a ``str``), one file or directory (a ``Path``), or several in order —
#: each a ``Path`` or a ``str`` spelling one.
SchemaSource = str | Path | Sequence[Path | str]


def _files(path: Path) -> list[Path]:
    if not path.exists():
        raise SchemaError(
            f"Schema source not found: {path}",
            error_code="SCHEMA_201",
            resolution_hint="Pass DDL text as a str, and a file or directory as a Path.",
        )
    return files_under(path) if path.is_dir() else [path]


def _read(file: Path) -> str:
    try:
        return file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SchemaError(
            f"Cannot read schema file {file}: {exc}",
            resolution_hint="A schema file is a readable file of UTF-8 text.",
        ) from exc


#: One piece of a source's DDL: the file it came from (``None`` for text), and its text.
_Segment = tuple[Path | None, str]


def _segments(
    source: SchemaSource | None, *, env: str | None, project_dir: Path | None
) -> list[_Segment]:
    """*source*'s DDL piece by piece, in the order it is read — the file each came from kept."""
    if (source is None) == (env is None):
        raise ValueError("Give exactly one of a schema source or an environment.")
    if env is not None:
        return [(None, SchemaBuilder(env=env, project_dir=project_dir).build(schema_only=True))]
    if isinstance(source, str):
        return [(None, source)]
    assert source is not None
    paths = [source] if isinstance(source, Path) else [Path(path) for path in source]
    return [(file, _read(file)) for path in paths for file in _files(path)]


def _joined(segments: list[_Segment]) -> str:
    return "\n".join(text for _, text in segments)


def schema_text(
    source: SchemaSource | None = None,
    *,
    env: str | None = None,
    project_dir: Path | None = None,
) -> str:
    """The DDL *source* holds, or that ``confiture build --env <env> --schema-only`` writes.

    A ``str`` is DDL text. A ``Path`` is a file, or a directory read the way a bare
    ``include_dirs`` entry is — every ``.sql`` under it, sorted by path. A sequence
    of paths is read in its order, a ``str`` in it being the path it spells. *env*
    reads the project's build instead: the files it selects, seed files left out,
    in build order.

    Raises:
        ValueError: unless exactly one of *source* and *env* is given.
        SchemaError: ``SCHEMA_201`` for a path that does not exist, ``SCHEMA_001``
            for a file that cannot be read as UTF-8 text.
    """
    return _joined(_segments(source, env=env, project_dir=project_dir))


def _where(segments: list[_Segment], line: int) -> tuple[Path | None, int]:
    """The file and the line in it that line *line* of the joined text is."""
    for file, text in segments:
        lines = text.count("\n") + 1
        if line <= lines:
            return file, line
        line -= lines
    return None, line


def _parse_error(segments: list[_Segment], sql: str, exc: Exception) -> SchemaError:
    file, line = _where(segments, parse_error_line(sql, exc))
    where = f"{file}:{line}" if file is not None else f"line {line}"
    return SchemaError(
        f"Cannot parse the schema ({where}): {exc}",
        error_code="DIFFER_400",
        context={"file": str(file) if file is not None else None, "line": line},
        resolution_hint="Fix the SQL syntax in the schema; PostgreSQL rejects it as written.",
    )


@dataclass(frozen=True)
class Definition:
    """One ``CREATE`` statement the model holds, and where it is written.

    Attributes:
        obj: The lint inventory's entry for it — the object as written.
        statement: The statement as pglast returned it; its locations index
            into :attr:`SchemaRead.text`.
        file: The file it is written in, or ``None`` for DDL handed in as text.
        line: The line of that file its ``CREATE`` begins on.
    """

    obj: SchemaObject
    statement: Any
    file: Path | None
    line: int


@dataclass(frozen=True)
class SchemaRead:
    """One parse of a schema source: the model, and what the parse had to say beside it.

    Attributes:
        model: :func:`parse_schema`'s model.
        warnings: Two definitions of one table, type or sequence, resolved the
            way the build resolves them (``DIFFER_402``) — the model holds the one
            the build keeps, and says nothing of the other.
        text: The DDL that was parsed, every file joined in read order.
        definitions: The statement behind each object the model holds, in source
            order — so a reader of the model can name the file and line an object
            is written on, and read what the model does not keep of it.
    """

    model: SchemaModel
    warnings: list[BuildWarning]
    text: str
    definitions: tuple[Definition, ...]
    _segments: tuple[_Segment, ...] = field(default=(), repr=False)

    def where(self, line: int) -> tuple[Path | None, int]:
        """The file, and the line in it, that line *line* of :attr:`text` is."""
        return _where(list(self._segments), line)


def read_schema(
    source: SchemaSource | None = None,
    *,
    env: str | None = None,
    project_dir: Path | None = None,
) -> SchemaRead:
    """:func:`parse_schema`'s model, from one parse, with what that parse knows beside it.

    Raises:
        ValueError, SchemaError: as :func:`parse_schema`; ``DIFFER_400`` names the
            file and line PostgreSQL's parser rejected, in the message and in
            ``context``.
    """
    segments = _segments(source, env=env, project_dir=project_dir)
    sql = _joined(segments)
    blanked = blank_copy_blocks(sql)
    try:
        raws = list(pglast.parser.parse_sql(blanked) or [])
        inventory = build_inventory(blanked, raws)
    except pglast.parser.ParseError as exc:
        raise _parse_error(segments, sql, exc) from exc
    return SchemaRead(
        model=with_triggers(schema_model(inventory), blanked, raws),
        warnings=duplicate_warnings(inventory, declared_objects(blanked, raws).collapsed),
        text=blanked,
        definitions=_definitions(inventory, raws, segments),
        _segments=tuple(segments),
    )


def _definitions(
    inventory: Inventory, raws: list[Any], segments: list[_Segment]
) -> tuple[Definition, ...]:
    """The statement, file and line of each object the model holds.

    An inventory entry knows where its statement's first token is (``offset``),
    and the statements are in source order, so the one it came from is the last
    that starts at or before it.
    """
    starts = [raw.stmt_location or 0 for raw in raws]
    found: list[Definition] = []
    for obj in sorted(
        (kept(group) for group in group_definitions(inventory.objects)), key=lambda o: o.offset
    ):
        raw = raws[bisect.bisect_right(starts, obj.offset) - 1]
        file, line = _where(segments, obj.statement_line)
        found.append(Definition(obj, raw, file, line))
    return tuple(found)


def parse_schema(
    source: SchemaSource | None = None,
    *,
    env: str | None = None,
    project_dir: Path | None = None,
) -> SchemaModel:
    """The model of the schema *source* declares — or *env*'s build, from *project_dir*.

    A ``str`` is DDL text. A ``Path`` is a file, or a directory read the way a
    bare ``include_dirs`` entry is — every ``.sql`` under it, sorted by path. A
    sequence of paths is read in its order, a ``str`` in it being the path it
    spells. *env* reads the project's build instead: the files ``confiture build
    --env <env> --schema-only`` selects, in build order. ``COPY … FROM stdin``
    data is blanked before parsing, so a tree that seeds inline still reads.

    Raises:
        ValueError: unless exactly one of *source* and *env* is given.
        SchemaError: ``DIFFER_400`` when PostgreSQL's parser rejects the DDL,
            naming the file and line; ``SCHEMA_201`` for a path that does not
            exist, ``SCHEMA_001`` for a file that cannot be read as UTF-8 text.
    """
    return read_schema(source, env=env, project_dir=project_dir).model


def introspect(database: str | Connection, *, schemas: Sequence[str] | None = None) -> SchemaModel:
    """The model of what *database* holds in *schemas* — every user schema when omitted.

    Tables, enum types, sequences, routines, views and triggers, read through
    ``live_catalog``, the one reader of a live catalog; an extension's own objects
    are left out, as they are when a tree is compared with a database. A URL is
    connected to and closed here; a connection is the caller's, transaction and all.
    A bare ``str`` is one schema name. A schema the database does not have holds
    nothing, so it adds nothing: ``schemas=["nope"]`` is an empty model, not an
    error.

    Raises:
        ConfigurationError: ``CONFIG_006`` when the URL does not connect.
        TypeError: a *database* that is neither a URL nor a :class:`Connection`.
    """
    with connection_for(database) as conn:
        if schemas is None:
            wanted = user_schemas(conn)
        else:
            wanted = [schemas] if isinstance(schemas, str) else list(schemas)
        return read(conn, schemas=wanted, routines=True, views=True, triggers=True)


def diff(
    old: SchemaSource | None,
    new: SchemaSource | None,
    *,
    env: str | None = None,
    project_dir: Path | None = None,
) -> SchemaDiff:
    """What changed from the schema *old* declares to the one *new* declares.

    Each side is anything :func:`parse_schema` takes: a source, or — given as
    ``None`` — *env*'s build from *project_dir*, so ``diff(snapshot, None,
    env="local")`` is what changed from a snapshot to the current tree.

    Every kind ``migrate diff`` reports, views, routines and triggers included, and
    the warnings it reports beside them — two definitions of one object, resolved
    the way the build resolves them (``DIFFER_402``).

    Raises:
        ValueError: unless exactly one side is ``None`` when *env* is given, and
            neither is when it is not.
        SchemaError: ``DIFFER_400`` when PostgreSQL's parser rejects either side,
            ``SCHEMA_201`` for a path that does not exist, ``SCHEMA_001`` for a
            file that cannot be read as UTF-8 text.
    """
    if env is not None and (old is None) == (new is None):
        raise ValueError("Give exactly one side as None with an environment: the side it builds.")
    old_sql, new_sql = (
        schema_text(side, env=env if side is None else None, project_dir=project_dir)
        for side in (old, new)
    )
    try:
        return SchemaDiffer().compare(old_sql, new_sql)
    except pglast.parser.ParseError as exc:
        raise SchemaError(
            f"Cannot parse a schema being compared: {exc}",
            error_code="DIFFER_400",
            resolution_hint="Fix the SQL syntax in the schemas being compared.",
        ) from exc
