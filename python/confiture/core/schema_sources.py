"""Where a schema is read from: DDL text, files, a project's build, or a live database.

Each source ends in the one model (``core/schema_model.py``): DDL through the lint
inventory (``inventory.build_model``), a database through ``live_catalog.read``.
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

from collections.abc import Sequence
from pathlib import Path

import pglast.parser

from confiture.core.builder import SchemaBuilder, files_under
from confiture.core.connection import Connection, connection_for
from confiture.core.differ import SchemaDiffer
from confiture.core.linting.inventory import build_model
from confiture.core.live_catalog import read, user_schemas
from confiture.core.parser_info import parse_error_line
from confiture.core.schema_change import SchemaDiff
from confiture.core.schema_model import SchemaModel
from confiture.core.sql_lexer import blank_copy_blocks
from confiture.exceptions import SchemaError

#: DDL text (a ``str``), one file or directory (a ``Path``), or several in order —
#: each a ``Path`` or a ``str`` spelling one.
SchemaSource = str | Path | Sequence[Path | str]


def _file_text(path: Path) -> str:
    if not path.exists():
        raise SchemaError(
            f"Schema source not found: {path}",
            error_code="SCHEMA_201",
            resolution_hint="Pass DDL text as a str, and a file or directory as a Path.",
        )
    files = files_under(path) if path.is_dir() else [path]
    return "\n".join(_read(file) for file in files)


def _read(file: Path) -> str:
    try:
        return file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SchemaError(
            f"Cannot read schema file {file}: {exc}",
            resolution_hint="A schema file is a readable file of UTF-8 text.",
        ) from exc


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
    if (source is None) == (env is None):
        raise ValueError("Give exactly one of a schema source or an environment.")
    if env is not None:
        return SchemaBuilder(env=env, project_dir=project_dir).build(schema_only=True)
    if isinstance(source, str):
        return source
    if isinstance(source, Path):
        return _file_text(source)
    assert source is not None
    return "\n".join(_file_text(Path(path)) for path in source)


def _model(sql: str) -> SchemaModel:
    try:
        return build_model(blank_copy_blocks(sql))
    except pglast.parser.ParseError as exc:
        raise SchemaError(
            f"Cannot parse the schema (line {parse_error_line(sql, exc)}): {exc}",
            error_code="DIFFER_400",
            resolution_hint="Fix the SQL syntax in the schema; PostgreSQL rejects it as written.",
        ) from exc


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
            ``SCHEMA_201`` for a path that does not exist, ``SCHEMA_001`` for a
            file that cannot be read as UTF-8 text.
    """
    return _model(schema_text(source, env=env, project_dir=project_dir))


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
