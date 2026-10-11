"""Where a schema is read from: DDL text, files, a project's build, or a live database.

Each source ends in the one model (``core/schema_model.py``): DDL through the one
read (``core/schema_read.py``), a database through ``live_catalog.read``.
Files are read in the order ``confiture build`` reads them, because the model is
order-aware — a later ``ALTER`` or ``DROP`` folds into what an earlier file
created (#301) — so a directory read here and the same directory built are one
schema.

A comparison of two sources is ``SchemaDiffer.compare_sides``', over each side's
model and the statements that create its views, routines and triggers — a tree's
as written, a database's as PostgreSQL writes them (``live_catalog.catalogued_objects``).
Which rules the comparison applies follows from where each side came from.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

from confiture.core.builder import SchemaBuilder, files_under
from confiture.core.connection import Connection, connection_for
from confiture.core.ddl_walk import AS_WRITTEN
from confiture.core.differ import SchemaDiffer, Side, held_by_definition
from confiture.core.expected_db import ExpectedSchemaDB
from confiture.core.ledger import bookkeeping_tables
from confiture.core.linting.inventory import label_for
from confiture.core.live_catalog import catalogued_objects, user_schemas
from confiture.core.live_catalog import read as read_catalog
from confiture.core.live_catalog import (
    require_supported_pg_tviews_on as _require_supported_pg_tviews_on,
)
from confiture.core.schema_change import SchemaDiff
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import (
    DEFINED_OTHER_KINDS,
    TVIEW_OPTIONS,
    ObjectRef,
    SchemaModel,
    ref_for,
)
from confiture.core.schema_read import SchemaRead, Segment, read_segments
from confiture.core.server_constants import server_constants
from confiture.exceptions import SchemaError

#: DDL text (a ``str``), one file or directory (a ``Path``), or several in order —
#: each a ``Path`` or a ``str`` spelling one.
SchemaSource = str | Path | Sequence[Path | str]

#: What :func:`diff` compares: a schema source, or a database — a URL
#: (``postgresql://…``) or a :class:`Connection`.
DiffSide = SchemaSource | Connection

#: The schemes a database URL starts with, which no DDL text does.
_URL_SCHEMES = ("postgresql://", "postgres://")


def _is_database(side: object) -> bool:
    if isinstance(side, str):
        return side.startswith(_URL_SCHEMES)
    return isinstance(side, Connection)


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


def _segments(
    source: SchemaSource | None, *, env: str | None, project_dir: Path | None
) -> list[Segment]:
    """*source*'s DDL file by file, in the order it is read — the file each came from kept.

    *env* is the project's build: the schema files ``confiture build --schema-only``
    selects, in build order, each named relative to the project, so a position is
    a line of a file the author edits and a statement PostgreSQL rejects is named
    by its file.
    """
    if (source is None) == (env is None):
        raise ValueError("Give exactly one of a schema source or an environment.")
    if env is not None:
        builder = SchemaBuilder(env=env, project_dir=project_dir)
        files, _seeds = builder.categorize_sql_files()
        return selection_segments(files, root=project_dir or Path.cwd())
    if isinstance(source, str):
        return [Segment(None, source)]
    assert source is not None
    paths = [source] if isinstance(source, Path) else [Path(path) for path in source]
    return [Segment(file, _read(file)) for path in paths for file in _files(path)]


def selection_segments(
    files: Iterable[Path], *, root: Path, mapped_from: tuple[Path, Path] | None = None
) -> list[Segment]:
    """A build's selection as the segments a read is made of, each file named relative to *root*.

    *mapped_from* is ``(scratch, repository)`` when the files were read from a
    copy of a git ref (``GitRepository.materialise``): each segment then names the
    file where it sits in the repository, so a finding points at a path the author
    edits, the same path the working tree's build names.
    """
    segments: list[Segment] = []
    for file in files:
        shown = file if mapped_from is None else mapped_from[1] / file.relative_to(mapped_from[0])
        segments.append(Segment(shown, _read(file), label_for(shown, root)))
    return segments


def env_segments(env: str, project_dir: Path | None = None) -> list[Segment]:
    """*env*'s build, file by file: what ``confiture build --env`` selects, in build order."""
    return _segments(None, env=env, project_dir=project_dir)


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
    return read_segments(_segments(source, env=env, project_dir=project_dir))


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
        return read_catalog(conn, schemas=wanted, routines=True, views=True, triggers=True)


def require_supported_pg_tviews_on(database: str | Connection) -> None:
    """Refuse *database*'s pg_tviews where confiture cannot read its TVIEWs.

    The check every live read of TVIEWs makes first (drift, ``migrate up`` of a
    TVIEW migration, ``introspect``), for a tool that asks it before a deploy:
    a database without pg_tviews passes; one whose ``tviews.contract_version()``
    is not the contract confiture reads, or whose registry lacks a column it reads
    (pg_tviews before ``MINIMUM_PG_TVIEWS``), is refused. A URL is connected
    to and closed here; a connection is the caller's.

    Raises:
        ConfigurationError: ``CONFIG_014``, naming the release installed and what it
            lacks; ``CONFIG_006`` when the URL does not connect.
        TypeError: a *database* that is neither a URL nor a :class:`Connection`.
    """
    with connection_for(database) as conn:
        _require_supported_pg_tviews_on(conn)


def database_side(
    database: str | Connection,
    *,
    against: SchemaModel | None = None,
    tracking_table: str | None = None,
) -> Side:
    """The side of a comparison *database* is: its model and the statements PostgreSQL writes.

    Every section is read — tables, types, sequences, routines, views, triggers,
    TVIEWs and the other kinds, these by existence. Compared *against* a tree, the
    database is read in the schemas the tree names (:func:`declared_schemas`), and
    confiture's own tables (``ledger.bookkeeping_tables``, *tracking_table*'s
    ledger among them) are left out unless the tree declares them; with no tree,
    every user schema is read. The default schema, which a tree puts objects in
    without creating, is the tree's whether or not it writes ``CREATE SCHEMA``.
    The model says it is the catalog's (``source``), so a comparison with a tree
    applies the parity rules, and the side carries how its server spells the
    tree's constants (``server_constants``), so a default compares as a value.

    Raises:
        ConfigurationError: ``CONFIG_006`` when the URL does not connect;
            ``CONFIG_014`` when its pg_tviews offers no read contract confiture knows.
        TypeError: a *database* that is neither a URL nor a :class:`Connection`.
    """
    with connection_for(database) as conn:
        wanted = user_schemas(conn) if against is None else declared_schemas(against)
        model = read_catalog(
            conn, schemas=wanted, routines=True, views=True, triggers=True, other_objects=True
        )
        model = _the_projects(model, against, tracking_table)
        constants = AS_WRITTEN if against is None else server_constants(conn, against)
        return Side(model, catalogued_objects(conn, model, wanted), constants=constants)


def materialised_side(
    sql: str,
    scratch_url: str,
    *,
    read: SchemaRead,
    schemas: Sequence[str] | None = None,
    default_schema: str = DEFAULT_SCHEMA,
) -> Side:
    """The side a tree is once PostgreSQL holds it: built into a scratch database, read back.

    *sql* is *read*'s tree as one text. It is applied to a throwaway database on the
    writable server *scratch_url* (``ExpectedSchemaDB``, dropped on the way out,
    whatever happens) with *default_schema* first on its ``search_path``, and read
    as a database is (:func:`database_side`) in *schemas* — the ones the tree
    names when omitted. Every slot the catalog answers is then PostgreSQL's
    analysis of the tree's, so it compares with a database's exactly
    (``differ.MATERIALISED``).

    What the catalog cannot say about the tree is taken from *read*:

    - the statement that creates an object the catalog reads by existence alone
      (a domain, a composite or range type, an aggregate, a policy, a rule, …):
      its existence is compared, and a migration creates it as the tree wrote it;
    - a TVIEW option the tree does not pin, which is pg_tviews' choice, not the
      tree's, whatever the scratch registry holds;
    - what the read had to say: two definitions of one object (``DIFFER_402``), a
      name that needs quotes (``DIFFER_403``), an index written on a relation
      the tree had not declared.

    An object the tree wrote unqualified is found where the build put it, in
    *default_schema*.

    Raises:
        SchemaError: when the scratch server cannot build the tree.
        ConfigurationError: ``CONFIG_014`` when the tree's TVIEWs need a pg_tviews
            the scratch server does not have in a version confiture reads.
    """
    wanted = list(schemas) if schemas is not None else declared_schemas(read.model)
    search_path = None if default_schema == DEFAULT_SCHEMA else default_schema
    with ExpectedSchemaDB(scratch_url).from_source(schema_sql=sql, search_path=search_path) as conn:
        model = read_catalog(
            conn, schemas=wanted, routines=True, views=True, triggers=True, other_objects=True
        )
        model = _the_projects(model, read.model, None)
        objects = catalogued_objects(conn, model, wanted)
    return _with_the_trees(Side(model, objects), Side.of(read, held=True), default_schema)


def _with_the_trees(side: Side, tree: Side, default_schema: str) -> Side:
    """*side*, PostgreSQL's reading of *tree*, with what only *tree* can say.

    A statement the catalog wrote is kept: it is PostgreSQL's reading. An object
    the catalog holds and wrote none for takes the tree's statements, and a TVIEW
    the tree's pinned options. A domain, a type, a policy and a rule take the
    tree's statements too: they are compared by the model's definitions, which
    are PostgreSQL's here, and the statement is what a migration carries, spelled
    as the author spelled it (#708). *tree*'s notes are carried as they are.
    """

    def trees[V](held: Mapping[ObjectRef, V], ref: ObjectRef) -> V | None:
        """What *tree* holds for *ref*; written unqualified, where the build put it."""
        if ref in held or ref.schema != default_schema:
            return held.get(ref)
        return held.get(replace(ref, schema=DEFAULT_SCHEMA))

    model = side.model
    unstated = {
        ref: statements
        for ref in held_by_definition(model) - side.objects.keys()
        if (statements := trees(tree.objects, ref))
    }
    authored = {
        ref: statements
        for ref in side.objects
        if ref.kind in DEFINED_OTHER_KINDS and (statements := trees(tree.objects, ref))
    }
    tviews = {
        ref: replace(view, **{key: getattr(declared, key) for key in TVIEW_OPTIONS})
        if (declared := trees(tree.model.tviews, ref)) is not None
        else view
        for ref, view in model.tviews.items()
    }
    return replace(
        side,
        model=replace(model, tviews=tviews),
        objects={**side.objects, **unstated, **authored},
        warnings=tree.warnings,
        quoted=tree.quoted,
        dangling=tree.dangling,
    )


def _the_projects(
    model: SchemaModel, against: SchemaModel | None, tracking_table: str | None
) -> SchemaModel:
    """*model* without what a database holds for confiture or for every tree.

    Confiture's own tables, and the default schema — which a tree puts objects in
    without creating it — are not the project's unless *against* declares them.
    """
    if against is None:
        return model
    own = bookkeeping_tables(tracking_table)
    default = ref_for("schema", None, DEFAULT_SCHEMA)
    return replace(
        model,
        tables={
            ref: table
            for ref, table in model.tables.items()
            if table.name not in own or ref in against.tables
        },
        other_objects={
            ref: obj
            for ref, obj in model.other_objects.items()
            if ref != default or ref in against.other_objects
        },
    )


def declared_schemas(model: SchemaModel) -> list[str]:
    """Every schema *model* puts an object in or creates, and the default schema.

    What a database is read in when it is compared with a tree: a schema the
    tree never names is not the project's, and every object in it would read
    as one the tree drops.
    """
    placed = {
        ref.schema
        for section in (
            model.tables,
            model.enum_types,
            model.sequences,
            model.routines,
            model.views,
            model.triggers,
            model.tviews,
            model.other_objects,
        )
        for ref in section
    }
    created = {ref.name for ref in model.other_objects if ref.kind == "schema"}
    return sorted(placed | created | {DEFAULT_SCHEMA})


def diff(
    old: DiffSide | None,
    new: DiffSide | None,
    *,
    env: str | None = None,
    project_dir: Path | None = None,
) -> SchemaDiff:
    """What changed from the schema *old* declares to the one *new* declares.

    Each side is anything :func:`parse_schema` takes, or a database — a URL
    (``postgresql://…``) or a :class:`Connection` — read through ``live_catalog``.
    Given as ``None``, a side is *env*'s build from *project_dir*, so ``diff(url,
    None, env="local")`` is what a migration from that database to the current
    tree must do. A database compared with a tree is read in the schemas the tree
    names, and compared through every parity rule: a database built from a tree
    has no change from it.

    Every kind ``migrate diff`` reports, views, routines and triggers included, and
    the warnings it reports beside them — two definitions of one object, resolved
    the way the build resolves them (``DIFFER_402``), and an object a database
    holds that the diff cannot write (``DIFFER_404``).

    Raises:
        ValueError: unless exactly one side is ``None`` when *env* is given, and
            neither is when it is not.
        DifferError: ``DIFFER_403`` when either side names an object that
            needs quotes, which confiture does not support.
        SchemaError: ``DIFFER_400`` when PostgreSQL's parser rejects either side,
            ``SCHEMA_201`` for a path that does not exist, ``SCHEMA_001`` for a
            file that cannot be read as UTF-8 text.
        ConfigurationError: ``CONFIG_006`` when a database URL does not connect.
    """
    if env is not None and (old is None) == (new is None):
        raise ValueError("Give exactly one side as None with an environment: the side it builds.")
    sides = (old, new)
    trees = {
        index: read_schema(side, env=env if side is None else None, project_dir=project_dir)
        for index, side in enumerate(sides)
        if not _is_database(side)
    }
    # A database is read against the tree it is compared with; two databases, whole.
    against = next((tree.model for tree in trees.values()), None)
    held = any(_is_database(side) for side in sides)
    old_side, new_side = (
        Side.of(trees[index], held=held)
        if index in trees
        else database_side(cast("str | Connection", side), against=against)
        for index, side in enumerate(sides)
    )
    return SchemaDiffer().compare_sides(old_side, new_side)
